#!/usr/bin/env bash
# Start N VOICEVOX CPU engines (docker) on ports 50021.. and wait until they answer.
#   usage: engines.sh N [CPU_THREADS]    -> prints the comma separated engine URLs on the last line
set -euo pipefail
n=${1:-1}; th=${2:-}
img=voicevox/voicevox_engine:cpu-latest
docker pull -q "$img" >&2
urls=()
for i in $(seq 0 $((n - 1))); do
  p=$((50021 + i))
  docker run -d --rm --name "vv$i" -p "127.0.0.1:$p:50021" ${th:+-e VV_CPU_NUM_THREADS=$th} "$img" >&2
  urls+=("http://127.0.0.1:$p")
done
for u in "${urls[@]}"; do
  ok=
  for t in $(seq 1 120); do curl -sf "$u/version" >&2 && { ok=1; break; }; sleep 3; done
  [ -n "$ok" ] || { echo "engine $u did not start" >&2; docker logs vv0 >&2 || true; exit 1; }
  echo " $u up" >&2
done
(IFS=,; echo "${urls[*]}")
