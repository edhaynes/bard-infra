# Bard box-demo video

A ~60s narrated demo of the device-only **box join + ping** flow (the four-client
proof in `scripts/smoke_box_demo.py`): four heterogeneous clients — Mac, iPhone,
Linux VM, Android — each generate their own key, join one box, and ping across it.
Zero-trust spine: *nothing leaves your network; trust is earned, never given.*

Narrated by the **Maestro** ElevenLabs voice (the same commissioned voice the
`alpha/video` pitch uses); visuals are branded terminal scenes rendered by Pillow
and muxed by ffmpeg. **Generated media (`*.mp3`, `*.mp4`, `preview/`) is
gitignored — the source is committed.**

These are stylized terminal scenes, not a screen capture of real GUIs; the real
four-GUI recording is the §14 on-device step.

## Regenerate

Requires `ffmpeg`, Pillow, and `ELEVEN_API_KEY` in the environment.

```sh
# 1. narration (Maestro voice) — one ElevenLabs call
python3 gen_narration.py box-demo.txt box-demo.mp3

# 2. render + mux (scene timing auto-fits the narration length)
python3 render_box_demo.py box-demo.mp3 bard-box-demo.mp4
```

## Files

| File | Role |
|------|------|
| `box-demo.txt` | narration script (source of truth; Maestro inverted-grammar voice) |
| `gen_narration.py` | ElevenLabs Maestro TTS (reads `ELEVEN_API_KEY`) |
| `render_box_demo.py` | Bard terminal-scene renderer + ffmpeg mux |
