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

# The pipeline scripts live at the repo root and are imported by each other
# (build_refs imports build_song), so they ship as a set into one directory.
echo "== syncing pipeline scripts"
rsync -a "$REPO"/build_refs.py "$REPO"/build_song.py "$REPO"/build_storyboard.py \
         "$REPO"/make_anchor.py "$REPO"/reroll_refs.py "$REPO"/make_contact_sheet.py \
         "$REPO"/guardrail.py "$REPO"/fix_ref.py \
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
# Vision: studio/vision.py prefers a local VL model on the litellm
# gateway and only falls back to xAI when there is none. Set
# STUDIO_VISION_MODEL to pin one instead of auto-detecting.
Environment=LITELLM_BASE=http://127.0.0.1:4000/v1
# PIN the text model, do not auto-detect it here. The gateway fronts several
# machines and the first match on this one is qwen3.6-coder -- which is ollama
# on THIS box, where ComfyUI already holds ~22 GB of the 24 GB card. Ollama
# then loads that 27B model on the CPU and says nothing. Measured through the
# gateway: qwen3-coder (a different box) answered in 315 ms; qwen3.6-coder did
# not answer at all in 90 s.
Environment=STUDIO_TEXT_MODEL=qwen3-coder
Environment=COMFY_INPUT=%h/ComfyUI/input
Environment=COMFY_OUTPUT=%h/ComfyUI/output
# Album profile: character, wardrobe, world, locations. The scripts carry no
# album content, so point this at a different profile for a different project.
Environment=STUDIO_PROFILE=%h/meowp-studio/scripts/profiles/street_cats.json
Environment=STUDIO_HOST=0.0.0.0
Environment=STUDIO_PORT=8000
# XAI_API_KEY is read from ~/.config/morpheus/grok-mcp.env by studio/grok.py.
# It is deliberately NOT baked into this unit file.
ExecStart=%h/meowp-studio/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
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

IP=$(ssh $R 'tailscale ip -4 2>/dev/null | head -1')

# Smoke test: a green systemd status only proves uvicorn started, not that the
# app imports its modules and renders. Hit the real pages and fail loudly.
echo "== smoke test"
FAIL=0
for P in / /playlists /tiers /jobs /models /anchors; do
  CODE=$(ssh $R "curl -s -o /dev/null -w '%{http_code}' -m 15 http://127.0.0.1:8000$P" || echo 000)
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
# Report the bind honestly. STUDIO_HOST defaults to 0.0.0.0, which is every
# interface -- tailnet, LAN and any docker bridge -- not the tailnet alone.
# That is a fine choice on a trusted home network, but the banner should not
# claim an isolation the service is not enforcing.
BIND=$(ssh $R "systemctl --user show meowp-studio -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^STUDIO_HOST=' | cut -d= -f2")
if [ "$FAIL" = 0 ]; then
  echo "studio: http://${IP:-cerberus-ai}:8000"
  if [ "${BIND:-0.0.0.0}" = "0.0.0.0" ]; then
    echo "        bound to 0.0.0.0 -- reachable on tailnet, LAN and docker bridges."
    echo "        for tailnet-only: set STUDIO_HOST to the tailscale IP in the unit."
  else
    echo "        bound to $BIND"
  fi
else
  echo "DEPLOYED BUT NOT HEALTHY -- see the failures above."
  echo "url:    http://${IP:-cerberus-ai}:8000"
fi
echo "logs:   ssh $R 'journalctl --user -u meowp-studio -f'"
exit $FAIL
