## Notes

- Output goes to stdout unless `-o` is given, so it pipes cleanly into `jq` or a file.
- Exit status is non-zero if any file fails to convert.
- `--list-formats` and `--doctor` exit without needing an input file.
- `exiftool` (optional) enriches image metadata; without it, images yield only
  the OCR/description text.
- Audio conversion produces metadata only. Audio transcription is not supported.
