"""Rebuild the integrated model and planner from the source archive."""
import argparse,subprocess,sys
from pathlib import Path
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("archive",type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    archive=str(args.archive.resolve(strict=True))
    for step in [["routing.py","build",archive],["route_map.py",archive,"--output-dir","data"],
                 ["pattern_checks.py",archive],["ai/run_pipeline.py",archive],
                 ["import_ai.py"],["export_demo.py"],["checks.py"]]:
        subprocess.run([sys.executable,"-B",*step],cwd=root,check=True)
if __name__=="__main__": main()
