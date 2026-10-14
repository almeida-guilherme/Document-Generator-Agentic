import os
import io
import base64
import cv2
import numpy as np
from PIL import Image
from langchain_core.messages import HumanMessage
from prompts.caption_prompt import CAPTION_PROMPT

# Change detection runs on a downscaled grayscale copy, so thresholds don't depend on resolution.
COMPARE_WIDTH = 640
PIXEL_DELTA = 25  # per-pixel intensity difference that counts as "changed" (ignores compression noise)


def _small_gray(frame) -> np.ndarray:
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (COMPARE_WIDTH, int(h * COMPARE_WIDTH / w)), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)


def changed_fraction(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.count_nonzero(cv2.absdiff(a, b) > PIXEL_DELTA)) / a.size


def _samples(cap, step: int, fps: float):
    """Yields (image, timestamp) every `step` frames, decoding only the frames it returns."""
    index = 0
    while cap.grab():
        if index % step == 0:
            ok, image = cap.retrieve()
            if ok:
                yield image, index / fps
        index += 1


def create_frames(
    video_path: str,
    output_dir: str = "cache/frames",
    sample_every: float = 0.5,
    change_threshold: float = 0.001,
    detail_threshold: float = 0.0008,
    max_unsettled: float = 4.0,
    max_frames: int = 400,
) -> list[dict]:
    """
    Extracts the screenshots worth documenting from a screen recording.

    Film-style scene detectors miss most UI changes (same background and layout, only text changes),
    so this samples the video and keeps a frame whenever enough pixels differ from the last kept frame:
      - "change":  the screen differs from the last kept frame by >= change_threshold and has settled
                   (it barely differs from the previous sample, so it isn't mid-transition).
      - "before_change": the last settled state of the previous screen, if it was edited since it was kept
                   (e.g. a form fully filled right before clicking Save).
      - "moving":  the screen keeps changing for more than max_unsettled seconds (scrolling, animations),
                   so one frame is taken anyway instead of waiting for it to settle.
      - "start" / "end": first and last state of the video.

    Defaults: a moving mouse cursor changes ~0.07% of pixels, a filled form field ~0.13%.

    Returns frames in chronological order: [{"id", "path", "timestamp", "reason"}].
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps * sample_every))

    os.makedirs(output_dir, exist_ok=True)
    frames: list[dict] = []

    def keep(image, timestamp: float, reason: str):
        frame_id = f"F{len(frames) + 1:03d}"
        path = os.path.join(output_dir, f"{frame_id}.jpg")
        cv2.imwrite(path, image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        frames.append({"id": frame_id, "path": path, "timestamp": round(timestamp, 2), "reason": reason})

    kept_gray = None          # last kept frame
    prev = None               # previous sample: (image, gray, timestamp)
    settled = None            # last sample that was stable (not mid-transition): (image, gray, timestamp)
    settled_kept = True       # whether `settled` is already in `frames`
    unsettled_since = None    # when the screen started changing without settling

    for image, timestamp in _samples(cap, step, fps):
        gray = _small_gray(image)

        if kept_gray is None:
            keep(image, timestamp, "start")
            kept_gray, prev, settled, settled_kept = gray, (image, gray, timestamp), (image, gray, timestamp), True
            continue

        is_stable = changed_fraction(gray, prev[1]) < change_threshold
        if is_stable:
            unsettled_since = None
        elif unsettled_since is None:
            unsettled_since = prev[2]
        moving_too_long = unsettled_since is not None and timestamp - unsettled_since >= max_unsettled

        if changed_fraction(gray, kept_gray) >= change_threshold and (is_stable or moving_too_long):
            # Only when the new screen replaces the settled one; during typing it already contains it.
            if (not settled_kept
                    and changed_fraction(settled[1], kept_gray) >= detail_threshold
                    and changed_fraction(gray, settled[1]) >= change_threshold):
                keep(settled[0], settled[2], "before_change")
            keep(image, timestamp, "change" if is_stable else "moving")
            kept_gray, settled, settled_kept = gray, (image, gray, timestamp), True
            if moving_too_long:
                unsettled_since = timestamp
        elif is_stable:
            settled, settled_kept = (image, gray, timestamp), False

        prev = (image, gray, timestamp)
        if len(frames) >= max_frames:
            print(f"Warning: reached max_frames={max_frames} at {timestamp:.0f}s; the rest of the video is ignored.")
            break

    cap.release()

    if prev is not None and not settled_kept and changed_fraction(settled[1], kept_gray) >= detail_threshold:
        keep(settled[0], settled[2], "end")

    return frames


def encode_image(path: str, max_width: int = 1366) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def caption_frame(frame: dict, llm, max_width: int = 1366) -> dict:
    image_b64 = encode_image(frame["path"], max_width)

    message = HumanMessage(content=[
        {"type": "text", "text": CAPTION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
    ])

    result = llm.invoke([message])

    return {
        "id": frame["id"],
        "timestamp": frame["timestamp"],
        **result.model_dump(),
    }
