"""Civitai search and LoRA download. No FastAPI.

Search is the public REST surface. A token is optional for public files
(Civitai 307s to B2). The key is read only through creds.get("civitai").
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
PACK_PATH = os.path.join(os.path.dirname(__file__), "seed", "lora_pack.json")
FAMILIES = ("qwen", "flux2", "klein", "zimage", "krea2")
GROUP_ORDER = ("Anatomy", "Popular", "Other")


def _headers():
    token = creds.get("civitai")
    h = {"User-Agent": "meowp-studio/1"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search(query, *, types="LORA", limit=12, nsfw=True, base_model=None,
           sort="Most Downloaded"):
    """List models. Empty query is most-downloaded LoRAs for the base."""
    q = {"limit": int(limit), "types": types, "nsfw": "true" if nsfw else "false",
         "sort": sort or "Most Downloaded"}
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


def load_pack():
    """Curated New Image LoRA pack (labels, family, Civitai version ids)."""
    try:
        with open(PACK_PATH) as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"families": {}, "items": []}


def family_for(model_key):
    """Studio t2i key → pack family (qwen/flux2/klein/zimage/krea2)."""
    key = (model_key or "").strip()
    for fam, spec in (load_pack().get("families") or {}).items():
        if key in (spec.get("keys") or []):
            return fam
    low = key.lower()
    if "klein" in low:
        return "klein"
    if "krea" in low:
        return "krea2"
    if "z_image" in low or low.startswith("zimage"):
        return "zimage"
    if "flux" in low:
        return "flux2"
    return "qwen"


def base_for(model_key):
    """Civitai baseModels string for the New Image picker / search."""
    fam = family_for(model_key)
    spec = (load_pack().get("families") or {}).get(fam) or {}
    return spec.get("base") or "Qwen"


def infer_family(rel):
    """Family from a path under models/loras (subdir or legacy Qwen root)."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    head = rel.split("/", 1)[0] if "/" in rel else ""
    if head in FAMILIES:
        return head
    return "qwen"


def _pack_index():
    out = {}
    for it in load_pack().get("items") or []:
        f = (it.get("file") or "").replace("\\", "/")
        if f:
            out[f] = it
            out[os.path.basename(f)] = it
    return out


def list_for_model(model_key, skip_video=True, skip_lightning=True):
    """Installed LoRAs for one t2i family, grouped for the Style LoRA select."""
    fam = family_for(model_key)
    idx = _pack_index()
    grouped = {g: [] for g in GROUP_ORDER}
    seen = set()
    for rel in list_installed(skip_video=skip_video, skip_lightning=skip_lightning):
        if infer_family(rel) != fam:
            continue
        meta = idx.get(rel) or idx.get(os.path.basename(rel)) or {}
        group = meta.get("group") if meta.get("group") in grouped else "Other"
        label = (meta.get("label") or os.path.basename(rel)).strip()
        row = {"file": rel, "label": label, "group": group}
        grouped[group].append(row)
        seen.add(rel)
        seen.add(os.path.basename(rel))
    missing = []
    for it in load_pack().get("items") or []:
        if it.get("family") != fam or not it.get("version_id"):
            continue
        rel = (it.get("file") or "").replace("\\", "/")
        if not rel or rel in seen or os.path.basename(rel) in seen:
            continue
        missing.append({
            "file": rel, "label": it.get("label") or os.path.basename(rel),
            "group": it.get("group") or "Other",
            "version_id": int(it["version_id"]),
        })
    groups = [{"name": g, "loras": grouped[g]} for g in GROUP_ORDER if grouped[g]]
    return {"family": fam, "groups": groups, "missing": missing}


def download(version_id, dest_dir=None, dest_name=None):
    """Write one model version into dest_dir. Returns the local path."""
    if not version_id:
        raise ValueError("version_id required")
    dest_dir = dest_dir or lora_dir()
    os.makedirs(dest_dir, exist_ok=True)
    token = creds.get("civitai")
    url = f"{DOWNLOAD}/{int(version_id)}"
    if token:
        url += f"?token={urllib.parse.quote(token)}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            name = dest_name or os.path.basename(
                urllib.parse.urlparse(r.url).path.split("?")[0]
            ) or f"{version_id}.safetensors"
            if not name.endswith(".safetensors"):
                name = f"{version_id}.safetensors"
            path = os.path.join(dest_dir, os.path.basename(name))
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
    rel = (args.get("file") or "").replace("\\", "/").lstrip("/")
    fam = args.get("family") or (infer_family(rel) if rel else "")
    dest_dir = lora_dir()
    dest_name = os.path.basename(rel) if rel else None
    if fam in FAMILIES:
        dest_dir = os.path.join(dest_dir, fam)
        if rel and rel.startswith(fam + "/"):
            dest_name = os.path.basename(rel)
    progress(f"downloading civitai version {vid}")
    path = download(vid, dest_dir=dest_dir, dest_name=dest_name)
    progress(f"saved {path}")
    return {"path": path}
