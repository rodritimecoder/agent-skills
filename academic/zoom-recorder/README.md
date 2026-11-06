# Zoom Cloud Recording & Transcript Extractor (`zoom-recorder`)

High-efficiency Zoom recording extractor designed for university lectures and meetings. Downloads transcripts (Markdown/VTT) and presentation slides directly without downloading full video files or requiring Zoom Developer Admin credentials.

---

## ⚡ Highlights

- **Zero Admin Credentials Required**: Authenticates with password-protected Zoom cloud recordings (`utsmeet.zoom.us`, `*.zoom.us`) directly using web playback session tokens.
- **Transcript-First Extraction**: Fetches native `.vtt` transcripts in milliseconds and formats them into clean, structured Markdown with timestamps and speaker tags.
- **Enterprise URL Unwrapping**: Unwraps Microsoft SafeLinks (`protection.outlook.com`) and Mimecast (`mimecastprotect.com`) protection URLs automatically.
- **Keyframe Slide Sampling**: Streams presentation video directly via `ffmpeg` to extract slide transitions without downloading gigabytes of video.
- **Canvas LMS Integration**: Pairs with `canvas-cli` to scan course modules, locate recordings and passcodes, and pull transcripts directly into course note directories.

---

## 📦 Requirements

- Python 3.9+
- `pip install requests`
- `ffmpeg` (only required if extracting presentation slide keyframes)

---

## 🚀 Quick Usage

```bash
# 1. Download clean Markdown transcript of a passcode-protected Zoom lecture
python3 scripts/zoom_download.py \
  --url "https://utsmeet.zoom.us/rec/share/..." \
  --passcode "Passcode123" \
  --out-dir "./transcripts" \
  --format md

# 2. Automated Canvas module crawl: fetch all weekly Zoom recordings and transcripts
python3 examples/canvas_zoom_pipeline.py \
  --course-id 41088 \
  --out-dir "./notes/recordings" \
  --format md
```
