# 03_visual_sample — Sample Candidate Visual Frames

One job: extract key video frames across the timeline without bloating storage with near-identical slides.

## Inputs
- Working (this run): `../01_acquire/output/source_video.mp4`
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Audio waveforms, transcript text, raw weights.

## Process
1. Extract candidate frames using ffmpeg with scene detection and minimum interval stepping:
   ```bash
   ffmpeg -i ../01_acquire/output/source_video.mp4 -vf "select='gt(scene,0.15)+not(mod(n\,75))',scale='min(1920,iw)':-1" -vsync vfr output/frames/frame_%05d.png
   ```
2. For each extracted frame, compute its exact timestamp and a fast perceptual hash (dHash/pHash).
3. Deduplicate: if consecutive frames have perceptual distance < threshold (identical slides or static screen), drop the redundant frame.
4. Record every retained frame's filename, timestamp in seconds, and hash in `output/manifest.json`.

## Outputs
- `output/frames/*.png` (sampled candidate image frames)
- `output/manifest.json` (list of sampled frames with timestamps)

## Human check
Inspect the frame count in `output/manifest.json`. If coverage is too sparse or too dense, adjust the interval or scene threshold in `_shared/pipeline_rules.md` and re-run.
