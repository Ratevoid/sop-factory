#!/bin/zsh
set -euo pipefail

SOP_AUTOMATION_ROOT="${SOP_AUTOMATION_ROOT:-${0:A:h}}"
SOP_MAIN="$SOP_AUTOMATION_ROOT/sop.py"
if [[ ! -f "$SOP_MAIN" ]]; then
  print -u2 "SOP_INSTALLATION_NOT_FOUND: expected $SOP_MAIN"
  exit 127
fi

# Keep the standalone SOP runtime isolated from a caller's Python environment.
# Hermes exports its own site-packages through PYTHONPATH; inheriting that path
# can load an incompatible Pillow or other dependency into SOP.
export PYTHONPATH="$SOP_AUTOMATION_ROOT"
exec python3 "$SOP_MAIN" "$@"
