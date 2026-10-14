import argparse
from dotenv import load_dotenv
from pipeline import run_pdd_pipeline, new_run_dir, print_report

load_dotenv()

parser = argparse.ArgumentParser(description="Generate a Process Design Document (PDD) from a screen recording.")
parser.add_argument("video", help="path to the screen recording")
parser.add_argument("--runs-dir", default="runs", help="where each run's folder is created (default: runs/)")
parser.add_argument("--window", type=int, default=30, help="observations per structuring call (default: 30)")
parser.add_argument("--sample-every", type=float, default=0.5, help="seconds between sampled frames (default: 0.5)")
parser.add_argument("--change-threshold", type=float, default=0.001,
                    help="fraction of changed pixels that counts as a new screen state (default: 0.001)")
args = parser.parse_args()

run_dir = new_run_dir(args.video, args.runs_dir)
output, report = run_pdd_pipeline(
    args.video,
    run_dir,
    max_frames_per_window=args.window,
    frame_options={"sample_every": args.sample_every, "change_threshold": args.change_threshold},
)
print_report(report)
print(f"Document generated: {output}")
print(f"Run folder (frames, captions, report): {run_dir}")
