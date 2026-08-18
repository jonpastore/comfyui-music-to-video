"""Civitai search and LoRA download. No FastAPI.

Search is the public REST surface. Download needs a token — even public
files. The key is read only through creds.get("civitai").
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import creds

API = "https://civitai.com/api/v1"
DOWNLOAD = "https://civitai.com/api/download/models"
TIMEOUT = 20


def _headers():
    token = creds.get("civitai")
    h = {"User-Agent": "meowp-studio/1"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search(query, *, types="LORA", limit=12, nsfw=True, base_model=None):
    """List models. Empty query is newest LoRAs."""
    q = {"limit": int(limit), "types": types, "nsfw": "true" if nsfw else "false"}
    if query:
        q["query"] = query
    if base_model:
        q["baseModels"] = base_model
    url = API + "/models?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"civitai search failed: {e}") from e
    out = []
    for m in body.get("items") or []:
        ver = (m.get("modelVersions") or [{}])[0]
        files = ver.get("files") or []
        safetensor = next((f for f in files if str(f.get("name") or "").endswith(".safetensors")),
                          files[0] if files else {})
        out.append({
            "id": m.get("id"),
            "name": m.get("name") or "",
            "type": m.get("type") or "",
            "nsfw": bool(m.get("nsfw")),
            "version_id": ver.get("id"),
            "base_model": ver.get("baseModel") or "",
            "file": safetensor.get("name") or "",
            "size_mb": round((safetensor.get("sizeKB") or 0) / 1024, 1),
            "download_url": safetensor.get("downloadUrl") or (
                f"{DOWNLOAD}/{ver.get('id')}" if ver.get("id") else ""),
        })
    return out


def lora_dir():
    root = os.environ.get("COMFY_MODELS") or os.path.expanduser("~/ComfyUI/models")
    return os.path.join(root, "loras")


def list_installed(skip_video=True, skip_lightning=True):
    """LoRA filenames on this box, relative to lora_dir()."""
    root = lora_dir()
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith(".safetensors"):
                continue
            low = name.lower()
            if skip_lightning and "lightning" in low:
                continue
            if skip_video and ("ltx" in low or low.startswith("wan") or "wan2" in low):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def download(version_id, dest_dir=None):
    """Write one model version into dest_dir. Returns the local path."""
    token = creds.get("civitai")
    if not token:
        raise RuntimeError("no Civitai API key — store one on Config")
    if not version_id:
        raise ValueError("version_id required")
    dest_dir = dest_dir or lora_dir()
    os.makedirs(dest_dir, exist_ok=True)
    url = f"{DOWNLOAD}/{int(version_id)}?token={urllib.parse.quote(token)}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            name = os.path.basename(urllib.parse.urlparse(r.url).path) or f"{version_id}.safetensors"
            name = os.path.basename(name.split("?")[0]) or f"{version_id}.safetensors"
            path = os.path.join(dest_dir, name)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, path)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"civitai download failed: {e}") from e
    return path


import jobs


@jobs.handler("download_lora")
def h_download_lora(args, progress):
    vid = args.get("version_id")
    progress(f"downloading civitai version {vid}")
    path = download(vid)
    progress(f"saved {path}")
    return {"path": path}
