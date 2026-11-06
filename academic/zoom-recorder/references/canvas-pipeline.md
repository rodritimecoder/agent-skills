# Canvas Integration & Downstream Study Workflow

When lecture recordings are posted as Canvas pages or announcements with
passcodes, use `examples/canvas_zoom_pipeline.py`.

## How the pipeline works

1. Calls `canvas-cli modules <course_id>` to list all weekly modules.
2. Fetches the page items inside each module — e.g. `Week 1 - Tutorial video
   recording - Passcode: S!6o2WH?`.
3. Uses regular expressions to parse out the Zoom replay URL and the
   `Passcode: <password>`.
4. Passes each recording to `zoom_download.py`, which un-protects the
   Mimecast link, authenticates with Zoom, and writes clean Markdown
   transcripts grouped by week.

## Downstream: Cornell Notes

Once transcripts are downloaded as Markdown, feed them straight into
`cornell-notes`:

```bash
python3 /run/media/rodri/AI/skills/cornell-notes/format_notes.py \
  --input ~/Downloads/notes/zoom_transcripts/Week_1/tutorial_transcript.md
```

## Token-shielded inspection

Both commands below avoid pulling a full transcript into context. The
outline is roughly 200 tokens where the transcript is 50,000.

```bash
# Metadata only, no files downloaded
python3 /run/media/rodri/AI/skills/zoom-recorder/scripts/zoom_download.py \
  --url "<recording-url>" --passcode "<pwd>" --info-only --table

# A 20-line compact lecture outline
python3 /run/media/rodri/AI/skills/zoom-recorder/scripts/zoom_download.py \
  --url "<recording-url>" --passcode "<pwd>" --outline --table --limit 15
```
