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

**SPIKED 2026-08-12, and the reasoning below it was wrong.** This section used
to say "compute capability 7.5 is Turing, that is the whole answer, and it is
not about the 11 GB" — that fp8 tensor cores arrive with Ada, so every fp8 model
in the studio was out. It asked to be spiked before being committed to. It was,
and **the constraint is the 11 GB after all.**

**fp8 RUNS on the 2080 Ti.** `z_image_turbo_fp8mix.safetensors` — an fp8 model —
rendered a real 1024x576 image on peaches through SwarmUI pinned to
`exactbackendid: 2`. Not blank: RGB std 56.2, 969830 bytes.

    cold, including the model load   60.8s
    warm, second seed                 8.6s

Against cerberus's 5090 on the same model and step count, normalised per pixel
(2048x896 in 7.67s = 239 kpx/s, against peaches' 1024x576 in 8.6s = 69 kpx/s):
**cerberus is 3.5x faster.** The backend title's "~3.3x cerberus" was close.

fp8 tensor *cores* are indeed Ada and later. What that means in practice is that
ComfyUI stores the weights at fp8 and upcasts per operation, so the box pays in
speed and not in refusal — the VRAM saving is real, the matmul acceleration is
not. That is a 3.5x tax, not a wall.

**No native bf16 stands, and it is the one that bit.** bf16 arrives with Ampere
(sm_80). This is why peaches carries `ace_step_v1_3.5b_fp16.safetensors` rather
than the bf16 build cerberus has, and why `models.ALIASES` exists.

So the real table, against models this project already uses, with sizes measured
off disk rather than quoted, against **10.58 GiB usable** (11264 MiB nominal):

| Model | Weights | On a 2080 Ti |
|---|---|---|
| `z_image_turbo_fp8mix` | 6.1 GiB | **yes — measured, 8.6s warm at 1024x576** |
| `ace_step_v1_3.5b` (fp16 build) | 7.2 GiB | **yes** — fits, and it is the always-on audio box |
| `flux-2-klein-4b-fp8` | 4 GiB | **yes** by size; unproven here |
| `sd_xl_base_1.0` | 6.5 GiB | **yes**, comfortably |
| `wan2.2_i2v_low_noise_14B` (the refiner) | 13.31 GiB | **no** — 1.26x the card |
| `wan2.2_s2v_14B` | 15.27 GiB | **no** — 1.44x the card |
| `qwen_image_edit_2511_fp8mixed` | 19.12 GiB | **no** — 1.81x the card |
| `ltx-2.5-22b-distilled` (int8) | 20.03 GiB | **no** — 1.89x the card |
| `ltx-2.3-22b-distilled` (fp8) | 21.86 GiB | **no** — 2.07x the card |
| `wan2.2_i2v` (high **and** low, both load) | 26.62 GiB | **no** — 2.52x the card |

**None of those noes is about fp8.** Every one is a weight file larger than the
card, which is why `models.fits()` compares exactly that and nothing else.

**This is now enforced in code, not in prose.** `models.weights_gib` carries
each measured size, `models._system_stats()` reads each backend's real VRAM off
its own `/system_stats`, and `models.fits()` answers per box — so
`/models/fleet` says "15.27 GiB of weights on a 10.58 GiB card" on the page
instead of someone re-deriving it here. `models.where()` sorts a box that holds
a model it cannot hold *resident* to the back rather than dropping it: streaming
is slow, and slow is a different answer from cannot.

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

1. ~~**Does an fp8 checkpoint fail loudly or silently degrade?**~~ **ANSWERED
   2026-08-12, and the fear was right.** It degrades silently. fp8 weights load
   and render on Turing — measured above, 8.6s warm — at about 3.5x the time per
   pixel, with nothing anywhere saying so. So the box will accept work it can
   technically do and be slow at it, which is exactly the failure mode this
   question predicted, and it is why the answer to question 2 mattered.
2. ~~**Should the swarm be told what this backend cannot do?**~~ **ANSWERED
   2026-08-12: it cannot be, and the studio does it instead.** SwarmUI routes to
   whichever backend is free, not whichever is capable, and it does not requeue
   a validation miss — measured the same day: an unpinned anchor was refused
   twice because Swarm picked a box without Qwen-Image-Edit. Two mechanisms now
   cover it, both in the studio:
   - `models.py` says what each box *can* run — per-backend availability,
     `ALIASES` for the same weights under a different name, `fits()` for weights
     against that card's real VRAM, and `where()` for the order to try.
   - `pipeline.py` walks `exactbackendid` over the running backends on retry
     rather than re-rolling the same dice.
   Model curation still decides where a job *can* succeed; it never decides
   where Swarm *sends* it, and that is why the pinning exists.
3. ~~**Array or cache for the models?**~~ **ANSWERED 2026-08-12.** Cache, on a
   share of their own. The policies were read rather than assumed: `appdata` is
   `shareUseCache="prefer"` (the mover pulls array→cache, so files written there
   do stay on the pool) and `system` is `"only"`. Models now live on a dedicated
   **`models`** share at `shareUseCache="only"`, `shareCachePool="cache"` —
   `only` means the mover has no array copy to make and cannot relocate them at
   all, which `prefer` does not guarantee if the pool ever fills. It is also not
   `appdata`, so an appdata-backup plugin (none installed today) would never try
   to back up a hundred gigabytes of weights. Verified: a write through
   `/mnt/user/models` lands on `/mnt/cache/models` (nvme). 837 GB free, and
   `shareExport="-"` keeps it off SMB/NFS.

   This is also why the Docker vDisk did NOT need resizing. Weights belong on a
   bind mount, not inside `docker.img` — the vDisk holds image layers, and at
   the time of writing it was 10.4 GB used of 20 GB with six images. Growing it
   to 120 GB to store models would have been solving the wrong problem, at the
   cost of recreating every container.

---

## 8 · Postmortem: the 2026-08-12 docker vDisk resize

**What was wanted:** grow the Docker vDisk from 20 GB to 120 GB, to make room
for text and music models.

**What happened:** the box became unreachable — no ssh, no ping — and came back
with a stopped array and a pending dual-parity check.

**What the evidence says.** `/boot/logs/syslog-previous` from that boot:

    07:36:55 emhttpd: shcmd (128): umount /mnt/cache
    07:36:55 emhttpd: shcmd (128): exit status: 32
    07:36:55 emhttpd: Retry unmounting disk share(s)...
    ... the same, every 5 s, ten times ...
    07:37:45 rc.6: Sending all processes the SIGTERM signal

Exit status 32 is "target is busy". `/mnt/cache` would not unmount, Unraid
retried for ~45 s, then the shutdown was forced through. That is why the array
came back unclean (`/boot/config/forcesync` present) and why `mdResyncAction`
is now `check P Q` against 11.7 TB. The lost ssh and ping were the shutdown
tearing down `eth0` — `rc.6` had already reached `ip link set eth0 down` — not
a crash and not a network fault. The shutdown itself was ORDERLY; it was the
array stop that hung.

**Why /mnt/cache was busy.** `DOCKER_IMAGE_FILE=/mnt/user/system/docker/docker.img`
— the vDisk lives on the cache pool. Stopping the ARRAY to resize it means
unmounting the pool Docker is running out of. Anything still holding the pool
(the Docker service, a container, or a shell whose cwd is under /mnt/cache)
pins it, and Unraid will not force an unmount.

### The lesson, and it is the whole point of this section

**Resizing the Docker vDisk does NOT require stopping the array.** The
supported path stops only the Docker *service*:

1. Settings → Docker → **Enable Docker: No** → Apply. The array stays started.
2. The vDisk size field and a **Delete vDisk file** control become editable
   (verified in this box's own `DockerSettings.page`, lines 181 and 192).
3. Set size, delete the old vDisk, Apply.
4. **Enable Docker: Yes.** A fresh image is created at the new size.
5. Reinstall containers from **Apps → Previous Apps** — templates live on the
   USB flash (`/boot/config/plugins/dockerMan/templates-user/`) and survive.

Changing the size alone does not grow an existing image; the vDisk has to be
recreated. That is why step 3 deletes it.

**Better still: there is no need for a fixed size at all.** Unraid 7.3 supports
`DOCKER_IMAGE_TYPE='folder'` — a directory data-root instead of a vDisk, which
grows as needed and can never hit this wall again.

**And the models do not belong inside it either way.** A vDisk holds image
layers. Model weights belong on a bind-mounted path on the cache pool, so they
are not in the thing being resized, are not lost when the vDisk is recreated,
and do not have to be sized for in advance.

### Access is safe during this — verified, not assumed

The obvious fear is losing the remote path. It does not apply here:

| | |
|---|---|
| `tailscaled` | HOST process, `/usr/local/sbin/tailscaled`, state on `/boot/config/plugins/tailscale/state` (USB flash). The Unraid **plugin**, not a container — `docker ps` matches nothing. |
| `sshd` | HOST process, listening on `100.95.184.29:22` and `192.168.1.99:22`. |

Neither is a container, so stopping the Docker service cannot take either down.
Note that a tailnet ssh login arrives via `tailscaled be-child ssh` — Tailscale
SSH, not sshd — but tailscaled is still a host process, so the conclusion holds.

### One correction, and one real risk

1. **`DOCKER_CUSTOM_NETWORKS="wlan0 "` is CORRECT — do not "fix" it.** It reads
   like an inclusion list naming a dead interface. It is the opposite: an
   EXCLUSION list. `/etc/rc.d/rc.docker:504` is

       for NETWORK in $INCLUDE; do
         if [[ ! $DOCKER_CUSTOM_NETWORKS =~ "$NETWORK " ]]; then
           # ...create the network...

   and `DockerSettings.page:135` builds the value from `implode(' ', $unset)` —
   the interfaces UN-ticked in the GUI. So the setting says "do not create a
   custom network on wlan0", which is right for a down, unused NIC. `eth0` is
   absent from the list precisely because its macvlan SHOULD be created, and
   that is the network `pihole-v6-unbound` runs on at 192.168.1.24. Editing this
   to "include eth0" would either build a macvlan on a dead WiFi interface or
   remove the network pihole depends on.

2. **The real risk stands:** `docker network inspect eth0` reports
   `driver=macvlan parent=vhost0`, and `vhost0@eth0` carries the same
   192.168.1.99 as the management interface (from `DOCKER_ALLOW_ACCESS="yes"`).
   macvlan on the management link is the known Unraid hard-lock class, and a
   Docker restart is when it bites. Switching the custom network type to ipvlan
   is the documented mitigation — but note pihole holds a fixed IP on that
   network, so the change is not free and should be made deliberately, not as a
   side effect of something else.

### Sequel, same day

The array was started and the correcting parity check (`check P Q`, 11.7 TB) is
running. It does NOT conflict with Docker work: `docker.img` lives on the nvme
pool (`/mnt/cache/system/docker/docker.img`) while the check reads the array
disks, so there is no contention — measured, not assumed.

Model WEIGHTS went to a dedicated cache-only `models` share (§7 q3), which needs
no Docker at all. But the vDisk did have to grow after all — not for the models,
for the RUNTIME. Measured rather than guessed, by pulling it on a box with room:

    mmartial/comfyui-nvidia-docker:ubuntu24_cuda12.6-latest
      4.7 GB compressed / 31 layers  ->  14.5 GB on disk

against 9.44 GiB free. Image layers live in Docker's data-root by definition; no
bind mount can hold them, so no volume arrangement avoids this.

### Growing docker.img ONLINE, with nothing stopped

`docker.img` is btrfs on a loop device, and btrfs grows online. This took
seconds, restarted nothing, and left all six containers serving:

    IMG=/mnt/cache/system/docker/docker.img
    stat -c %s "$IMG"                      # 21474836480 -- and REFUSE if >= target
    truncate -s $((120*1024*1024*1024)) "$IMG"   # sparse growth, no data written
    losetup -c /dev/loop2                  # make the loop device see the new size
    btrfs filesystem resize max /var/lib/docker  # grow the fs inside

    Device size:  20.00GiB -> 120.00GiB
    Free:          9.44GiB -> 109.44GiB
    physically allocated on the pool: still 20G (sparse, grows on demand)

Then `DOCKER_IMAGE_SIZE="120"` in `/boot/config/docker.cfg` so the GUI agrees
with reality (backup kept alongside it). The size is only read when an image is
CREATED, so the edit is inert until then — but a stale value there is a trap for
whoever next presses Apply.

**The guard matters more than the commands.** `truncate` downwards would destroy
the filesystem, so the script refuses unless the target exceeds the current size.

This is not the GUI path, which deletes and recreates the vDisk and therefore
every container. It is the one that costs nothing.
