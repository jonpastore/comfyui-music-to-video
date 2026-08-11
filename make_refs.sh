#!/bin/bash
# Storyboard -> approved-able reference images, one per clip, both cuts.
# Builds the workflows locally, ships them to cerberus, submits them in order,
# pulls the PNGs back into the song folder and makes a contact sheet to review.
#
# usage: ./make_refs.sh "Street Cats/Rear Entrance" rear_entrance [clean|explicit]
set -eu
DIR=${1:?"song folder, e.g. Street Cats/Rear Entrance"}
SLUG=${2:?"slug, e.g. rear_entrance"}
ONLY=${3:-both}
cd "$(dirname "$0")"

MP3=$(ls "$DIR"/*.mp3 | head -1)
R=cerberus-ai

for V in clean explicit; do
  [ "$ONLY" = both ] || [ "$ONLY" = "$V" ] || continue
  SB="$DIR/${SLUG}_${V}.json"
  [ -f "$SB" ] || { echo "no storyboard: $SB"; exit 1; }

  python3 build_refs.py --storyboard "$SB" --version "$V" --slug "$SLUG" \
    --anchor "meow_p_anchor_${V}.png" --audio "$MP3" \
    --outdir "/tmp/wf_${SLUG}_${V}"

  # stale refs must go first: sync_from_cerberus.sh uses --ignore-existing, so
  # an old local PNG of the same name silently survives a regeneration.
  rm -f "$DIR/$V"/clip_*.png
  ssh $R "rm -rf ~/wf_${SLUG}_${V} ~/ComfyUI/output/refs_${SLUG}_${V}"
  rsync -a "/tmp/wf_${SLUG}_${V}/" "$R:~/wf_${SLUG}_${V}/"
  rsync -a "meow_p_anchor_${V}.png" "$R:~/ComfyUI/input/"

  echo "== $V: $(ls /tmp/wf_${SLUG}_${V} | wc -l) images, ~15s each"
  ssh $R "~/bin/submit_all.sh ~/wf_${SLUG}_${V}"

  mkdir -p "$DIR/$V"
  rsync -a "$R:~/ComfyUI/output/refs_${SLUG}_${V}/" "$DIR/$V/"
  python3 make_contact_sheet.py "$DIR/$V" "$DIR/${SLUG}_${V}_contact_sheet.jpg" 2>/dev/null \
    || echo "(contact sheet skipped)"
done

echo "review: $DIR/${SLUG}_*_contact_sheet.jpg"
echo "reroll bad clips: python3 reroll_refs.py --storyboard \"$DIR/${SLUG}_clean.json\" \\"
echo "   --version clean --slug $SLUG --audio \"$MP3\" \\"
echo "   --anchor meow_p_anchor_clean.png --clips 4,17,37 --outdir reroll/${SLUG}_clean"
