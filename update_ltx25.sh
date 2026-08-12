#!/bin/bash
# Bring both render backends up to LTX-2.5, and pin what they land on.
#
#   ./update_ltx25.sh cerberus     native venv + systemd, plus SwarmUI
#   ./update_ltx25.sh gamingpc     docker image rebuild
#   ./update_ltx25.sh all
#
# Idempotent: re-running when everything already matches the pins is a no-op
# apart from a service restart.
#
# THE POINT OF THE CUDA BUMP, since it is not obvious and not in any doc:
# comfy/quant_ops.py does `ck.registry.disable("cuda")` when torch.version.cuda
# < 13. Both boxes ran torch 2.11.0+cu128, so comfy-kitchen's CUDA backend was
# switched off and LTX-2.5's int8-convrot / nvfp4 matmuls fell through to the
# eager backend. Confirmed in gamingpc's own startup log before this change:
#     cuda:   {'available': True,  'disabled': True }
#     eager:  {'available': True,  'disabled': False}
# Same torch version either side of the move -- only the CUDA build changes.
set -euo pipefail

COMFY_REF=${COMFY_REF:-26d7f8556822d9d08c2d3e1878636ac3b4969af9}   # 2026-08-11, includes 57ce8e1a "Add support for LTX 2.5 (#15499)"
SWARM_REF=${SWARM_REF:-f9367de5d6319d2e20edd84415c9751bf258e110}   # 2026-08-11 "LTX-2.5 stuff", on top of 82dbd7f "LTX 2.5 support (#1493)"
CUDA_CHANNEL=${CUDA_CHANNEL:-cu130}
TORCH=${TORCH:-2.11.0} TORCHVISION=${TORCHVISION:-0.26.0} TORCHAUDIO=${TORCHAUDIO:-2.11.0}

CERB=cerberus-ai
CERB_URL=http://127.0.0.1:8188
GAME=jon@100.107.235.105
# NOT loopback: compose publishes the container port on the tailnet address only
# (ports: "100.107.235.105:8188:8188"), so nothing listens on 127.0.0.1 there.
GAME_URL=http://100.107.235.105:8188
REPO_DIR=$(cd "$(dirname "$0")" && pwd)

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# A backend with work in flight must not be restarted underneath it.
require_idle() {
  local host=$1 url=$2
  local n
  n=$(ssh -n "$host" "curl -s --max-time 8 '$url/queue'" | python3 -c \
      'import json,sys; d=json.load(sys.stdin); print(len(d["queue_running"])+len(d["queue_pending"]))')
  [ "$n" = 0 ] || { echo "REFUSING: $host has $n job(s) queued/running. Drain first." >&2; exit 1; }
}

# Poll until ComfyUI answers, rather than sleeping a guessed number of seconds.
wait_up() {
  local host=$1 url=$2 i
  for i in $(seq 1 90); do
    ssh -n "$host" "curl -sf --max-time 3 '$url/system_stats' >/dev/null 2>&1" && return 0
    sleep 2
  done
  echo "TIMEOUT: $url never came up" >&2; return 1
}

# The check that actually matters. Everything else is plumbing.
verify_comfy() {
  local host=$1 url=$2 label=$3
  say "verify $label"
  ssh -n "$host" "curl -s --max-time 10 '$url/system_stats'" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("  comfyui", d["system"]["comfyui_version"])
for dev in d["devices"]:
    print("  gpu    ", dev["name"], round(dev["vram_total"]/2**30,1), "GiB")
'
  # LTX-2.5-only nodes: absent on any build older than 57ce8e1a.
  ssh -n "$host" "curl -s --max-time 15 '$url/object_info'" | python3 -c '
import json,sys
d=json.load(sys.stdin)
need=["LTXVDurationPredictor","LTXVDualCFGGuider","LTXVModalityGuidance","LTXVSpatioTemporalGuidance"]
missing=[n for n in need if n not in d]
print("  LTX-2.5 nodes:", "all present" if not missing else "MISSING "+",".join(missing))
sys.exit(1 if missing else 0)
'
}

# Read it from the log rather than inferring it from the torch version: the
# whole reason for this change is a decision ComfyUI makes at import time.
verify_kitchen() {
  local logcmd=$1
  say "verify comfy-kitchen CUDA backend"
  eval "$logcmd" | python3 -c '
import re,sys
txt=sys.stdin.read()
# LAST match, not the first: the log window spans the pre-restart start too, and
# reading that one reports the state we just changed away from.
ms=re.findall(r"comfy_kitchen backend cuda: (\{.*?\})", txt)
if not ms:
    print("  no kitchen cuda line in log -- inconclusive"); sys.exit(1)
line=ms[-1]
disabled="\x27disabled\x27: True" in line
print("  cuda backend:", "DISABLED (still on eager -- cu130 did not take)" if disabled else "ENABLED")
sys.exit(1 if disabled else 0)
'
}

update_cerberus() {
  say "cerberus: preflight"
  require_idle "$CERB" "$CERB_URL"

  say "cerberus: ComfyUI -> $COMFY_REF"
  ssh -n "$CERB" "set -eu
    cd ~/ComfyUI
    [ -z \"\$(git status --porcelain)\" ] || { echo 'REFUSING: ~/ComfyUI has local changes'; exit 1; }
    git fetch -q origin
    git merge --ff-only $COMFY_REF
    git rev-parse --short HEAD"

  say "cerberus: torch $TORCH+$CUDA_CHANNEL"
  # The +$CUDA_CHANNEL suffix is load-bearing on an EXISTING venv. A local
  # version is not part of version matching, so `torch==2.11.0` is considered
  # already satisfied by the installed 2.11.0+cu128 and pip does nothing at all,
  # silently. It exits 0 and leaves you on cu128. (The Dockerfile can get away
  # with the bare version because it builds a fresh venv where the cu130 index
  # is the only source.)
  # Drop the cu12 runtime packages BEFORE installing cu130, not after. They are
  # dead weight once torch is cu13, but they are not merely inert: cu12 uses the
  # old nvidia/<pkg>/lib layout and cu13 uses nvidia/cu13/lib, and nvrtc then
  # resolves libnvrtc-builtins against the wrong one -- every JIT-compiled kernel
  # dies with "failed to open libnvrtc-builtins.so.13.0". That is what took out
  # LTXVAudioVAEEncode (the audio VAE's STFT does a complex abs()).
  # Order matters: several cu12 and cu13 packages ship the SAME soname at the
  # same path (both cudnn wheels are 9.19.0.56), so uninstalling cu12 AFTER the
  # cu13 install deletes a file cu13 still needs and leaves torch unimportable.
  # Uninstall first, then let the cu130 install lay down a complete set.
  ssh -n "$CERB" "set -eu
    V=~/ComfyUI/venv
    STALE=\$(\$V/bin/pip list 2>/dev/null | grep -oE '^nvidia-[a-z0-9-]*-cu12' | tr '\n' ' ')
    [ -z \"\$STALE\" ] || { echo \"  dropping stale cu12 runtime: \$STALE\"; \$V/bin/pip uninstall -y -q \$STALE; }"
  ssh -n "$CERB" "~/ComfyUI/venv/bin/pip install -q \
      'torch==$TORCH+$CUDA_CHANNEL' 'torchvision==$TORCHVISION+$CUDA_CHANNEL' 'torchaudio==$TORCHAUDIO+$CUDA_CHANNEL' \
      --index-url https://download.pytorch.org/whl/$CUDA_CHANNEL
    ~/ComfyUI/venv/bin/pip install -q -r ~/ComfyUI/requirements.txt
    ~/ComfyUI/venv/bin/python -c 'import torch;print(\"  torch\",torch.__version__,\"cuda\",torch.version.cuda)'
    # A JIT-compiled kernel, because a broken nvrtc is invisible until the first
    # render and then only in one node. complex abs() is the exact op the audio
    # VAE's STFT hits, and the exact one that failed on a mixed cu12/cu13 tree.
    ~/ComfyUI/venv/bin/python -c \"
import torch
x = torch.randn(8, device='cuda', dtype=torch.complex64)
torch.abs(x).sum().item()
print('  nvrtc JIT ok')\""

  say "cerberus: restart ComfyUI"
  ssh -n "$CERB" "systemctl --user restart comfyui"
  wait_up "$CERB" "$CERB_URL"
  verify_comfy "$CERB" "$CERB_URL" "cerberus ComfyUI"
  verify_kitchen "ssh -n $CERB 'journalctl --user -u comfyui --since \"5 min ago\" --no-pager'"

  say "cerberus: SwarmUI -> $SWARM_REF"
  # SwarmUI is a compiled .NET app; a git pull alone changes nothing until it is
  # rebuilt. launchtools/linux-build-logic.sh is where that contract lives.
  ssh -n "$CERB" "set -eu
    cd ~/SwarmUI
    git fetch -q origin
    git merge --ff-only $SWARM_REF
    systemctl --user stop swarmui
    export DOTNET_ROOT=\$HOME/.dotnet PATH=\$HOME/.dotnet:\$PATH
    dotnet build src/SwarmUI.csproj --configuration Release -o ./src/bin/live_release
    git rev-parse HEAD > src/bin/last_build
    systemctl --user start swarmui"
  say "cerberus: verify SwarmUI + its backends"
  verify_swarm
}

# Parsed locally: nesting python inside ssh inside bash quoting is how the
# escaping goes wrong. Remote does curl only.
verify_swarm() {
  local i sid
  for i in $(seq 1 60); do
    ssh -n "$CERB" "curl -sf --max-time 3 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:7801/API/GetNewSession" >/dev/null 2>&1 && break
    sleep 2
  done
  sid=$(ssh -n "$CERB" "curl -s -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:7801/API/GetNewSession" \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["version"], d["session_id"])')
  echo "  swarm ${sid%% *}"
  ssh -n "$CERB" "curl -s -X POST -H 'Content-Type: application/json' -d '{\"session_id\":\"${sid##* }\"}' http://127.0.0.1:7801/API/ListBackends" \
    | python3 -c '
import json,sys
d=json.load(sys.stdin)
rows=[v for v in d.values() if isinstance(v,dict) and "status" in v]
for v in rows:
    print("  backend:", v.get("title"), "->", v.get("status"))
sys.exit(0 if rows and all(v.get("status")in("running","idle") for v in rows) else 1)
'
}

update_gamingpc() {
  say "gamingpc: preflight"
  require_idle "$GAME" "$GAME_URL"

  say "gamingpc: push pinned Dockerfile"
  rsync -a "$REPO_DIR/comfy-backend/Dockerfile" "$GAME:/home/jon/comfy-backend/Dockerfile"

  say "gamingpc: rebuild image (COMFY_REF=$COMFY_REF, $CUDA_CHANNEL)"
  # --pull is deliberately NOT passed: the base image tag is part of the pin.
  ssh -n "$GAME" "cd /home/jon/comfy-backend && docker compose build \
      --build-arg COMFY_REF=$COMFY_REF --build-arg SWARM_REF=$SWARM_REF \
      --build-arg CUDA_CHANNEL=$CUDA_CHANNEL \
      --build-arg TORCH=$TORCH --build-arg TORCHVISION=$TORCHVISION --build-arg TORCHAUDIO=$TORCHAUDIO"

  say "gamingpc: restart container"
  ssh -n "$GAME" "cd /home/jon/comfy-backend && docker compose up -d"
  wait_up "$GAME" "$GAME_URL"
  verify_comfy "$GAME" "$GAME_URL" "gamingpc ComfyUI"
  verify_kitchen "ssh -n $GAME 'docker logs comfyui 2>&1 | tail -200'"
}

case "${1:-all}" in
  cerberus) update_cerberus ;;
  gamingpc) update_gamingpc ;;
  all)      update_cerberus; update_gamingpc ;;
  *) echo "usage: $0 [cerberus|gamingpc|all]" >&2; exit 2 ;;
esac

say "done"
