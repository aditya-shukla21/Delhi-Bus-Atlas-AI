"""Serve the offline Delhi bus planner on the loopback interface."""

import argparse
import json
import re
import webbrowser
import zipfile
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import operator_view
import routing


ROOT = Path(__file__).resolve().parent

# GitHub stores the large runtime crowd database as a compressed archive.
# Restore it automatically on first launch; the extracted DB is git-ignored.
_CROWD_DB = ROOT / "data" / "crowding.sqlite"
_CROWD_ARCHIVE = ROOT / "data" / "crowding.sqlite.zip"
if not _CROWD_DB.exists() and _CROWD_ARCHIVE.exists():
    with zipfile.ZipFile(_CROWD_ARCHIVE) as _archive:
        _archive.extract("data/crowding.sqlite", ROOT)

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/journey_ai.js": ("journey_ai.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "DelhiBusAtlas"

    def log_message(self, format, *args):
        # Trip queries include a user's intended origin and destination.
        pass

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, content):
        self.respond(status, json.dumps(content, ensure_ascii=False, allow_nan=False).encode(),
                     "application/json; charset=utf-8")

    def do_GET(self):
        try:
            if len(self.path) > 2048:
                self.json_response(HTTPStatus.REQUEST_URI_TOO_LONG, {"error": "Request is too long."})
                return
            url = urlsplit(self.path)
            if url.path in ASSETS:
                filename, content_type = ASSETS[url.path]
                self.respond(HTTPStatus.OK, (ROOT / filename).read_bytes(), content_type)
                return
            fields = parse_qs(url.query, keep_blank_values=True, max_num_fields=8)

            def field(key, limit=100):
                values = fields.get(key, [])
                if len(values) != 1 or not 0 < len(values[0].strip()) <= limit:
                    raise ValueError(f"Enter a valid {key}.")
                return values[0].strip()

            if url.path == "/health":
                result = {"status": "ok"}
            elif url.path == "/v1/example":
                result = json.loads((ROOT / "data" / "example.json").read_text(encoding="utf-8-sig"))
            elif url.path == "/v1/stops/search":
                result = routing.search_stops(field("q"))
            elif url.path in ("/v1/plan", "/v1/advice"):
                origin, destination = field("from"), field("to")
                travel_date, travel_time = field("date", 10), field("time", 5)
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", travel_date):
                    raise ValueError("Enter a date in YYYY-MM-DD format.")
                date.fromisoformat(travel_date)
                if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", travel_time):
                    raise ValueError("Enter a departure time in 24-hour HH:MM format.")
                preference = field("preference" if "preference" in fields else "comfort", 10)
                if preference not in ("fast", "comfort") and not (
                    re.fullmatch(r"[0-9]{1,3}", preference) and 0 <= int(preference) <= 100
                ):
                    raise ValueError("Choose a travel preference.")
                if origin == destination:
                    raise ValueError("Choose different origin and destination stops.")
                query = routing.plan if url.path == "/v1/plan" else routing.advice
                result = query(origin, destination, travel_date, travel_time, preference)
            elif url.path == "/v1/hotspots":
                day = field("day", 16)
                hour = int(field("bin" if "bin" in fields else "hour", 2))
                if day not in ("weekday", "saturday", "sunday") or not 0 <= hour < 48:
                    raise ValueError("Choose a day type and a half-hour bin from 0 to 47.")
                result = operator_view.hotspots(day, hour)
            else:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
                return
            self.json_response(HTTPStatus.OK, result)
        except (ValueError, KeyError):
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": "Check the selected stops, date and time."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR,
                               {"error": "The planner could not read its local data. Check the data setup and try again."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the planner in your default browser")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with ThreadingHTTPServer(("127.0.0.1", args.port), RequestHandler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Delhi Bus Atlas is ready at {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
