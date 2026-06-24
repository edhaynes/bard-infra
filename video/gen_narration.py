"""Synthesize the Bard box-demo narration through the saved Maestro ElevenLabs voice.

Reads ELEVEN_API_KEY from the environment (never hardcoded). Stdlib only.
Usage: python gen_narration.py <spoken-text-file> <out.mp3>

The voice id + settings match the alpha/video pipeline (the same commissioned
"Maestro" voice); the worldly drawl is shaped by the script's inverted grammar,
not by the timbre.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_KEY = os.environ.get("ELEVEN_API_KEY")
if not API_KEY:
    sys.exit("ELEVEN_API_KEY not set in environment")

VOICE_ID = "xnE7vmHjTg1xy0WXwuIX"  # Maestro (voice-experiment/maestro/voice.json)
MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {"stability": 0.4, "similarity_boost": 0.75, "style": 0.3}

text_file, out_path = Path(sys.argv[1]), Path(sys.argv[2])
text = text_file.read_text(encoding="utf-8").strip()

req = urllib.request.Request(
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
    data=json.dumps({"text": text, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}).encode(
        "utf-8"
    ),
    headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        audio = resp.read()
except urllib.error.HTTPError as e:
    sys.exit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
except urllib.error.URLError as e:
    sys.exit(f"Network error: {e}")

out_path.write_bytes(audio)
print(f"Wrote {out_path} ({len(audio)} bytes)")
