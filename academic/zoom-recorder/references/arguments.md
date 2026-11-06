# CLI Arguments

| Argument | Description | Default |
|---|---|---|
| `--url <url>` | Zoom cloud recording URL (`/rec/play` or `/rec/share`) | Required |
| `--passcode, -p <pwd>` | Recording passcode (if protected) | `""` |
| `--out-dir, -o <dir>` | Destination folder for saved files | `.` |
| `--format` | Output format: `md` (Markdown), `vtt` (raw WebVTT), `txt` (plain text), `all` | `md` |
| `--keyframes` | Stream video with ffmpeg to extract slide changes | Disabled |
| `--scene-threshold` | Sensitivity for slide change scene detection (`0.0` - `1.0`) | `0.35` |
| `--table, -t` | Render output as high-density Markdown pipe tables | Disabled |
| `--outline, --agenda` | Extract high-density chronological agenda/outline table (~200 tokens) | Disabled |
| `--info-only, --info` | Retrieve recording metadata only without downloading files | Disabled |
| `--project <fields>` | Comma-separated fields to project in output (e.g. `topic,duration`) | Disabled |
| `--limit, -n <N>` | Cap the number of outline rows returned | `0` (unlimited) |
| `--json` | Print extracted recording metadata or outline to stdout as JSON | Disabled |

## Reading the slides

`--keyframes` writes the detected slide changes to `<slug>_slides/*.png`. OCR is
not part of this skill; hand the frames to the `ocr` skill, which owns the
models and the servers:

```bash
python3 $ZR/zoom_download.py --url "<url>" --passcode "<pwd>" --keyframes -o ./rec
for f in ./rec/*_slides/*.png; do ocr "$f" -o "${f%.png}.md"; done
```

