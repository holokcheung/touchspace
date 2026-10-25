#!/usr/bin/env bash
set -euo pipefail
speech_repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
speech_model_dir="$speech_repo_dir/backend/data/speech"
speech_model_sha=921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f
if ! command -v whisper-cli >/dev/null; then
  echo 'Install whisper.cpp first: brew install whisper.cpp' >&2
  exit 1
fi
mkdir -p "$speech_model_dir"
if [ -f "$speech_model_dir/ggml-tiny.en.bin" ] && echo "$speech_model_sha  $speech_model_dir/ggml-tiny.en.bin" | shasum -a 256 -c - >/dev/null 2>&1; then
  echo 'Local speech model is ready. Restart the TouchSpace backend.'
  exit 0
fi
speech_download="$(mktemp "$speech_model_dir/.tiny.en.XXXXXX")"
trap 'rm -f "$speech_download"' EXIT
curl --fail --location --retry 2 --output "$speech_download" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin
echo "$speech_model_sha  $speech_download" | shasum -a 256 -c -
mv "$speech_download" "$speech_model_dir/ggml-tiny.en.bin"
echo 'Local speech model is ready. Restart the TouchSpace backend.'
