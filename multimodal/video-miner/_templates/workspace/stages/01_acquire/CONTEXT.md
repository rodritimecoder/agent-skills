# 01_acquire — Download/Ingest Video & Audio

One job: acquire the source video, dump metadata, extract native subtitles if present, and produce a normalized 16 kHz WAV audio file.

## Inputs
- Working (this run): Video URL or local path specified in workspace configuration or CLI argument.
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Future stage directories, unrelated video files.

## Process
1. If the input is a URL (YouTube, Vimeo, etc.), fetch stream metadata and download the best video/audio streams using `yt-dlp`. Also extract native/auto subtitles if available.
2. If the input is a local file, link or copy reference to the local file.
3. Probe video resolution, duration, codec, and fps using `ffprobe`.
4. Extract 16 kHz mono WAV audio using `ffmpeg`:
   ```bash
   ffmpeg -i source_video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output/audio.wav
   ```
5. Emit `output/video_meta.json`.

## Outputs
- `output/source_video.mp4` (or symlink if local)
- `output/audio.wav` (16 kHz mono audio)
- `output/video_meta.json` (duration, fps, resolution, subtitle info)
- `output/subtitles.vtt` (optional, if native captions exist)

## Human check
Verify that `output/audio.wav` plays cleanly and `output/video_meta.json` correctly reflects duration and format. If custom subtitles are preferred, place them in `output/subtitles.vtt`.
