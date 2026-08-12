# ethan-wsl as a swarm backend — resume after reboot

> **UPDATE 2026-08-12 (day 9) — read this before the rest.**
>
> Resolved since this was written:
> - `UNBLOCK.md` is **deleted**. Both its items were verified dead: `jon` is in
>   the docker group and docker works over ssh, and nvidia-container-toolkit is
>   NOT needed — `/dev/dxg` passthrough gives the container the RTX 5080
>   (verified: `NVIDIA GeForce RTX 5080, 16303 MiB, 610.88`). `nvidia-smi` is not
>   on PATH under WSL passthrough; use `/usr/lib/wsl/lib/nvidia-smi`.
> - **Passwordless sudo now works** (the "Loose end" below is done).
> - **SSH keys are meshed and verified agent-free**: gamingpc<->ethan and
>   cerberus<->ethan. Ethan had no key at all; one was generated. Test any
>   cross-node access with `-o ForwardAgent=no` — agent forwarding hides a
>   missing key and the failure only appears when something runs detached.
> - **DNS is fixed** with a `resolved.conf.d` drop-in (`DNS=1.1.1.1 1.0.0.1`).
>   MagicDNS resolved tailnet names but had no global nameservers to forward
>   public queries to. The drop-in keeps MagicDNS working.
>
> **The new finding, which supersedes "this box will keep dropping out":** the box
> runs **Proton VPN**, and it captures all traffic. Confirmed on the host —
> `ProtonVPN.Client` and `ProtonVPNService` running, `0.0.0.0/1` + `128.0.0.0/1`
> routed to `ProTUN`, 5.26 GB received on that adapter, egress IP
> `134.82.68.167` = `AS208172 Proton AG, Miami`. That is why throughput is
> ~5 Mbit/s AND why Tailscale relays via DERP `"mia"` instead of peering
> directly: a VPN breaks UDP hole punching. One cause, both symptoms.
>
> **Do not disable it** — it is Ethan's machine and his choice. Ask for split
> tunnelling (exclude Docker/WSL/Tailscale) if the box is wanted seriously.
>
> **Its value dropped.** The one thing it could do that peaches could not was
> bf16 (ACE-Step). `cast_bf16_to_fp16.py` removed that distinction, so peaches —
> always-on, LAN-attached — now does music too. Treat ethan as opportunistic
> capacity and design nothing that depends on it. Build is stopped at
> 393 MB / 2.06 GB with layers cached; resume with
> `cd /home/jon/comfy-backend && docker compose build`.

Setting up Ethan's machine as a second ComfyUI backend for the SwarmUI instance
on cerberus. The build was interrupted when the machine went offline mid-way
(tailscale showed both `ethan-wsl` and `desktop-695nkr4` drop together, so the
host slept or shut down — nothing failed).

**Nothing is broken. Everything below is staged on his box and survives the
reboot.** Resume is one command once the box is back.

---

## The machine, as measured

| | |
|---|---|
| Host | `DESKTOP-695NKR4`, WSL2, Ubuntu 26.04 LTS, kernel 6.18.33.2-microsoft |
| GPU | **RTX 5080, 16303 MiB, driver 610.88** — confirmed *from inside a container* |
| Tailscale | `100.111.252.15` (`ethan-wsl`); the Windows host is `100.108.56.15` |
| Docker | 29.7.2, native (not Docker Desktop). `jon` **is** in the `docker` group |
| Disk | 954 GB free |
| Reachability | it can already reach cerberus ComfyUI — `http://100.103.148.120:8188` returned 200 |

Two things about this box that shaped every decision:

- **Python is 3.14.4 and there is no `pip`.** Torch has no wheels that new, so a
  native ComfyUI venv is not on the table. The container carries its own Python
  and torch and sidesteps it entirely.
- **`nvidia-container-toolkit` is NOT installed and is NOT needed.** WSL exposes
  the driver through `/dev/dxg` and ships its userspace libraries in
  `/usr/lib/wsl`. A container given both sees the card with no toolkit and no
  root. This was verified, not assumed:

      docker run --rm --device=/dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro \
        -e LD_LIBRARY_PATH=/usr/lib/wsl/lib \
        nvidia/cuda:12.8.1-base-ubuntu24.04 \
        /usr/lib/wsl/lib/nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
      # -> NVIDIA GeForce RTX 5080, 16303 MiB, 610.88

## What is staged on his box

`~/comfy-backend/` — survives the reboot:

- `Dockerfile` — CUDA 12.8 base, own venv, **torch cu128** (the 5080 is Blackwell
  / sm_120 and earlier CUDA builds have no kernels for it), ComfyUI, and **both
  SwarmUI node packs symlinked into `custom_nodes/`**. Without those the backend
  registers but runs degraded — 10 features instead of the 14 cerberus reports.
- `compose.yaml` — validated. GPU by the `/dev/dxg` route above. Published on
  **`100.111.252.15:8188` only, not `0.0.0.0`**: ComfyUI has no authentication and
  binding it wide would put it on Ethan's whole LAN rather than just the tailnet.
  That is stricter than cerberus deliberately, because it is not our network.
- `models/`, `input/`, `output/` — bind-mounted, so models live on the host and
  survive image rebuilds.
- `UNBLOCK.md` — now mostly obsolete; the toolkit steps are not needed.

**No SwarmUI on this box, on purpose.** One SwarmUI runs on cerberus and drives
every backend. Every extra install is another first-run wizard pointed at another
disk — which already cost us a broken self-start backend and 7.3 GB of litter on
cerberus when someone clicked through it in a browser.

---

## Resume: what to run after the reboot

Confirm the box is back first — from anywhere on the tailnet:

    tailscale status | grep ethan-wsl        # must not say "offline"
    ssh jon@ethan-wsl 'echo alive'

Then build and start it. **Run it detached** — an ssh drop killed the first
attempt, and the build takes 10-20 minutes because torch is ~3 GB:

    ssh jon@ethan-wsl 'cd ~/comfy-backend && nohup docker compose up -d --build > build.log 2>&1 &'

Watch it:

    ssh jon@ethan-wsl 'tail -f ~/comfy-backend/build.log'

When it is up, these must both be true:

    ssh jon@ethan-wsl 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8188/object_info'
    # -> 200
    ssh jon@ethan-wsl 'curl -s http://127.0.0.1:8188/object_info | python3 -c "
    import sys,json; d=json.load(sys.stdin)
    print(len([k for k in d if k.startswith(\"Swarm\")]))"'
    # -> ~59  (cerberus reports 59, gamingpc 60; far fewer means the packs did not load)
    #
    # Parse the JSON, do NOT use `grep -c "\"Swarm"`. Recent ComfyUI returns
    # /object_info as a SINGLE line, so grep -c counts lines and reports 1 for a
    # perfectly healthy backend. That cost a wrong diagnosis on gamingpc.

## Then register it on cerberus

SwarmUI runs with `--lock_settings`, so `AddNewBackend` answers
`{"error":"Settings are locked."}` until the flag comes off. It is there because
the instance has no authentication and every visitor on the tailnet is therefore
the `local` admin — without it anyone opening the page can add backends and start
model downloads onto the box, which is exactly what the first-run wizard did once
already. So it is a deliberate three-step dance:

1. Remove `--lock_settings` from `ExecStart` in
   `~/.config/systemd/user/swarmui.service` on cerberus, then
   `systemctl --user daemon-reload && systemctl --user restart swarmui`.
2. Register (`session_id` from `POST /API/GetNewSession`):

       POST /API/AddNewBackend  {"type_id": "comfyui_api"}          -> returns id
       POST /API/EditBackend    {"backend_id": <id>, "title": "ethan RTX 5080",
                                 "settings": {"Address": "http://100.111.252.15:8188",
                                              "AllowIdle": true, "OverQueue": 1}}

   `EditBackend` reads its values from a **nested `settings` object**; a flat body
   answers `{"error":"Missing settings."}`.
3. Put the flag back, `daemon-reload`, restart.

**`AllowIdle: true` is not cosmetic.** `ComfyUIAPIBackend.cs:32` is
`CanIdle => Settings.AllowIdle`, and that flag decides whether a connect failure
redirects the job to another backend or hard-fails. It defaults to false. Note
also that while locked, SwarmUI does not persist settings at all
(`Program.cs:694` returns early from `SaveSettingsFile`), so a backend added
without unlocking would not survive a restart even if it were accepted.

---

## Two things to be honest about before doing more of this

### 1. This box will keep dropping out

It just did. WSL2 tears its VM down when the last session closes, and the Windows
host sleeps on its own. Meanwhile, read from SwarmUI's source:

- A backend lost **while connecting** is redirected to another backend —
  `ComfyUIAPIAbstractBackend.cs:295-303`, and only when `AllowIdle` is true.
- A backend lost **mid-generation** is **not** requeued. `:575-582` sets the
  backend IDLE and rethrows; there is no redirect. The job dies.
- `studio/jobs.py` has no retry of any kind.

So a sleeping desktop costs whatever clip was rendering on it. Before this box is
worth relying on it needs to stay up: a Windows scheduled task at boot running
something like `wsl -d <distro> -e tail -f /dev/null` to hold the VM open, and the
host set not to sleep. Retry belongs in `studio/jobs.py` regardless — per-clip,
bounded, logged, and never for `edit_audio`, which moves `mp3_path`. That is
phase 3 of `docs/SWARM_PIPELINE_PLAN.md`.

### 2. A 16 GB card does not help with the slow part

Measured on cerberus, largest first:

| Model | Size | Fits in 16 GB? |
|---|---|---|
| `ltx-2-19b-dev-fp8` | 25.2 GB | no |
| `ltx-2.3-22b-distilled` | 21.9 GB | no |
| `qwen_image_edit_2511_fp8mixed` | 19.1 GB | no |
| `wan2.2_s2v_14B_fp8_scaled` | 15.3 GB | not with a text encoder beside it |
| `wan2.2_i2v_{high,low}_14B_fp8` | 13.3 GB each | tight; +6.3 GB umt5 encoder does not fit |
| `ace_step_v1_3.5b` | 7.2 GB | yes |
| `sd_xl_base_1.0` | 6.5 GB | yes |
| `Z-Image-Turbo-FP8Mix` | 6.1 GB | yes |

**The video models — the actual bottleneck — do not fit.** Ethan's box is a good
second worker for reference frames, album art and audio, and it is not a second
WAN renderer. Worth deciding what to sync before copying 100 GB across a tailnet:
Z-Image + SDXL + ACE-Step is ~20 GB and covers everything that box can actually
run.

Also: the studio cannot yet *send* work to Swarm at all. `pipeline.py` submits
straight to ComfyUI and harvests output files off a local path
(`collect()` globs `COMFY_OUTPUT`), so a render on Ethan's box would land on
Ethan's disk and the studio would see nothing — silently, as an empty result that
reads like a bad render. That is exactly what `docs/SWARM_PIPELINE_PLAN.md` plans
and none of it is built. **Registering this backend makes it visible in SwarmUI;
it does not yet make it useful to the studio.**

---

## Loose end

`jon`'s passwordless sudo on that box is configured but ineffective: `sudo -l`
lists `(ALL) NOPASSWD: ALL`, but `%sudo ALL=(ALL:ALL) ALL` comes after it and the
last matching rule wins. Nothing above needs sudo any more, so this is optional:

    echo 'jon ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/jon-nopasswd
    sudo chmod 440 /etc/sudoers.d/jon-nopasswd

`/etc/sudoers.d` is `@includedir`'d at the end, so a rule there wins.

---

**Standing archive directive:** when writing a session continuation or hand-off
`.md`, move the oldest top-level `CONTINUATION-*.md` into `docs/continuations/`
so only the latest three remain at top level, fix every inbound link to the moved
file, and refresh the docs index's "most recent" pointer.
