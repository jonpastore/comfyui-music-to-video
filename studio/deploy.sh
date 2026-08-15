#!/bin/bash
# Deploy Meow P Studio to cerberus-ai and (re)start it under systemd --user.
#
# The app runs on the same box as ComfyUI so it can read and write
# ~/ComfyUI/{input,output} directly -- no file shuttling between machines.
# It gets its OWN venv: ComfyUI's venv is left exactly as it is.
#
# usage: ./deploy.sh [--no-restart]
set -euo pipefail
cd "$(dirname "$0")"
REPO=".."
R=cerberus-ai
DEST='~/meowp-studio'

echo "== syncing app"
ssh $R "mkdir -p $DEST/scripts $DEST/data"
rsync -a --delete \
  --exclude data/ --exclude __pycache__/ --exclude '*.pyc' \
  ./ "$R:$DEST/app/"

# The real database is $DEST/data/studio.db, set by STUDIO_DATA in the unit.
# Running the app by hand from the app directory WITHOUT that variable creates a
# second, empty one at $DEST/app/data/studio.db -- and the --exclude above meant
# it then survived every deploy. One sat there from Aug 10 with 0 songs and no
# anchors table, as a decoy for "where did all my rows go".
ssh $R "rm -rf $DEST/app/data"

# The pipeline scripts live at the repo root and are imported by each other
# (build_refs imports build_song), so they ship as a set into one directory.
echo "== syncing pipeline scripts"
rsync -a "$REPO"/build_refs.py "$REPO"/build_song.py "$REPO"/build_storyboard.py \
         "$REPO"/make_anchor.py "$REPO"/reroll_refs.py "$REPO"/make_contact_sheet.py \
         "$REPO"/guardrail.py "$REPO"/fix_ref.py "$REPO"/make_audio.py \
         "$R:$DEST/scripts/"
rsync -a "$REPO"/profiles/ "$R:$DEST/scripts/profiles/" 2>/dev/null || true

# The few-shot storyboard exemplar grok.py teaches from. Without it grok falls
# back to a bland inline placeholder and storyboard quality quietly drops, so
# ship it and fail loudly if it is missing rather than degrading in silence.
EX_DIR="Street Cats/Rear Entrance"
if [ -f "$REPO/$EX_DIR/rear_entrance_explicit.json" ]; then
  # $HOME, not the literal ~: quoting the tilde to protect the spaces in
  # "Street Cats/Rear Entrance" would create a directory actually named "~".
  ssh $R "mkdir -p \"\$HOME/meowp-studio/scripts/$EX_DIR\""
  rsync -a "$REPO/$EX_DIR/rear_entrance_explicit.json" \
           "$REPO/$EX_DIR/rear_entrance_explicit.md" "$R:$DEST/scripts/$EX_DIR/"
else
  echo "  ERROR: storyboard exemplar missing; grok now FAILS rather than degrading."; exit 1
fi

echo "== venv"
# Built with an EXPLICIT interpreter, never bare `python3`: the render box's
# default python3 is 3.10 while 3.12 sits beside it, and librosa needs 3.12 to
# reach its current release. A bare `python3 -m venv` silently produced a 3.10
# venv that could not install requirements.txt at all.
#
# `test -d` alone would keep a stale interpreter forever, so the version is
# checked and the venv rebuilt when it is too old. Rebuilding happens IN PLACE:
# a venv is NOT relocatable -- every script in bin/ carries a shebang with the
# venv's absolute path, so building elsewhere and renaming produces a venv whose
# uvicorn points at a directory that no longer exists, and the service will not
# start. Cost of learning that: about 90 seconds of downtime.
PY=python3.12
ssh $R "set -e
        command -v $PY >/dev/null || { echo '  ERROR: $PY is not on the render box'; exit 1; }
        if [ -x $DEST/venv/bin/python ] && \
           ! $DEST/venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,12) else 1)'; then
          echo '  existing venv predates 3.12 -- rebuilding it in place'
          systemctl --user stop meowp-studio 2>/dev/null || true
          rm -rf $DEST/venv
        fi
        test -d $DEST/venv || $PY -m venv $DEST/venv
        $DEST/venv/bin/pip -q install --upgrade pip
        $DEST/venv/bin/pip -q install -r $DEST/app/requirements.txt"

# The bind address, decided BEFORE the unit is written because the unit needs
# it. Tailnet-only by default: this app has no authentication of any kind and
# 0.0.0.0 put it on the LAN and on every docker bridge as well.
# STUDIO_HOST=0.0.0.0 in the environment opts back out.
IP=$(ssh $R 'tailscale ip -4 2>/dev/null | head -1')
BIND="${STUDIO_HOST:-$IP}"
if [ -z "$BIND" ]; then
  echo "  WARNING: no tailscale IP on $R, binding 0.0.0.0 -- LAN and docker bridges too"
  BIND=0.0.0.0
fi

echo "== systemd unit"
ssh $R "mkdir -p ~/.config/systemd/user && cat > ~/.config/systemd/user/meowp-studio.service <<'UNIT'
[Unit]
Description=Meow P Studio
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/meowp-studio/app
Environment=STUDIO_SCRIPTS=%h/meowp-studio/scripts
Environment=STUDIO_DATA=%h/meowp-studio/data
Environment=COMFY_URL=http://127.0.0.1:8188
# Vision: pin qwen3-vl so a 503 on GET /models cannot hide a running
# llama-server on amd-halo :8006 (measured 2026-08-14).
Environment=LITELLM_BASE=http://127.0.0.1:4000/v1
Environment=STUDIO_VISION_MODEL=qwen3-vl
# PIN the text model, do not auto-detect it here. The gateway fronts several
# machines and auto-detection cannot see which of them shares a GPU with the
# renderer -- it used to pick qwen3.6-coder, which was ollama on THIS box behind
# a card ComfyUI already fills, and it answered nothing in 90 s.
#
# qwen3.6 is Qwen3.6-35B-A3B on amd-halo :8007 with thinking OFF. Thinking
# matters here: with it on the model spent 193 completion tokens and 4.0 s to
# answer "say ok"; off, 2 tokens and 133 ms. Every studio caller wants short
# structured output, not an essay about it.
Environment=STUDIO_TEXT_MODEL=qwen3.6
Environment=COMFY_INPUT=%h/ComfyUI/input
Environment=COMFY_OUTPUT=%h/ComfyUI/output
# comfy (this box only) or swarm (SwarmUI picks a backend). The switch is one
# word here, and flipping it is a decision someone makes rather than something a
# deploy does -- SWITCHED TO SWARM 2026-08-12 by Jon, after phases 0-4 landed
# and the fleet was verified: three backends registered, inputs staged to both
# remote boxes, and the retry walking exactbackendid over the running backends.
# Put it back to comfy to render on this box alone; nothing else has to change.
Environment=RENDER_BACKEND=swarm
# Where each OTHER backend keeps its ComfyUI input dir. SwarmUI has no upload
# API -- UploadImage is not registered and answers HTTP 400 -- so a reference
# image reaching another box is a filesystem problem. Every box that could be
# handed the job needs the file, because Swarm picks the backend and the studio
# does not get to know which.
#
# Both paths were found the hard way and neither is guessable:
#   gamingpc  ComfyUI runs out of ~/comfy-backend, NOT ~/ComfyUI.
#   peaches   ComfyUI runs out of /comfy/mnt/ComfyUI inside the container, so
#             the /basedir mount (which holds the models) is the WRONG target;
#             the host path below is the one that appears as its input dir.
# Verified 2026-08-12 by staging a real ref and having each box LoadImage it.
Environment=SWARM_INPUT_DIRS=jon@100.107.235.105:/home/jon/comfy-backend/input,root@100.95.184.29:/mnt/user/appdata/comfyui-swarm/mnt/ComfyUI/input
# Album profile: character, wardrobe, world, locations. The scripts carry no
# album content, so point this at a different profile for a different project.
Environment=STUDIO_PROFILE=%h/meowp-studio/scripts/profiles/street_cats.json
# STUDIO_HOST is the BIND, and ExecStart below reads it. It used to be set here
# and ignored: ExecStart hardcoded --host 0.0.0.0, so the deploy banner offered
# "set STUDIO_HOST to the tailscale IP for tailnet-only" -- advice that would
# have changed nothing while the banner then reported the isolation as done.
Environment=STUDIO_HOST=$BIND
Environment=STUDIO_PORT=8000
# XAI_API_KEY is read from ~/.config/morpheus/grok-mcp.env by studio/grok.py.
# It is deliberately NOT baked into this unit file.
ExecStart=%h/meowp-studio/venv/bin/uvicorn app:app --host $BIND --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload"

if [ "${1:-}" != "--no-restart" ]; then
  echo "== restart"
  # enable --now is NOT enough: on an already-running service it is a no-op and
  # the freshly rsynced code never gets loaded. restart is what actually applies
  # a deploy.
  ssh $R "systemctl --user enable meowp-studio.service; \
          systemctl --user restart meowp-studio.service; sleep 3; \
          systemctl --user --no-pager -l status meowp-studio.service | head -20"
fi

# Smoke test: a green systemd status only proves uvicorn started, not that the
# app imports its modules and renders. Hit the real pages and fail loudly.
# Against $BIND, not 127.0.0.1: uvicorn --host takes ONE address, so a
# tailnet-only bind does not answer on loopback and a loopback smoke test would
# report the whole app down.
echo "== smoke test"
FAIL=0
for P in / /playlists /tiers /jobs /models /anchors; do
  CODE=$(ssh $R "curl -s -o /dev/null -w '%{http_code}' -m 15 http://$BIND:8000$P" || echo 000)
  printf "  %-12s %s\n" "$P" "$CODE"
  [ "$CODE" = "200" ] || FAIL=1
done
# ComfyUI must be reachable from the app or every render job fails at submit time
CODE=$(ssh $R "curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8188/system_stats" || echo 000)
printf "  %-12s %s%s\n" "comfyui" "$CODE" "$([ "$CODE" = 200 ] || echo '  <- ComfyUI is down; renders will fail')"
[ "$CODE" = "200" ] || FAIL=1
# The API key is read at call time, not import time, so check it separately
ssh $R 'test -s ~/.config/morpheus/grok-mcp.env && grep -q "^XAI_API_KEY=." ~/.config/morpheus/grok-mcp.env' \
  && echo "  xai key      present" \
  || { echo "  xai key      MISSING -> storyboard generation will fail."; \
       echo "               fix: scp ~/.config/morpheus/grok-mcp.env $R:~/.config/morpheus/"; FAIL=1; }

echo
# Report the bind honestly -- read back from the RUNNING unit, not from the
# variable this script hoped to set, so a unit edited by hand is reported as it
# actually is.
RUNNING=$(ssh $R "systemctl --user show meowp-studio -p ExecStart --value 2>/dev/null | tr ' ' '\n' | grep -A1 -- '--host' | tail -1")
if [ "$FAIL" = 0 ]; then
  echo "studio: http://${IP:-cerberus-ai}:8000"
  if [ "${RUNNING:-0.0.0.0}" = "0.0.0.0" ]; then
    echo "        bound to 0.0.0.0 -- reachable on tailnet, LAN and docker bridges."
    echo "        for tailnet-only: deploy with tailscale up, or STUDIO_HOST=<ip> ./deploy.sh"
  else
    echo "        bound to $RUNNING -- tailnet only, not the LAN or docker bridges"
  fi
else
  echo "DEPLOYED BUT NOT HEALTHY -- see the failures above."
  echo "url:    http://${IP:-cerberus-ai}:8000"
fi
echo "logs:   ssh $R 'journalctl --user -u meowp-studio -f'"
exit $FAIL
