#!/usr/bin/env bash
# run-diarization — Nemotron 3 Diarization via audio.cpp, one shot.
#
# Turns a recording into speaker turns, then (optionally) stamps an existing
# WebVTT/SRT transcript with who said what. Up to 8 speakers, arrival-order ids.
#
#   ./run-diarization.sh talk.mp4
#   ./run-diarization.sh talk.mp4 --vtt talk.vtt --names Kem,Chase,Vince
#   ./run-diarization.sh *.mp4 --out /tmp/diar
#
# Output per input, in <out>/<basename>/:
#   turns.json        raw model output (start/end sample, speaker_id, confidence)
#   transcript.vtt    WebVTT with <v Name> voice spans (only with --vtt/--srt)
#   transcript.srt    same, SubRip
#   transcript.txt    [mm:ss] Name: text
#   summary.json      talk time, turn count, mean confidence per speaker
#
# Env: AUDIOCPP_CLI, DIAR_MODEL, DIAR_MODEL_DIR, DIAR_PRECISION

set -uo pipefail

# Needed only by the HIP/ROCm build of audiocpp_cli, which links the ROCm SDK
# from /opt/rocm/lib (not in ldconfig). Harmless for the Vulkan build.
_rocm_lib="${ROCM_LIB_DIR:-/opt/rocm/lib}"
[ -d "$_rocm_lib" ] && export LD_LIBRARY_PATH="${_rocm_lib}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

CLI="${AUDIOCPP_CLI:-/run/media/rodri/AI/audio.cpp/audiocpp_cli}"
MODEL_DIR="${DIAR_MODEL_DIR:-/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/Nemotron-3-Diarization-GGUF}"
HF_REPO="audio-cpp/Nemotron-3-Diarization-GGUF"

BACKEND="vulkan"
THREADS="8"
PRECISION="${DIAR_PRECISION:-bf16}"
LATENCY="very_high"
MERGE_GAP="0.5"
OUT_ROOT=""
TRANSCRIPT=""
NAMES=""
MAP=""
KEEP_WAV=0
QUIET=0
DOWNLOAD_ONLY=0
INPUTS=()

die() { echo "run-diarization: $*" >&2; exit 1; }
say() { [ "$QUIET" = 1 ] || echo "$*"; }

usage() {
  sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --vtt FILE            label this WebVTT (or .srt) transcript with speakers
  --names A,B,C         name speakers in arrival order (speaker_0=A, ...)
  --map 0=Kem,1=Chase   explicit id→name overrides, wins over --names
  --out DIR             output root (default: alongside each input)
  --precision bf16|q8_0 bf16 is parity-safe (default); q8_0 may shift boundaries
  --backend NAME        cpu|hip|rocm|vulkan|cuda|metal (default: vulkan)
  --threads N           backend threads (default: 8)
  --latency-profile P   very_high|low|very_low|ultra_low|asr_la0..asr_la13
  --threshold F         speaker activity threshold 0..1 (default: model, 0.5)
  --min-frames N        drop decoded turns shorter than N 10 ms frames
  --pad-frames N        pad decoded turns by N 10 ms frames
  --merge-gap S         merge same-speaker turns closer than S seconds in the
                        transcript (default 0.5; turns.json stays raw)
  --keep-wav            keep the extracted 16 kHz mono wav
  --download-only       fetch the GGUF and exit
  -q, --quiet           no progress chatter
  -h, --help            this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --vtt|--srt)      TRANSCRIPT="${2:?--vtt needs a file}"; shift 2 ;;
    --names)          NAMES="${2:?--names needs a list}"; shift 2 ;;
    --map)            MAP="${2:?--map needs a list}"; shift 2 ;;
    --out|-o)         OUT_ROOT="${2:?--out needs a dir}"; shift 2 ;;
    --precision)      PRECISION="${2:?}"; shift 2 ;;
    --backend)        BACKEND="${2:?}"; shift 2 ;;
    --threads)        THREADS="${2:?}"; shift 2 ;;
    --latency-profile) LATENCY="${2:?}"; shift 2 ;;
    --threshold)      THRESHOLD="${2:?}"; shift 2 ;;
    --min-frames)     MIN_FRAMES="${2:?}"; shift 2 ;;
    --pad-frames)     PAD_FRAMES="${2:?}"; shift 2 ;;
    --merge-gap)      MERGE_GAP="${2:?}"; shift 2 ;;
    --keep-wav)       KEEP_WAV=1; shift ;;
    --download-only)  DOWNLOAD_ONLY=1; shift ;;
    -q|--quiet)       QUIET=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    -*)               die "unknown option: $1" ;;
    *)                INPUTS+=("$1"); shift ;;
  esac
done

MODEL="${DIAR_MODEL:-$MODEL_DIR/nemotron-3-diarization-${PRECISION}.gguf}"

[ "$PRECISION" = "bf16" ] || [ "$PRECISION" = "q8_0" ] || die "precision must be bf16 or q8_0"

ensure_model() {
  [ -f "$MODEL" ] && return 0
  command -v curl >/dev/null || die "curl missing, cannot fetch $MODEL"
  mkdir -p "$(dirname "$MODEL")" || die "cannot create $(dirname "$MODEL")"
  say "downloading $(basename "$MODEL") from $HF_REPO"
  local progress="--progress-bar"
  [ -t 2 ] || progress="-sS"
  curl -L --fail "$progress" -C - \
    -o "$MODEL.part" \
    "https://huggingface.co/$HF_REPO/resolve/main/$(basename "$MODEL")" \
    || die "download failed"
  mv "$MODEL.part" "$MODEL" || die "cannot install $MODEL"
  say "model ready: $MODEL ($(du -h "$MODEL" | cut -f1))"
}

ensure_model
if [ "$DOWNLOAD_ONLY" = 1 ]; then
  echo "$MODEL"
  exit 0
fi

[ -x "$CLI" ] || die "audiocpp_cli not executable: $CLI"
command -v ffmpeg >/dev/null || die "ffmpeg missing"
[ "${#INPUTS[@]}" -gt 0 ] || { usage; exit 1; }

if [ -n "$TRANSCRIPT" ]; then
  [ "${#INPUTS[@]}" -eq 1 ] || die "--vtt labels one input at a time"
  [ -f "$TRANSCRIPT" ] || die "transcript not found: $TRANSCRIPT"
fi

label_transcript() {
  local turns="$1" media="$2" transcript="$3" outdir="$4" base="$5" rate="$6"
  python3 - "$turns" "$media" "$transcript" "$outdir" "$base" "$rate" "$NAMES" "$MAP" "$MERGE_GAP" <<'PY'
import json, os, re, sys

turns_path, media, src, outdir, base, rate, names, mapping, merge_gap = sys.argv[1:10]
rate = int(rate or 16000)
merge_gap = float(merge_gap or 0.5)

raw = json.load(open(turns_path, encoding="utf-8"))
turns = [
    {"start": t["start_sample"] / rate, "end": t["end_sample"] / rate,
     "id": t["speaker_id"], "conf": float(t.get("confidence") or 0.0)}
    for t in raw
]
turns.sort(key=lambda t: t["start"])

order = []
for t in turns:
    if t["id"] not in order:
        order.append(t["id"])

labels = {}
for i, spk in enumerate(order):
    labels[spk] = f"Speaker {i + 1}"
if names:
    for i, name in enumerate([n.strip() for n in names.split(",") if n.strip()]):
        if i < len(order):
            labels[order[i]] = name
for pair in [p.strip() for p in mapping.split(",") if p.strip()]:
    key, _, val = pair.partition("=")
    key = key.strip()
    if key.startswith("speaker_"):
        labels[key] = val.strip()
    elif key.isdigit() and int(key) < len(order):
        labels[order[int(key)]] = val.strip()

def stamp(sec, sep):
    h, m, s = int(sec // 3600), int(sec % 3600 // 60), sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", sep)

TIMING = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[.,](\d{1,3})")

def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000

cues = []
for block in re.split(r"\n\s*\n", open(src, encoding="utf-8-sig").read().replace("\r\n", "\n")):
    lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
    if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
        continue
    for i, line in enumerate(lines):
        m = TIMING.search(line)
        if not m:
            continue
        text = " ".join(lines[i + 1:])
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            cues.append({"start": secs(*m.group(1, 2, 3, 4)),
                         "end": secs(*m.group(5, 6, 7, 8)),
                         "text": re.sub(r"\s+", " ", text)})
        break

if not cues:
    sys.exit(f"no cues parsed from {src}")

def pick(cue):
    per = {}
    for t in turns:
        overlap = min(cue["end"], t["end"]) - max(cue["start"], t["start"])
        if overlap > 0:
            per[t["id"]] = per.get(t["id"], 0.0) + overlap
    if per:
        spk = max(per, key=per.get)
        share = per[spk] / sum(per.values())
        return spk, share
    mid = (cue["start"] + cue["end"]) / 2
    near = min(turns, key=lambda t: min(abs(t["start"] - mid), abs(t["end"] - mid)))
    return near["id"], 0.0

for cue in cues:
    cue["id"], cue["share"] = pick(cue)

def merged():
    out = []
    for cue in cues:
        prev = out[-1] if out else None
        if prev and prev["id"] == cue["id"] and cue["start"] - prev["end"] <= merge_gap:
            prev["end"] = max(prev["end"], cue["end"])
            prev["text"] += " " + cue["text"]
        else:
            out.append(dict(cue))
    return out

blocks = merged()
os.makedirs(outdir, exist_ok=True)

with open(os.path.join(outdir, "transcript.vtt"), "w", encoding="utf-8") as f:
    f.write("WEBVTT\n\n")
    for i, b in enumerate(blocks, 1):
        f.write(f"{i}\n{stamp(b['start'], '.')} --> {stamp(b['end'], '.')}\n")
        f.write(f"<v {labels[b['id']]}>{b['text']}</v>\n\n")

with open(os.path.join(outdir, "transcript.srt"), "w", encoding="utf-8") as f:
    for i, b in enumerate(blocks, 1):
        f.write(f"{i}\n{stamp(b['start'], ',')} --> {stamp(b['end'], ',')}\n")
        f.write(f"{labels[b['id']]}: {b['text']}\n\n")

with open(os.path.join(outdir, "transcript.txt"), "w", encoding="utf-8") as f:
    for b in blocks:
        f.write(f"[{int(b['start'] // 60):02d}:{int(b['start'] % 60):02d}] {labels[b['id']]}: {b['text']}\n")

talk, count, conf = {}, {}, {}
for t in turns:
    dur = max(0.0, t["end"] - t["start"])
    talk[t["id"]] = talk.get(t["id"], 0.0) + dur
    count[t["id"]] = count.get(t["id"], 0) + 1
    conf[t["id"]] = conf.get(t["id"], 0.0) + t["conf"] * dur
total = sum(talk.values()) or 1.0

summary = {
    "input": os.path.abspath(media),
    "transcript": os.path.abspath(src) if src else None,
    "speakers": [
        {"id": spk, "name": labels[spk], "talk_s": round(talk[spk], 2),
         "share": round(talk[spk] / total, 4), "turns": count[spk],
         "mean_confidence": round(conf[spk] / talk[spk], 4) if talk[spk] else 0.0}
        for spk in sorted(talk, key=lambda s: -talk[s])
    ],
    "mixed_cues": sum(1 for c in cues if c["share"] < 0.7),
    "total_talk_s": round(total, 2),
}
json.dump(summary, open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8"), indent=2)

print(f"  {len(order)} speakers, {len(turns)} turns, {len(blocks)} passages")
for s in summary["speakers"]:
    print(f"    {s['name']:<16} {s['talk_s']:>8.1f}s  {s['share'] * 100:>5.1f}%  "
          f"{s['turns']:>3} turns  conf {s['mean_confidence']:.3f}")
if summary["mixed_cues"]:
    print(f"    {summary['mixed_cues']} cues were mixed-speaker; labelled by dominant talk time")
PY
}

run_one() {
  local input="$1" rate=16000
  [ -f "$input" ] || { echo "  skip, not a file: $input" >&2; return 1; }
  case "$input" in
    *.vtt|*.srt|*.txt|*.md)
      echo "  $input is a transcript, not audio. Diarization needs the recording." >&2
      echo "  rerun with: $0 <recording.mp4> --vtt \"$input\"" >&2
      return 1 ;;
  esac
  local base outdir wav
  base="$(basename "${input%.*}")"
  if [ -n "$OUT_ROOT" ]; then outdir="$OUT_ROOT/$base"; else outdir="$(dirname "$(readlink -f "$input")")/$base.diar"; fi
  mkdir -p "$outdir" || return 1

  say "→ $input"
  wav="$outdir/audio16k.wav"
  ffmpeg -hide_banner -loglevel error -y -i "$input" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$wav" \
    || { echo "  ffmpeg could not decode $input" >&2; return 1; }

  local args=(--task diar --family nemotron_3_diar --model "$MODEL" --backend "$BACKEND"
              --threads "$THREADS" --mode offline --audio "$wav"
              --turns-out "$outdir/turns.json" --metrics
              --session-option "latency_profile=$LATENCY")
  [ -n "${THRESHOLD:-}" ] && args+=(--request-option "speaker_threshold=$THRESHOLD")
  [ -n "${MIN_FRAMES:-}" ] && args+=(--request-option "speaker_min_frames=$MIN_FRAMES")
  [ -n "${PAD_FRAMES:-}" ] && args+=(--request-option "speaker_pad_frames=$PAD_FRAMES")
  [ "$QUIET" = 1 ] || args+=(--log)

  local log="$outdir/diarize.log"
  "$CLI" "${args[@]}" >"$log" 2>&1 || { echo "  diarization failed, see $log" >&2; tail -5 "$log" >&2; return 1; }
  [ -s "$outdir/turns.json" ] || { echo "  no turns written, see $log" >&2; return 1; }

  rate=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$wav")
  say "  turns → $outdir/turns.json"

  if [ -n "$TRANSCRIPT" ]; then
    label_transcript "$outdir/turns.json" "$input" "$TRANSCRIPT" "$outdir" "$base" "$rate"
    say "  transcript → $outdir/transcript.vtt"
  fi

  if [ "$KEEP_WAV" = 0 ]; then rm -f "$wav"; fi
  say "  done"
}

fail=0
for input in "${INPUTS[@]}"; do
  if [ -d "$input" ]; then
    while IFS= read -r f; do run_one "$f" || fail=1; done \
      < <(find "$input" -maxdepth 1 -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' \
            -o -iname '*.flac' -o -iname '*.ogg' -o -iname '*.opus' -o -iname '*.mp4' \
            -o -iname '*.mkv' -o -iname '*.webm' -o -iname '*.mov' \) | sort)
  else
    run_one "$input" || fail=1
  fi
done

exit "$fail"
