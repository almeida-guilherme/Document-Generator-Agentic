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
parser.add_argument("--caption-width", type=int, default=1366,
                    help="width frames are shrunk to before captioning; smaller is cheaper but small text "
                         "(file names, column headers) gets misread (default: 1366, the useful maximum)")
parser.add_argument("--from-run", metavar="RUN_DIR",
                    help="reuse frames, captions and transcript from an earlier run of the same video "
                         "(only structuring and the document are redone)")
parser.add_argument("--template", metavar="DOCX",
                    help="a company PDD template to write the document into (its examples and instructions are "
                         "removed, its sections filled); a resumed run uses the template it started with")
parser.add_argument("--resume", metavar="RUN_DIR",
                    help="continue an interrupted run in its own folder; stages already done are not redone")
args = parser.parse_args()
if args.resume and args.from_run:
    parser.error("use either --resume or --from-run, not both")

run_dir = args.resume or new_run_dir(args.video, args.runs_dir)
output, report = run_pdd_pipeline(
    args.video,
    run_dir,
    max_frames_per_window=args.window,
    frame_options={"sample_every": args.sample_every, "change_threshold": args.change_threshold},
    caption_width=args.caption_width,
    from_run=args.from_run,
    template_path=args.template,
)
print_report(report)
print(f"Document generated: {output}")
print(f"Run folder (frames, captions, report): {run_dir}")
