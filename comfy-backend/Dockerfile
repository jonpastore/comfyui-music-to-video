# ComfyUI as a SwarmUI BACKEND. No SwarmUI here on purpose: one SwarmUI runs on
# cerberus and drives every box. This image is the engine, not an interface.
#
# Its own python+torch is the point -- the host is Ubuntu 26.04 with python 3.14
# and no pip, which torch has no wheels for.
#
# CANONICAL COPY lives in this repo; update_ltx25.sh rsyncs it to gamingpc. It
# used to exist only on that box, which meant the build was unreproducible in
# the strong sense: nobody could rebuild it without the box.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

# Everything version-bearing is an ARG so a rebuild is reproducible. The old
# Dockerfile pinned NOTHING -- `git clone --depth 1` plus a bare `pip install
# torch` meant any rebuild silently moved both ComfyUI and torch, and the image
# you got back was not the image you had.
ARG COMFY_REF=26d7f8556822d9d08c2d3e1878636ac3b4969af9
ARG SWARM_REF=f9367de5d6319d2e20edd84415c9751bf258e110
# cu130, not cu128: comfy/quant_ops.py does `ck.registry.disable("cuda")` when
# torch.version.cuda < 13, which silently drops LTX-2.5's int8-convrot and nvfp4
# matmuls onto the eager backend. Verified in this container's own startup log:
#   cuda: {'available': True, 'disabled': True}
# Same torch/vision/audio versions as the cu128 build had -- only the CUDA
# build changes, so this is a one-variable move.
ARG CUDA_CHANNEL=cu130
ARG TORCH=2.11.0
ARG TORCHVISION=0.26.0
ARG TORCHAUDIO=2.11.0

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip git ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# This is a Blackwell card (sm_120); earlier CUDA builds have no kernels for it.
RUN pip install --upgrade pip && \
    pip install "torch==${TORCH}" "torchvision==${TORCHVISION}" "torchaudio==${TORCHAUDIO}" \
        --index-url "https://download.pytorch.org/whl/${CUDA_CHANNEL}"

# Fetch exactly one commit rather than `clone --depth 1` of whatever master is
# today -- same bandwidth, but the ref is now an input instead of a surprise.
RUN git init /opt/ComfyUI && cd /opt/ComfyUI && \
    git remote add origin https://github.com/comfyanonymous/ComfyUI.git && \
    git fetch --depth 1 origin "${COMFY_REF}" && \
    git checkout FETCH_HEAD && \
    pip install -r requirements.txt

# The Swarm packs import cv2, imageio_ffmpeg and OpenGL_accelerate, and declare
# dill/rembg/ultralytics -- none of which ComfyUI's own requirements.txt pulls
# in. A clean ComfyUI therefore loads ONE Swarm node instead of 59 and the
# backend registers "degraded" without saying why; cerberus only works because
# other custom node packs happened to install cv2 for it. headless opencv on
# purpose: there is no display in a container.
RUN pip install opencv-python-headless imageio-ffmpeg PyOpenGL-accelerate dill rembg ultralytics

# The two packs SwarmUI needs in EVERY ComfyUI it drives. Without them a backend
# registers but runs degraded -- 10 features instead of the 14 cerberus reports.
RUN git init /opt/SwarmUI && cd /opt/SwarmUI && \
    git remote add origin https://github.com/mcmonkeyprojects/SwarmUI.git && \
    git fetch --depth 1 origin "${SWARM_REF}" && \
    git checkout FETCH_HEAD && \
    ln -s /opt/SwarmUI/src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/SwarmComfyCommon \
          /opt/ComfyUI/custom_nodes/SwarmComfyCommon && \
    ln -s /opt/SwarmUI/src/BuiltinExtensions/ComfyUIBackend/ExtraNodes/SwarmComfyExtra \
          /opt/ComfyUI/custom_nodes/SwarmComfyExtra

WORKDIR /opt/ComfyUI
EXPOSE 8188
# 0.0.0.0 inside the container; the port is published to the tailnet address
# only (see compose.yaml), so this is not open to the LAN.
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"]
