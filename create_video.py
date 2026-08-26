from scenedetect import open_video, SceneManager, AdaptiveDetector
from scenedetect.scene_manager import save_images
import imagehash
from langchain_core.messages import HumanMessage
from schemas import FrameCaption
from PIL import Image
import io
import base64
from prompts.caption_prompt import CAPTION_PROMPT

def create_frames(videoPath):
    video = open_video(videoPath)
    scene_manager = SceneManager()
    scene_manager.add_detector(AdaptiveDetector())
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()
    video = open_video(videoPath)

    image_filenames = save_images(
        scene_list= scene_list,
        video= video,
        num_images=1,
        output_dir="frames/"
    )

    frames = []
    for i, (start,ed) in enumerate(scene_list):
        filename = image_filenames[i][0]
        frames.append({
            "path": f"frames/{filename}",
            "timestamp":start.get_seconds(),
        })

    threshold = 5
    kept = []
    prev_hash = None
    for frame in frames:
        h = imagehash.phash(Image.open(frame["path"]))
        if prev_hash is None or (h - prev_hash) > threshold:
            kept.append(frame)
            prev_hash = h

    return kept

def encode_image(path: str, max_width: int = 800) -> str:
    img = Image.open(path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def caption_frame(frame: dict, llm) -> dict:
    image_b64 = encode_image(frame["path"])

    message = HumanMessage(content=[
        {"type": "text", "text": CAPTION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
    ])

    result: FrameCaption = llm.invoke([message])

    return {
        "path": frame["path"],
        "timestamp": frame["timestamp"],
        **result.model_dump(),
    }