#!/bin/bash
# Fetch the LTX-2.5 ComfyUI (int8-convrot) model set onto a render box.
# The Lightricks/LTX-2.5 repo is gated=auto: accept the LTX-2.x Community
# License once at huggingface.co/Lightricks/LTX-2.5, then export HF_TOKEN.
#
#   HF_TOKEN=hf_... ./fetch_ltx25.sh            # -> gamingpc (32 GB 5090)
#   HF_TOKEN=hf_... TARGET=cerberus-ai ROOT=~/ComfyUI ./fetch_ltx25.sh
#
# Resumable (curl -C -): re-run after an interrupt and it picks up.
set -eu
: "${HF_TOKEN:=$(cat ~/.cache/huggingface/token 2>/dev/null || true)}"
: "${HF_TOKEN:?no token: write a read token to ~/.cache/huggingface/token, or export HF_TOKEN}"
TARGET=${TARGET:-jon@100.107.235.105}
ROOT=${ROOT:-/home/jon/comfy-backend}
REPO=${REPO:-Lightricks/LTX-2.5}

# peaches-unraid is NOT a target for this, and TARGET is an env override, so say
# so here rather than trusting whoever sets it. Its GPU is an RTX 2080 Ti (11 GB,
# compute 7.5): it cannot run a 20 GiB LTX-2.5 transformer at all, so anything
# this script wrote there would be ~58 GB of weights that never load. It also
# has traps this script does not honour -- on Unraid everything outside /boot
# and /mnt lives in RAM and is gone on reboot, and models belong on the cache
# pool rather than the array. See docs/UNRAID_BACKEND_PLAN.md.
case "$TARGET" in
  *peaches*|*100.95.184.29*)
    echo "REFUSING: $TARGET is peaches-unraid (RTX 2080 Ti, 11 GB) -- it cannot run" >&2
    echo "LTX-2.5, and this script does not honour Unraid's RAM-rootfs/cache-pool" >&2
    echo "rules. See docs/UNRAID_BACKEND_PLAN.md." >&2
    exit 2 ;;
esac

# <repo path> <comfy models subdir>
FILES="
diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors diffusion_models
text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors         text_encoders
vae/ltx-2.5-video-vae-bf16.safetensors                                           vae
vae/ltx-2.5-audio-vae-bf16.safetensors                                           vae
latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors    latent_upscale_models
model_patches/ltx-2.5-duration-head-bf16.safetensors                             model_patches
"

# The 24 GB box wants this too: 17.4 GiB of weights against int8's 20.03, which
# is the difference between ~4 GB of headroom and ~2. Fetched alongside so
# backing down off int8 costs a restart, not a 17 GB download.
[ "${WITH_NVFP4:-0}" = 1 ] && FILES="$FILES
diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors             diffusion_models
"

# Stage the token in a 0600 file on the target rather than inlining it into the
# remote command line, where every other user's `ps` would see it.
printf 'header = "Authorization: Bearer %s"\n' "$HF_TOKEN" \
  | ssh "$TARGET" "umask 077 && cat > ~/.hf-curl.cfg"
trap 'ssh "$TARGET" "rm -f ~/.hf-curl.cfg"' EXIT

echo "$FILES" | while read -r src dir; do
  [ -n "${src:-}" ] || continue
  f=$(basename "$src")
  url="https://huggingface.co/$REPO/resolve/main/$src"
  # Size-match against the remote rather than trusting a resumed file: a
  # complete file also makes `curl -C -` return 416, which would look like
  # a failure. One check settles both.
  # -n is load-bearing: without it ssh eats the rest of the piped file list
  # and the loop silently runs exactly once.
  ssh -n "$TARGET" "
    set -eu
    mkdir -p '$ROOT/models/$dir'; cd '$ROOT/models/$dir'
    want=\$(curl -sIL -K ~/.hf-curl.cfg '$url' | awk 'BEGIN{IGNORECASE=1}/^content-length:/{n=\$2}END{print n+0}' | tr -d '\r')
    have=\$(stat -c %s '$f' 2>/dev/null || echo 0)
    if [ \"\$have\" = \"\$want\" ] && [ \"\$want\" != 0 ]; then echo 'have  $f'; exit 0; fi
    curl -fL -C - --retry 5 --retry-delay 10 --no-progress-meter -K ~/.hf-curl.cfg -o '$f' '$url'
    got=\$(stat -c %s '$f')
    [ \"\$got\" = \"\$want\" ] || { echo \"SIZE MISMATCH $f: \$got != \$want\" >&2; exit 1; }
    echo 'ok    $f  '\$got
  "
done

# LTXVAudioVAELoader and LTXAVTextEncoderLoader both read ckpt_name from
# models/checkpoints/ -- not models/vae/, despite the file being a VAE. Without
# this the dropdown is silently empty. Hardlink, so it costs no disk.
ssh -n "$TARGET" "ln -f '$ROOT/models/vae/ltx-2.5-audio-vae-bf16.safetensors' \
                     '$ROOT/models/checkpoints/ltx-2.5-audio-vae-bf16.safetensors'"

ssh -n "$TARGET" "ls -l $ROOT/models/*/ltx-2.5-* $ROOT/models/text_encoders/gemma4-12b-*ltx-2.5* 2>/dev/null"
