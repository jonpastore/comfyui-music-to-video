# peaches-unraid as an image and music backend — research

> **PENDING APPROVAL. Nothing here is built.** Everything below was measured on
> the box, not recalled. Where a claim is architectural rather than measured it
> says so and names the spike that would settle it.

Short answers to the two questions asked:

- **Can the containers work with Unraid and persist?** Yes, and the prerequisite
  that usually blocks this is already done. But "persist" has a specific meaning
  here that a plain `docker run` does not satisfy — see §2.
- **Is the 2080 Ti good for text/image/music?** For **image and music, yes**. For
  video, no, and not because of its 11 GB — because of its *generation*. See §3.

---

## 1 · The box, as measured

| | |
|---|---|
| Unraid | 7.3.0, kernel 6.18.29-Unraid |
| GPU | **RTX 2080 Ti, 11264 MiB, driver 610.43.02, compute capability 7.5** |
| GPU UUID | `GPU-aadea5cb-ad26-e1ee-d8e6-aa73c825dba9` |
| Docker | 29.4.3, btrfs storage driver |
| **nvidia runtime** | **already registered** — `Runtimes: runc io.containerd.runc.v2 nvidia` |
| Tailscale | `100.95.184.29` |
| RAM | 31 GB total, 24 GB available |
| Cache pool | **922 GB NVMe, 837 GB free** |
| Array | 11 TB, 8.7 TB free |

**The Nvidia-Driver plugin is installed and its runtime is registered with
Docker.** That is normally the first and most annoying step on Unraid, and it is
done. A container gets the card with `--runtime=nvidia` and
`NVIDIA_VISIBLE_DEVICES=<the UUID above>` — Unraid's own convention is the UUID
rather than `all`, so that a second GPU added later does not silently join.

---

## 2 · Persistence on Unraid, which is not what it looks like

    /            rootfs   16G   <- RAM. Does NOT survive a reboot.
    /boot        flash    31G   <- USB stick. Config lives here.
    /mnt/cache   NVMe    922G   <- fast, persists
    /mnt/user    shfs     11T   <- array, persists

`DOCKER_IMAGE_FILE="/mnt/user/system/docker/docker.img"` and
`DOCKER_APP_CONFIG_PATH="/mnt/user/appdata/"`, so **images and containers do
persist** — they live in a btrfs image on the array, not in the RAM root.

The trap is narrower than "will it survive a reboot":

- **A container created by `docker run` or `docker compose` survives, but Unraid
  does not know about it.** It will not appear on the Docker tab, it will not be
  covered by Unraid's autostart ordering, and its image is a candidate for the
  "orphan image" cleanup because no template references it.
- **Anything written outside `/boot` and `/mnt` is gone on reboot.** A
  Dockerfile built in `/root` is gone. Compose files in `/root` are gone.

So the Unraid-native shape, which is what "persist" should mean here:

1. **A template** at
   `/boot/config/plugins/dockerMan/templates-user/my-comfyui.xml`. That is what
   makes it a first-class managed container: visible in the UI, autostarted,
   editable, and safe from orphan cleanup. The schema is plain XML — `<Name>`,
   `<Repository>`, `<Network>`, `<ExtraParams>`, and one `<Config>` element per
   port, path and variable. `my-immich.xml` on this box is a working example to
   copy the shape from.
2. **Everything mutable under `/mnt/user/appdata/comfyui/`** — the Unraid
   convention, and it is on the cache pool.
3. **Models on the cache pool, not the array.** 837 GB free NVMe against 8.7 TB
   of spinning array: a 7 GB checkpoint loaded off the array will be slow every
   time the model is swapped, and swapping is exactly what an 11 GB card does.

**Do not build the image on the box.** `/root` is RAM. Either build from a
Dockerfile kept in `/mnt/user/appdata/comfyui/build/`, or — better — use a
published image so the template has a `<Repository>` that survives without a
local build at all.

---

## 3 · What the 2080 Ti can actually run, and the constraint that decides it

**Compute capability 7.5 is Turing.** That is the whole answer, and it is not
about the 11 GB:

- **No fp8.** fp8 tensor cores arrive with Ada (sm_89). Every fp8 model in this
  studio is therefore out: `ltx-2.3-22b-distilled_transformer_only_fp8_scaled`,
  `wan2.2_*_fp8_scaled`, `qwen_image_edit_2511_fp8mixed`, and
  `Z-Image-Turbo-FP8Mix`.
- **No native bf16.** bf16 arrives with Ampere (sm_80). fp16 is fine and fast —
  Turing has fp16 tensor cores — but a bf16 checkpoint will either be converted
  or run slowly.

This is architectural rather than measured, and it is the one thing worth
spiking before committing: run `torch.cuda.get_device_capability()` and attempt
one fp8 load inside the container. Ten minutes, and it turns this section from
reasoning into evidence.

What that leaves, against models this project already uses:

| Model | Size | On a 2080 Ti |
|---|---|---|
| `ace_step_v1_3.5b` | 7.2 GB | **yes** — 3.5B at fp16 is ~7 GB, fits 11 GB |
| `sd_xl_base_1.0` | 6.5 GB | **yes**, comfortably |
| SD 1.5, upscalers, ControlNet, face restore | small | **yes**, easily |
| `Z-Image-Turbo-FP8Mix` | 6.1 GB | **no** — fp8 |
| `ltx-2.3-22b-distilled` (fp8) | 21.9 GB | **no**, twice over |
| `wan2.2_s2v_14B` (fp8) | 15.3 GB | **no**, twice over |

**So this is an image and music box.** That is exactly what was asked for, and it
is a genuinely good fit: ACE-Step audio is the single most useful thing to move
off the 5090s, because it is the one job that competes with video rendering for
the card and does not need the card's speed.

---

## 4 · SwarmUI here: don't

The request was for SwarmUI *and* ComfyUI. The recommendation is **ComfyUI only,
joined to the existing swarm**, for the same reason given on every other box:
one SwarmUI on cerberus drives all backends. A second install is a second
first-run wizard pointed at another disk — which has already cost this project a
broken self-start backend and 7.3 GB of orphaned download on cerberus when
someone clicked through it in a browser.

If a local UI on this box is genuinely wanted — for someone who should not see
the whole swarm — it is possible, but it should be a deliberate second instance
with its own `--lock_settings`, not the default.

**What this box needs to join the swarm is only:** ComfyUI reachable on the
tailnet, the two Swarm node packs, and one `AddNewBackend` + `EditBackend` pair
run on cerberus.

---

## 5 · The dependency that bit gamingpc, and will bite here

A clean ComfyUI does **not** install what the Swarm node packs import. Verified
on gamingpc: the packs need `cv2`, `imageio_ffmpeg` and `OpenGL_accelerate`, and
declare `dill`, `rembg`, `ultralytics`. Without them the backend registers and
runs **degraded** — cerberus only works because other custom node packs happened
to drag opencv in.

Any image used here must install:

    opencv-python-headless imageio-ffmpeg PyOpenGL-accelerate dill rembg ultralytics

and the check afterwards is that `/object_info` reports ~59 `Swarm*` node types.
**Count them by parsing the JSON, not with `grep -c`** — recent ComfyUI returns
`/object_info` as a single line, so `grep -c` reports `1` for a perfectly healthy
backend. That mistake is already in two documents in this repo and is being
corrected.

---

## 6 · Proposed shape

    /mnt/user/appdata/comfyui/          <- cache pool, persists, Unraid convention
        models/                          <- checkpoints here, NOT on the array
        input/  output/  custom_nodes/
        build/Dockerfile                 <- if building locally rather than pulling

    /boot/config/plugins/dockerMan/templates-user/my-comfyui.xml

Container: `--runtime=nvidia`,
`NVIDIA_VISIBLE_DEVICES=GPU-aadea5cb-ad26-e1ee-d8e6-aa73c825dba9`, published on
`100.95.184.29:8188` only — ComfyUI has no authentication and this is a file
server on a home LAN, so a `0.0.0.0` bind is materially worse here than
elsewhere.

Phases, each independently useful:

1. **Spike the fp8/bf16 question** (10 min). Decides §3 from evidence.
2. **ComfyUI container + template**, GPU verified, `/object_info` answering with
   the full Swarm node set.
3. **Sync ACE-Step and SDXL** to the cache pool — ~14 GB, the two models this
   card can actually run.
4. **Register on cerberus** — needs the `--lock_settings` unlock/relock dance.
5. Only then, if wanted: move audio generation here permanently, which is the
   real prize. It takes the one workload that competes with video off the 5090s.

---

## 7 · Open questions

1. **Does an fp8 checkpoint fail loudly or silently degrade?** ComfyUI may
   fall back to a slower path rather than refusing. If it degrades silently,
   this box will accept LTX jobs from the swarm and take forever — which is
   worse than refusing, given SwarmUI does not requeue a job lost mid-generation.
2. **Should the swarm be told what this backend cannot do?** SwarmUI routes to
   whichever backend is free, not whichever is capable. With a 2080 Ti in the
   pool, a video job can land on it. Whether SwarmUI can express "this backend
   only does these models" needs checking before joining, or the fast boxes get
   starved by jobs queued behind a card that cannot do them.
3. **Array or cache for the models?** Cache, on speed grounds — but 837 GB is
   shared with everything else Unraid caches, and Unraid's mover may relocate
   files written to a share with a cache-then-array policy. The appdata share's
   policy needs checking rather than assuming.
