# Video & Audio Extraction (`references/video.md`)

YouTube captions, video transcription, Bilibili subtitles, and Xiaoyuzhou podcast ASR.

---

## 📺 YouTube Captions & Transcripts

```bash
# 1. Download existing English/auto-generated captions
yt-dlp --write-sub --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "/tmp/%(id)s.%(ext)s" "URL"

# 2. Extract transcript as plain text
sed -e '/^[0-9]/d' -e '/^$/d' -e '/-->/d' /tmp/VIDEO_ID.en.vtt | uniq | head -n 100
```

---

## 🎙️ Xiaoyuzhou (小宇宙) Podcast ASR

For Chinese podcast audio transcription:

```bash
# Search episodes
opencli xiaoyuzhou search "query" -f json

# Transcribe episode audio via local Whisper / Nemotron ASR (:8081)
# (Delegates to local audio intelligence when offline)
```

---

## 📹 Bilibili Subtitles & Search

```bash
FILTER=~/.gemini/config/skills/agent-reach/scripts/reach_filter.py

# Video search with table projection
bili search "query" --type video -n 5 | python3 $FILTER bilibili --table

# Get video subtitle track
bili subtitle "BVID" -o /tmp/bili_sub.json
```
