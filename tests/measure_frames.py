"""Phase 0: measures how many meaningful screen states a frame extractor captures.

Usage: python -m tests.measure_frames <module>   (module exposing create_frames(video_path, output_dir))
An event counts as captured if some kept frame falls between it and the next event, i.e. the
screenshot shows that state before the screen moved on.
"""
import importlib
import json
import sys
import tempfile
import os
from tests.synthetic_video import build


def measure(create_frames, padding_minutes=0.0):
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "synthetic.mp4")
        events = build(video, minutes_of_padding=padding_minutes)
        frames = create_frames(video, output_dir=os.path.join(tmp, "frames"))
        times = sorted(f["timestamp"] for f in frames)
        missed = []
        for i, ev in enumerate(events):
            end = events[i + 1]["time"] if i + 1 < len(events) else float("inf")
            if not any(ev["time"] <= t < end for t in times):
                missed.append(ev["label"])
        return {"events": len(events), "captured": len(events) - len(missed),
                "frames_kept": len(frames), "missed": missed}


if __name__ == "__main__":
    mod = importlib.import_module(sys.argv[1])
    for pad in (0.0, 10.0):
        print(f"padding={pad}min", json.dumps(measure(mod.create_frames, pad)))
