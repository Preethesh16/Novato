"""Render captured terminal output into PNG screenshots, a GIF, and an MP4.

Run: uv run --with pillow python scripts/render_demo.py
Requires ffmpeg and a monospace TrueType font (override NOVATO_DEMO_FONT).
No generated or invented application output: every screen uses capture_demo JSON.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFont

MEDIA = Path(__file__).resolve().parents[1] / "docs" / "media"
FONT = os.environ.get("NOVATO_DEMO_FONT", "/usr/share/fonts/TTF/DejaVuSansMono.ttf")
COLORS = {"pacman": "#67d5f5", "apt": "#ffad80", "dnf": "#93b8ff", "zypper": "#8ee0a1"}


def render(capture, scene, index):
    accent = COLORS[capture["pm"]]
    screen = Image.new("RGB", (1440, 900), "#0b1119")
    draw = ImageDraw.Draw(screen)
    font = ImageFont.truetype(FONT, 21)
    small = ImageFont.truetype(FONT, 17)
    title = ImageFont.truetype(FONT, 30)
    draw.text((48, 30), "NOVATO  /  from novato to pro", font=title, fill="#f0f5fa")
    draw.text((48, 84), capture["distro"], font=font, fill=accent)
    draw.text((48, 120), scene["title"], font=small, fill="#a4b2c5")
    draw.rounded_rectangle((38, 170, 1402, 820), radius=18, fill="#131e2b", outline="#263749", width=2)
    for x, color in zip((66, 91, 116), ("#fa7777", "#f4c66a", "#80cc9a")):
        draw.ellipse((x, 190, x + 12, 202), fill=color)
    draw.text((150, 185), "terminal / basic mode / real container capture", font=small, fill="#9cafc4")
    draw.text((66, 231), "$ " + scene["command"], font=font, fill=accent)
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", scene["output"])
    # Monospace fonts lack these emoji; use readable text equivalents.
    output = output.replace("📋", ">").replace("💡", "*")
    lines = []
    for line in output.strip().splitlines():
        lines.extend(textwrap.wrap(line, width=98, replace_whitespace=False,
                                   drop_whitespace=False) or [""])
    if len(lines) > 20:
        raise ValueError(f"Scene too tall; do not silently crop: {scene['command']}")
    for row, line in enumerate(lines):
        draw.text((66, 281 + row * 25), line, font=font, fill="#e1e9f3")
    foot = "Package actions are dry-run previews. No packages were installed by Novato."
    draw.text((48, 851), foot, font=small, fill="#9cafc4")
    screen.save(MEDIA / f"{capture['pm']}-{index}.png")
    return screen


def main():
    frames, previews = [], []
    for family in ("pacman", "apt", "dnf", "zypper"):
        capture = json.loads((MEDIA / f"{family}.json").read_text())
        for i, scene in enumerate(capture["scenes"]):
            frame = render(capture, scene, i)
            frames.append(frame)
            if i == 1:
                previews.append(frame.resize((960, 600)))
    previews[0].save(MEDIA / "novato-demo.gif", save_all=True, append_images=previews[1:],
                     duration=3500, loop=0, optimize=True)
    with tempfile.TemporaryDirectory(prefix="novato-frames-") as tmp:
        paths = []
        for i, frame in enumerate(frames):
            path = Path(tmp) / f"{i:02}.png"
            frame.save(path)
            paths.append(f"file '{path}'\nduration 6\n")
        listing = Path(tmp) / "frames.txt"
        listing.write_text("".join(paths) + f"file '{path}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listing), "-vf", "fps=24", "-c:v", "libx264", "-crf", "23",
            "-pix_fmt", "yuv420p", "-t", str(len(frames) * 6),
            "-movflags", "+faststart", str(MEDIA / "novato-demo.mp4"),
        ], check=True)
    print("Rendered 12 real terminal captures, GIF preview, and 72-second MP4.")


if __name__ == "__main__":
    main()
