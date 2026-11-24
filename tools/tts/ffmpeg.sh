#!/usr/bin/env bash
# Install ffmpeg/ffprobe on the runner: static build from GitHub (BtbN, has libopus), apt as fallback
# (apt mirrors sometimes hang: time limits + retries).
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && exit 0
u=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
for i in 1 2 3; do
  if curl -fsSL --retry 3 --max-time 300 "$u" -o /tmp/ff.tar.xz && mkdir -p /tmp/ff && tar -xJf /tmp/ff.tar.xz -C /tmp/ff --strip-components=1; then
    sudo install -m 755 /tmp/ff/bin/ffmpeg /tmp/ff/bin/ffprobe /usr/local/bin/ && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libopus && exit 0
  fi
  echo "static ffmpeg try $i failed"; sleep 5
done
for i in 1 2 3; do
  timeout 180 sudo apt-get update -q -o Acquire::Retries=3 -o Acquire::http::Timeout=30 >/dev/null 2>&1 || true
  timeout 300 sudo apt-get install -y -q -o Acquire::Retries=3 -o Acquire::http::Timeout=30 ffmpeg >/dev/null && command -v ffprobe && exit 0
  echo "apt try $i failed"; sleep 10
done
exit 1
