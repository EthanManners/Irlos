#!/usr/bin/env bash
set -euo pipefail
export DISPLAY=:0
export XAUTHORITY=/root/.Xauthority
export XDG_RUNTIME_DIR=/tmp/runtime-root

exec obs --multi \
  --collection "Irlos" \
  --profile "Irlos" \
  --websocket_port 5556
