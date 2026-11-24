"""Rebuild all model artifacts from the original Delhi dataset ZIP."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--work-dir", type=Path, default=Path(__file__).parent / "work")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "artifacts")
    args = parser.parse_args()
    archive = str(args.archive.resolve(strict=True))
    work, output = str(args.work_dir.resolve()), str(args.output_dir.resolve())
    root = Path(__file__).resolve().parent
    stages = [
        ["00_match_stops.py", "--archive", archive, "--work-dir", work],
        ["01_build_cells.py", "--work-dir", work, "--output-dir", output],
        ["train.py", "--cells", str(Path(work) / "cells.sqlite"), "--output-dir", output],
    ]
    for stage in stages:
        print(f"Running {stage[0]}", flush=True)
        subprocess.run([sys.executable, "-B", str(root / stage[0]), *stage[1:]], check=True)


if __name__ == "__main__":
    main()
