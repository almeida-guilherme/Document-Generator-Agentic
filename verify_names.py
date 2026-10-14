"""
Settles names that the captions read in two ways, by looking again at the frames at full resolution.

Captions see each frame scaled down to ~1366 px wide, where small text such as a title bar is misread
differently from frame to frame (e.g. "5.5.26" read as "5.3.26" in half the frames). The text-only
structuring model can't tell which reading is right. This takes each pair of key names that differ by a
character or two, crops full-resolution tiles from frames whose captions mention either, and asks the
vision model which of the two names actually appears:
  - only one appears in any frame: the other is a misreading and is replaced by it everywhere;
  - both appear (e.g. "Report 5.4.26" and "Report 5.5.26" listed side by side): they are different things;
  - neither: nothing is changed.
"""
import base64
import io
from itertools import combinations
from langchain_core.messages import HumanMessage
from PIL import Image
from pydantic import BaseModel, Field

from schemas import ProcessModel
from structure import is_misreading, replace_names

FRAMES_PER_NAME = 3
TILE_SIZE = (960, 540)  # what the model sees close to native resolution (it scales images to a 768 px short side)

CHECK_PROMPT = """These images are overlapping crops of one screenshot, at full resolution.
Which of the following exact texts appear anywhere in them? Compare character by character: a text that differs in any digit or letter from what is on screen does not appear.

{options}"""


class NameCheck(BaseModel):
    present: list[str] = Field(default_factory=list, description="The options that appear exactly, copied as given; empty if none")


def _tiles(path: str) -> list[str]:
    """Overlapping tiles (half a tile apart), so any text shorter than half a tile is whole in one of them."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = TILE_SIZE
        if img.width <= w and img.height <= h:
            boxes = [(0, 0, img.width, img.height)]
        else:
            xs = sorted({min(x, max(img.width - w, 0)) for x in range(0, max(img.width - w, 0) + w // 2, w // 2)})
            ys = sorted({min(y, max(img.height - h, 0)) for y in range(0, max(img.height - h, 0) + h // 2, h // 2)})
            boxes = [(x, y, min(x + w, img.width), min(y + h, img.height)) for y in ys for x in xs]
        encoded = []
        for box in boxes:
            buffer = io.BytesIO()
            img.crop(box).save(buffer, format="JPEG", quality=90)
            encoded.append(base64.b64encode(buffer.getvalue()).decode())
        return encoded


def _mentions(caption: dict, name: str) -> bool:
    text = " ".join(caption.get("visible_text", [])) + " " + caption.get("observed_action", "")
    return name.lower() in text.lower()


def _spread(items: list, n: int) -> list:
    """Up to n items evenly spread over the list (so checks cover the whole recording)."""
    if len(items) <= n:
        return items
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def conflicting_names(model: ProcessModel) -> list[tuple[str, str]]:
    names = list(dict.fromkeys(k.name.strip() for k in model.key_names))
    return [(a, b) for a, b in combinations(names, 2) if is_misreading(a, b)]


def verify_names(model: ProcessModel, captions: list[dict], frames: list[dict], llm) -> dict:
    """
    Checks each conflicting pair and fixes the model in place. Returns the report entries:
    names_verified (pairs with the evidence found) and names_fixed_by_vision (replacements made).
    """
    conflicts = conflicting_names(model)
    if not conflicts:
        return {"names_verified": [], "names_fixed_by_vision": {}}
    path_by_id = {f["id"]: f["path"] for f in frames}
    check_llm = llm.with_structured_output(NameCheck)
    verified, replacements = [], {}

    for a, b in conflicts:
        found = {a: 0, b: 0}
        candidates = []
        for name in (a, b):
            candidates += _spread([c["id"] for c in captions if _mentions(c, name)], FRAMES_PER_NAME)
        for fid in dict.fromkeys(candidates):
            options = "\n".join(f"- {n}" for n in (a, b))
            content = [{"type": "text", "text": CHECK_PROMPT.format(options=options)}]
            content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{t}", "detail": "high"}}
                        for t in _tiles(path_by_id[fid])]
            result = check_llm.invoke([HumanMessage(content=content)])
            present = {p.strip() for p in result.present} & {a, b}
            for name in present:
                found[name] += 1
        verified.append({"names": [a, b], "frames_checked": len(set(candidates)), "frames_showing": found})
        if found[a] and not found[b]:
            replacements[b] = a
        elif found[b] and not found[a]:
            replacements[a] = b

    used = replace_names(model, replacements)
    # Keep the glossary consistent: a misreading becomes a variant of the name it was mistaken for.
    for wrong, right in replacements.items():
        target = next(k for k in model.key_names if k.name.strip() == right)
        for k in [k for k in model.key_names if k.name.strip() == wrong]:
            target.variants = list(dict.fromkeys(target.variants + [wrong] + k.variants))
            model.key_names.remove(k)
    return {"names_verified": verified, "names_fixed_by_vision": used}
