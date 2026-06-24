"""Render the Bard box-demo video: branded terminal scenes + splash/close cards,
streamed to ffmpeg and muxed with the Maestro narration. Pillow + ffmpeg only.

Scene boundaries are FRACTIONS of the narration duration, so the video auto-fits
whatever length the Maestro track comes out to (no hardcoded seconds to retune).

Adapted from alpha/video/render.py (same proven typing/stream/mux approach).
Usage: python render_box_demo.py box-demo.mp3 bard-box-demo.mp4
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 24
MONO = "/System/Library/Fonts/Menlo.ttc"
SANS = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

BG = (13, 17, 23)  # terminal background (#0d1117)
CHROME = (22, 27, 34)  # window title bar
TXT = (201, 209, 217)  # default text
DIM = (139, 148, 158)  # comments / secondary
GREEN = (63, 185, 80)  # JOINED / received
RED = (248, 81, 73)  # the mistake
BLUE = (88, 166, 255)  # prompt $
WHITE = (240, 246, 252)
NAVY = (10, 22, 49)  # Bard splash background
GOLD = (212, 175, 55)  # Bard accent bar

f_body = ImageFont.truetype(MONO, 32, index=0)
f_small = ImageFont.truetype(MONO, 26, index=0)
f_title = ImageFont.truetype(SANS, 170)
f_sub = ImageFont.truetype(SANS, 46)

P, G, R, D = TXT, GREEN, RED, DIM  # shorthand for scene line colors

# Each scene: list of lines; each line: list of (text, color) segments.
PROBLEM = [
    [("$ ", BLUE), ("bard devices", WHITE)],
    [("", TXT)],
    [("  laptop    Mac          local", P)],
    [("  phone     iPhone       wifi", P)],
    [("  server    Linux VM     vlan", P)],
    [("  mobile    Android      cellular", P)],
    [("", TXT)],
    [("  trust between them .... ", P), ("ASSUMED", R)],
    [("  ", TXT), ("# location is not identity", D)],
]
BOX = [
    [("$ ", BLUE), ('bard box create "Demo Box"', WHITE)],
    [("", TXT)],
    [("  box-demo  ", P), ("created.", G)],
    [("  a private room of your own", D)],
    [("", TXT)],
    [("  ", TXT), ('# nothing trusted for being "inside the wall"', D)],
]
JOIN = [
    [("$ ", BLUE), ("bard join", WHITE), ("   (each device makes its own key)", D)],
    [("", TXT)],
    [("  Mac        keygen + redeem .... ", P), ("JOINED", G)],
    [("  iPhone     keygen + redeem .... ", P), ("JOINED", G)],
    [("  Linux VM   keygen + redeem .... ", P), ("JOINED", G)],
    [("  Android    keygen + redeem .... ", P), ("JOINED", G)],
    [("", TXT)],
    [("  members: 4   ", P), ("# a key never shared, never sent", D)],
]
PING = [
    [("$ ", BLUE), ("bard ping", WHITE), ("   (Mac speaks)", D)],
    [("", TXT)],
    [("  Mac  ->  box-demo", P)],
    [("     iPhone   .... ", P), ("ping received", G)],
    [("     Linux VM .... ", P), ("ping received", G)],
    [("     Android  .... ", P), ("ping received", G)],
    [("", TXT)],
    [("  ", TXT), ("# no shared password. no server you don't own.", D)],
]

# (label, scene_lines, start_frac, end_frac) of the total duration.
SCENES = [
    ("problem", PROBLEM, 0.09, 0.30),
    ("box", BOX, 0.30, 0.44),
    ("join", JOIN, 0.44, 0.69),
    ("ping", PING, 0.69, 0.90),
]
SPLASH_END_FRAC = 0.09
CLOSE_START_FRAC = 0.90


def flatten(lines):
    flat = []
    for line in lines:
        for text, color in line:
            for ch in text:
                flat.append((ch, color))
        flat.append(("\n", None))
    return flat


def grouped_lines(flat, n):
    """Reconstruct display lines (runs of same-color text) from first n chars."""
    out, line = [], []
    run_text, run_color = "", None
    for ch, color in flat[:n]:
        if ch == "\n":
            if run_text:
                line.append((run_text, run_color))
            out.append(line)
            line, run_text, run_color = [], "", None
            continue
        if color != run_color and run_text:
            line.append((run_text, run_color))
            run_text = ""
        run_text, run_color = run_text + ch, color
    if run_text:
        line.append((run_text, run_color))
    if line:
        out.append(line)
    return out


def window(draw):
    """Draw the terminal window chrome; return (x, y) of the body origin."""
    x0, y0, x1, y1 = 160, 150, W - 160, H - 150
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=BG, outline=(48, 54, 61), width=2)
    draw.rounded_rectangle([x0, y0, x1, y0 + 56], radius=18, fill=CHROME)
    draw.rectangle([x0, y0 + 38, x1, y0 + 56], fill=CHROME)
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([x0 + 26 + i * 34, y0 + 19, x0 + 44 + i * 34, y0 + 37], fill=col)
    draw.text((x0 + 150, y0 + 16), "bard - box demo", font=f_small, fill=DIM)
    return x0 + 44, y0 + 92


def render_scene(lines, reveal):
    img = Image.new("RGB", (W, H), (8, 10, 14))
    d = ImageDraw.Draw(img)
    bx, by = window(d)
    flat = flatten(lines)
    n = max(0, min(len(flat), int(len(flat) * reveal)))
    disp = grouped_lines(flat, n)
    typing = reveal < 1.0
    y = by
    for li, line in enumerate(disp):
        x = bx
        for text, color in line:
            d.text((x, y), text, font=f_body, fill=color or TXT)
            x += d.textlength(text, font=f_body)
        if typing and li == len(disp) - 1:
            d.rectangle([x + 2, y + 4, x + 18, y + 36], fill=TXT)
        y += 46
    d.rectangle([0, H - 8, W, H], fill=GOLD)
    return img


def render_card(big, sub):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    tw = d.textlength(big, font=f_title)
    d.text(((W - tw) / 2, 360), big, font=f_title, fill=WHITE)
    d.rectangle([(W - 320) / 2, 580, (W + 320) / 2, 590], fill=GOLD)
    sw = d.textlength(sub, font=f_sub)
    d.text(((W - sw) / 2, 630), sub, font=f_sub, fill=GOLD)
    d.rectangle([0, H - 8, W, H], fill=GOLD)
    return img


def frame_at(t, total):
    frac = t / total if total else 1.0
    if frac < SPLASH_END_FRAC:
        return ("splash", render_card("BARD", "your private fabric - zero trust"))
    if frac >= CLOSE_START_FRAC:
        return ("close", render_card("BARD", "nothing leaves your network. trust, earned."))
    for label, lines, s, e in SCENES:
        if s <= frac < e:
            reveal = min(1.0, (frac - s) / ((e - s) * 0.62))
            return (f"{label}:{int(reveal * 240)}", render_scene(lines, reveal))
    return ("blank", Image.new("RGB", (W, H), (8, 10, 14)))


def main():
    audio, out = sys.argv[1], sys.argv[2]
    dur = float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio,
            ]
        ).strip()
    )
    total = dur + 0.4
    nframes = int(total * FPS)
    ff = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{W}x{H}",
            "-framerate",
            str(FPS),
            "-i",
            "-",
            "-i",
            audio,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "19",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            out,
        ],
        stdin=subprocess.PIPE,
    )
    preview = Path("preview")
    preview.mkdir(exist_ok=True)
    last_key, last_bytes, saved = None, None, set()
    for i in range(nframes):
        t = i / FPS
        key, img = frame_at(t, total)
        if key == last_key:
            ff.stdin.write(last_bytes)
            continue
        last_bytes = img.tobytes()
        last_key = key
        ff.stdin.write(last_bytes)
        tag = key.split(":")[0]
        if tag not in saved:
            img.save(preview / f"{tag}.png")
            saved.add(tag)
    ff.stdin.close()
    ff.wait()
    print(f"wrote {out} ({nframes} frames, {total:.1f}s); previews in {preview}/")


if __name__ == "__main__":
    main()
