"""Export the selected journey and operator rankings to a single offline HTML file."""
import json
from pathlib import Path
import routing

ROOT = Path(__file__).resolve().parent


def build():
    example = json.loads((ROOT / 'data/example.json').read_text(encoding='utf-8'))
    query = example["origin"]["id"], example["destination"]["id"], example["date"], example["time"]
    plan = routing.plan(*query, 0)
    # Reuse equivalent slider outcomes. Every saved recommendation comes from the
    # same routing engine as the live planner, including its evidence checks.
    advice_ids, unique, lookup = [], [], {}
    for preference in range(101):
        item = routing.advice(*query, preference)
        key = json.dumps(item, sort_keys=True)
        if key not in lookup:
            lookup[key] = len(unique)
            unique.append(item)
        advice_ids.append(lookup[key])
    hotspots = json.loads((ROOT / "data/hotspots.json").read_text(encoding="utf-8"))
    snapshot = dict(example=example, plan=plan, advice=unique, advice_ids=advice_ids, hotspots=hotspots)
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).replace("<", chr(92) + "u003c")
    adapter = """
window.busAtlasApi = async function(path, params = {}) {
    const value = Math.max(0, Math.min(100, Number(params.preference || 0)));
    if (path === '/v1/example') return snapshot.example;
    if (path === '/v1/advice') return snapshot.advice[snapshot.advice_ids[value]];
    if (path === '/v1/plan') {
        const w = value / 100;
        const weighted = o => (1-w)*o.time_score + w*o.comfort_score;
        const tie = w < 0.5 ? 'time_rank' : 'comfort_rank';
        const options = [...snapshot.plan.options].sort((a,b) => weighted(a)-weighted(b) || a[tie]-b[tie]);
        return {...snapshot.plan, options};
    }
    if (path === '/v1/hotspots') return snapshot.hotspots[params.day + '/' + (params.bin ?? params.hour)] || [];
    if (path === '/v1/stops/search') return [];
    throw new Error('Unknown demo request');
};
"""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>' + css + '</style>')
    for script in ("app.js", "journey_ai.js"):
        html = html.replace(f'<script defer src="/{script}"></script>', '')
    html = html.replace('<h2>Journey details</h2>', '<h2>Example journey</h2><p>Saved from the October model. Open the full planner to change the stops or departure.</p>')
    for field in ("origin", "destination", "date", "time"):
        html = html.replace(f'<input id="{field}"', f'<input disabled id="{field}"')
    html = html.replace('<button id="swap"', '<button hidden id="swap"').replace('<button class="primary-btn"', '<button hidden class="primary-btn"')
    scripts = [f"const snapshot={payload};", adapter, (ROOT / "journey_ai.js").read_text(encoding="utf-8"),
               (ROOT / "app.js").read_text(encoding="utf-8")]
    html = html.replace("</body>", "<script>" + chr(10).join(scripts) + "</script></body>")
    (ROOT / "Journey demo.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build()
