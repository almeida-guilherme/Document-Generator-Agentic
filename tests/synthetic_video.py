"""Builds a fake screen recording with known "meaningful moments", to measure frame capture offline.

Each event in the returned list is a moment where the screen reaches a new state that a PDD step
could need a screenshot of. Some are hard cuts (page changes), others are gradual (typing, scrolling)
which is what a cut-based scene detector tends to miss.
"""
import subprocess
import tempfile
import os
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 5


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


FONT, BIG = _font(22), _font(36)


def _page(title, lines=(), fields=(), scroll=0, spinner=None):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 60], fill="#2F5496")
    d.text((20, 12), title, fill="white", font=BIG)
    y = 100 - scroll
    for line in lines:
        if 60 < y < H:
            d.text((40, y), line, fill="black", font=FONT)
        y += 40
    for i, (label, value) in enumerate(fields):
        fy = 120 + i * 70
        d.text((40, fy), label, fill="black", font=FONT)
        d.rectangle([260, fy - 5, 900, fy + 35], outline="gray", width=2)
        d.text((270, fy), value, fill="black", font=FONT)
    if spinner is not None:
        d.arc([600, 330, 680, 410], spinner, spinner + 270, fill="#2F5496", width=8)
    return img


def _cursor(img, t):
    d = ImageDraw.Draw(img)
    x, y = 200 + int(400 * abs(((t / 7) % 2) - 1)), 300 + int(150 * abs(((t / 5) % 2) - 1))
    d.polygon([(x, y), (x, y + 22), (x + 6, y + 16), (x + 15, y + 16)], fill="black")
    return img


def build(path: str, minutes_of_padding: float = 0.0) -> list[dict]:
    """Writes the video to `path`; returns the ground-truth events [{time, label}]."""
    timeline = []  # (duration_s, frame_fn(local_t) -> Image, events[(offset_s, label)])

    def add(duration, fn, events):
        timeline.append((duration, fn, events))

    add(15, lambda t: _page("Intranet - Login", fields=[("User", ""), ("Password", "")]), [(0, "login page")])
    user = "joao.silva"
    add(10, lambda t: _page("Intranet - Login", fields=[("User", user[: int(t)]), ("Password", "")]),
        [(9.9, "username typed")])
    add(5, lambda t: _page("Intranet - Login", fields=[("User", user), ("Password", "*" * min(8, int(t * 3)))]),
        [(4.9, "password typed")])
    add(6, lambda t: _page("Loading...", spinner=int(t * 90) % 360), [])
    add(15, lambda t: _page("Dashboard", lines=["Open orders: 12", "Pending invoices: 4", "Reports"]),
        [(0, "dashboard")])
    orders = [f"Order #{1000 + i}  -  Client {chr(65 + i % 26)}  -  R$ {120 + i * 7},00" for i in range(40)]
    add(20, lambda t: _page("Orders", lines=orders, scroll=int(t * 40)),
        [(0, "orders list top"), (10, "orders list scrolled middle"), (19.9, "orders list scrolled bottom")])
    form = ["Order #1007", "Client H", "R$ 169,00"]
    def fill(t):
        n = min(3, int(t // 5) + 1)
        return _page("New Invoice", fields=[(lbl, form[i] if i < n else "")
                                             for i, lbl in enumerate(["Order", "Client", "Amount"])])
    add(15, fill, [(0, "invoice: order filled"), (5, "invoice: client filled"), (10, "invoice: amount filled")])
    add(8, lambda t: _page("Invoice saved", lines=["Invoice INV-2207 created successfully."]), [(0, "confirmation")])
    if minutes_of_padding:
        # long idle stretch with only the cursor moving (should NOT generate frames)
        add(minutes_of_padding * 60, lambda t: _page("Dashboard", lines=["Open orders: 11"]), [(0, "back to dashboard")])
    add(10, lambda t: _page("Email - Inbox", lines=["Send invoice INV-2207 to client"]), [(0, "email inbox")])

    events, start = [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
               "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        frame_no = 0
        for duration, fn, evs in timeline:
            for off, label in evs:
                events.append({"time": start + off, "label": label})
            for i in range(int(duration * FPS)):
                local_t = i / FPS
                img = _cursor(fn(local_t), frame_no / FPS)
                img.save(proc.stdin, "PNG")
                frame_no += 1
            start += duration
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed to encode the synthetic video")
    return events


if __name__ == "__main__":
    import json, sys
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic.mp4"
    print(json.dumps(build(out), indent=2))
