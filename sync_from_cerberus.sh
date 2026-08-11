#!/bin/bash
# Pull generated reference images and rendered clips off cerberus into the
# album folder tree, every 60s. Safe to run continuously; --ignore-existing
# means finished files are copied once and never re-fetched.
# usage: ./sync_from_cerberus.sh <slug> "<Album>/<Song Folder>"
set -u
SLUG=${1:?slug e.g. rear_entrance}
DEST=${2:?"e.g. Street Cats/Rear Entrance"}
cd "$(dirname "$0")"
R=cerberus-ai:'~/ComfyUI/output'

for v in clean explicit; do
  mkdir -p "$DEST/$v/clips"
done

while true; do
  for v in clean explicit; do
    # reference images (one per scene)
    rsync -a --ignore-existing "$R/refs_${SLUG}_${v}/" "$DEST/$v/" 2>/dev/null
    # rendered clips
    rsync -a --ignore-existing "$R/${SLUG}_${v}/" "$DEST/$v/clips/" 2>/dev/null
  done
  sleep 60
done
