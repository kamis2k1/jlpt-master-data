#!/usr/bin/env bash
# Install ffmpeg on the runner (apt mirrors sometimes hang: time limit + retries).
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && exit 0
for i in 1 2 3 4; do
  timeout 240 sudo apt-get update -q -o Acquire::Retries=3 -o Acquire::http::Timeout=30 >/dev/null 2>&1 || true
  timeout 420 sudo apt-get install -y -q -o Acquire::Retries=3 -o Acquire::http::Timeout=30 ffmpeg >/dev/null && command -v ffprobe && exit 0
  echo "apt try $i failed"; sleep 10
done
exit 1
