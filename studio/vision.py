"""Ask a model about an image, or ask a local model for structured text.

Local model first, xAI only as a fallback.

Two jobs in this pipeline need eyes:

  classify_sheet  -- review a contact sheet of the frames that will be rendered.
                     Runs per song, on 40-80 frames, repeatedly. Cost matters,
                     so this belongs on the local fleet.
  describe_anchor -- draft an album-profile field from the anchor. Once per
                     album at setup. Cost does not matter.

Backend choice is made per call, not at import: the local gateway comes and
goes as models are loaded on it, and a studio that started before the model did
must not be stuck on the paid path for the rest of its life.

The local door is the litellm gateway (OpenAI-compatible). Its key lives in
~/.config/morpheus/litellm.env, never in the repo.
"""
import base64
import json
import os
import re

import httpx

import grok

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

KEY_FILE = os.path.expanduser("~/.config/morpheus/litellm.env")
BASE = os.environ.get("LITELLM_BASE", "")
KEY = os.environ.get("LITELLM_KEY", "")
# Explicit override wins; otherwise any model whose id looks like a vision
# model is used, so loading one on the gateway is all it takes to switch over.
MODEL = os.environ.get("STUDIO_VISION_MODEL", "")
# Pin the text-only model. See local_text_model() for why a render box needs it.
TEXT_MODEL = os.environ.get("STUDIO_TEXT_MODEL", "")
_VISION_HINTS = ("vl", "vision", "llava", "pixtral", "moondream", "intern")
TIMEOUT = float(os.environ.get("STUDIO_VISION_TIMEOUT", 180))


def _env():
    base, key = BASE, KEY
    try:
        with open(KEY_FILE) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                v = v.strip().strip('"').strip("'")
                if k == "LITELLM_KEY" and not key:
                    key = v
                elif k == "LITELLM_BASE" and not base:
                    base = v
    except FileNotFoundError:
        pass
    return base, key


def local_model():
    """The local vision model id, or None. Never raises: no gateway, no key,
    no vision model loaded and a timeout all mean the same thing to a caller."""
    base, key = _env()
    if not base or not key:
        return None
    if MODEL:
        return MODEL
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return None
    hits = [i for i in ids if any(h in i.lower() for h in _VISION_HINTS)]
    return hits[0] if hits else None


def available():
    """(where, detail) for the UI and the job log."""
    m = local_model()
    if m:
        return "local", f"{m} via the litellm gateway"
    return "xai", "no local vision model; falling back to xAI (billed)"


def _data_url(path):
    with open(path, "rb") as f:
        raw = f.read()
    kind = "png" if path.lower().endswith(".png") else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


def _ask_local(model, image_path, system, user_text):
    base, key = _env()
    content = [{"type": "text", "text": user_text},
               {"type": "image_url", "image_url": {"url": _data_url(image_path)}}]
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": content}]
    r = httpx.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "messages": messages,
                         "response_format": {"type": "json_object"}},
                   timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"local vision model {model} failed ({r.status_code}): {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"] or ""


def _image_parts(paths):
    parts = []
    for p in paths:
        if p and os.path.isfile(p):
            parts.append({"type": "image_url",
                          "image_url": {"url": _data_url(p), "detail": "high"}})
    return parts


def _provider_record(provider, *, fallback=False):
    """What a vision call records so cost is attributable (T10-2)."""
    return {"provider": provider, "backend": provider, "fallback": bool(fallback)}


def ask_images(paths, system, user_text, progress=None, prefer_local=True):
    """Several images + one question -> (raw reply, provider record).

    First path is the subject. The record names who answered; a paid path
    taken while local was preferred is marked fallback (T10-2).
    """
    parts = [{"type": "text", "text": user_text}] + _image_parts(paths)
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": parts}]
    if prefer_local:
        model = local_model()
        base, key = _env()
        if model and base and key:
            try:
                if progress:
                    progress(f"vision: {model} (local)")
                r = httpx.post(f"{base}/chat/completions",
                               headers={"Authorization": f"Bearer {key}"},
                               json={"model": model, "messages": messages,
                                     "response_format": {"type": "json_object"}},
                               timeout=TIMEOUT)
                if r.status_code >= 400:
                    raise RuntimeError(f"local vision model {model} failed "
                                       f"({r.status_code}): {r.text[:200]}")
                text = r.json()["choices"][0]["message"]["content"] or ""
                return text, _provider_record("local", fallback=False)
            except Exception as e:
                if progress:
                    progress(f"vision: local model failed ({e}); falling back to xAI")
    if progress:
        progress("vision: xAI (billed)")
    text = grok._chat(grok._resolve_model(grok.VISION_MODEL), messages, progress)
    return text, _provider_record("xai", fallback=prefer_local)


SCORE_SYSTEM = (
    "You compare one generated frame (first image) to the operator's "
    "base photographs (the remaining images) and to the prompt that was asked. "
    "Score identity and prompt independently. Then set confidence to the "
    "MINIMUM of those two numbers. Do not average. A frame that matches "
    "composition but is the wrong species is identity <= 25 and confidence <= 25. "
    "identity (0-100): same individual as the photographs — face, ears, hair, "
    "fur colour, species, body proportions, drawn-feline anatomy. "
    "Wardrobe does NOT lower identity. Adding a jacket, chains, pants, or "
    "taking clothes off a nude plate is expected. "
    "Human skin or a human face on a feline character is <= 20. "
    "A second tail, a missing tail, or a melted/extra limb is <= 30. "
    "Nipples, vulva, or body colour that do not match the photographs "
    "(jet-black instead of charcoal-brown, human flesh instead of fur) "
    "are identity defects, not wardrobe. "
    "prompt (0-100): asked view, pose, and wardrobe. Seated must be sitting, "
    "not standing. Portrait must be head-and-shoulders, not a full-body "
    "figure in a tall frame. On all fours must be on hands and knees. "
    "Standing views must stand. Asked clothes may be present. "
    "notes: one short sentence naming the worst PHYSICAL identity defect "
    "(species, face, fur, anatomy, tail, limbs) or saying what matches. "
    "Do not name clothes as an identity defect. "
    "Do not invent a PASS/FAIL. Answer JSON only: "
    '{"confidence": <0-100>, "identity": <0-100>, "prompt": <0-100>, '
    '"notes": "<one short sentence>"}.'
)


def parse_score(obj):
    """Clamp a model dict to the stored shape. Bad numbers become unknown."""
    def _n(key):
        try:
            v = int(round(float(obj.get(key))))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, v))
    got = {"confidence": _n("confidence"), "identity": _n("identity"),
           "prompt": _n("prompt"),
           "notes": " ".join(str(obj.get("notes") or "").split())[:200]}
    def _in_range(key):
        try:
            v = float(obj.get(key))
        except (TypeError, ValueError):
            return False
        return 0 <= v <= 100
    if (got["confidence"] is not None and _in_range("identity")
            and _in_range("prompt")):
        got["confidence"] = min(got["confidence"], got["identity"], got["prompt"])
    return got


def _backend_from_error(err, where):
    """Prefer the backend named by the exception over available().

    available() is what we hoped to use. After a local-then-xAI fallback the
    exception is from xAI while available() still says local.
    """
    e = (err or "").lower()
    if "xai" in e:
        return "xai"
    if "local" in e:
        return "local"
    return where


def score_candidate(path, bases, prompt="", progress=None):
    """Advisory match of one candidate to the base photographs and the prompt.

    Never a gate. A vision failure is confidence=None, not a reject.
    Records the provider that actually answered; a paid fallback is marked
    (T10-2).
    """
    where, detail = available()
    bases = [b for b in (bases or []) if b and os.path.isfile(b)]
    if not path or not os.path.isfile(path):
        rec = _provider_record(where, fallback=False)
        return {"confidence": None, "identity": None, "prompt": None,
                "notes": "", "error": "candidate file missing", **rec}
    user = ("First image: the generated candidate. Remaining images: the "
            "operator's base photographs. Prompt that was asked:\n"
            + (prompt or "(album default composition)"))
    try:
        raw, call = ask_images([path] + bases[:3], SCORE_SYSTEM, user, progress)
        obj = json_or_raise(raw, "anchor score")
    except Exception as e:
        if progress:
            progress(f"vision score failed: {e}")
        err = str(e)[:200]
        backend = _backend_from_error(err, where)
        rec = _provider_record(backend, fallback=(backend == "xai" and where == "local"))
        return {"confidence": None, "identity": None, "prompt": None,
                "notes": "", "error": err, **rec}
    got = parse_score(obj)
    got.update(call)
    return got


def ask(image_path, system, user_text, progress=None, prefer_local=True):
    """One image + one question -> (raw reply text, provider record).

    A local failure falls through to xAI rather than failing the job: the local
    gateway is best-effort infrastructure, and a half-loaded model must not cost
    someone an hour of rendering. The record names who answered; a paid path
    taken while local was preferred is marked fallback (T10-2).
    """
    if prefer_local:
        model = local_model()
        if model:
            try:
                if progress:
                    progress(f"vision: {model} (local)")
                text = _ask_local(model, image_path, system, user_text)
                return text, _provider_record("local", fallback=False)
            except Exception as e:
                if progress:
                    progress(f"vision: local model failed ({e}); falling back to xAI")
    if progress:
        progress("vision: xAI (billed)")
    content = [{"type": "text", "text": user_text},
               {"type": "image_url", "image_url": {"url": _data_url(image_path), "detail": "high"}}]
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": content}]
    text = grok._chat(grok._resolve_model(grok.VISION_MODEL), messages, progress)
    return text, _provider_record("xai", fallback=prefer_local)


def json_or_raise(out, what):
    """Parse a model's reply as JSON, or raise saying which caller it came from.

    Public because app.py's genre suggestion needs the same leading-zero repair
    and the same fence stripping every other model reply here needs; a second
    parser beside this one would drift from it.
    """
    text = _FENCE.sub("", out or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Local models echo the cell label back as a number: the sheet says
    # "clip 003" and qwen3-vl answers {"clip": 003}, which is not legal JSON.
    # Repair only after a straight parse has failed, so valid output is never
    # touched, and only leading zeros on a value -- nothing inside a string.
    repaired = re.sub(r'(:\s*)0+(\d)', r"\1\2", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{what} returned non-JSON: {e}") from None


def local_text_model():
    """Any local chat model, vision or not -- for text-only jobs like reading an
    edit instruction. Prefers an instruct/chat model over an embedding or
    rerank one, which are on the same gateway and cannot answer.

    STUDIO_TEXT_MODEL pins one, and on a box that also renders it should be set:
    the gateway fronts several machines and auto-detection cannot see which. On
    cerberus the first match is `qwen3.6-coder`, which is ollama on THIS box --
    and ComfyUI already holds ~22 GB of the 24 GB card, so ollama silently loads
    that 27B model on the CPU instead. Measured through the gateway: 315 ms for
    a model on the other box, versus no answer at all in 90 s for that one.
    """
    if TEXT_MODEL:
        return TEXT_MODEL
    base, key = _env()
    if not base or not key:
        return None
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return None
    skip = ("embed", "rerank", "whisper", "router")
    usable = [i for i in ids if not any(s in i.lower() for s in skip)]
    # prefer a local one: the gateway also fronts paid APIs under plain names
    local_first = [i for i in usable if any(h in i.lower() for h in ("qwen", "oss", "llama"))]
    return (local_first or usable or [None])[0]


def ask_text(system, user_text, progress=None, model=None):
    """One text question -> the model's raw reply. Local only: the callers are
    conveniences, and none of them is worth a paid call if the fleet is down."""
    base, key = _env()
    model = model or local_text_model()
    if not (base and key and model):
        raise RuntimeError("no local text model available on the litellm gateway")
    if progress:
        progress(f"asking {model} (local)")
    r = httpx.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user_text}],
                         "response_format": {"type": "json_object"}},
                   timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"local model {model} failed ({r.status_code}): {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"] or "", model


# --------------------------------------------------------------- reviewing --

# T10-14: a model is never asked a question whose answer it cannot be
# visibly wrong about. "Does this match?" is the shape that produced
# 41.1-vs-64.7. "describe what differs" is the accepted shape.
DESCRIBE_DIFFERS = "describe what differs"
_MATCH_SHAPE = re.compile(
    r"\bdoes this match\b|\bdo these match\b|\bdoes it match\b|"
    r"\bmatch the reference\b|\bis this a match\b|\bis it a match\b",
    re.I,
)


def prompt_shape(question):
    """Refuse a match question. Return the question otherwise (T10-14)."""
    q = " ".join((question or "").split())
    if not q:
        raise ValueError("empty question is not a prompt shape")
    if _MATCH_SHAPE.search(q):
        raise ValueError(
            "does this match? is refused as a prompt shape (T10-14); "
            "ask 'describe what differs'")
    return q


REVIEW_SYSTEM = (
    "You are reviewing a contact sheet of AI-generated frames for one music video. "
    "It is a grid of frames, each labelled 'clip N' in the top-left of its cell. "
    "Judge only what is visible.\n\n"
    "You have TWO jobs.\n\n"
    "1. CONTINUITY. The same character appears in every frame and must look like the "
    "same individual throughout. Compare the cells against each other and flag any cell "
    "that breaks continuity: fur or skin colour that differs from the other frames "
    "(pale or human-toned limbs on an otherwise dark-furred character is the known "
    "failure), hair colour or length changing, eye colour changing, ears or tail "
    "missing or changed, wardrobe changing when the other frames agree, or the "
    "character's build changing. Say which cells are the majority and which is the odd "
    "one out -- the flagged clip is the one that disagrees with the rest.\n\n"
    "2. USABILITY. Flag a cell that is broken: two copies of the character, extra or "
    "missing limbs, melted anatomy, or unreadable garbage.\n\n"
    "Deliberate variation is NOT a fault: camera angle, distance, location, lighting "
    "colour and pose are supposed to change between frames. A dark scene is not a fur "
    "colour change. Only flag what a viewer would read as a different character or a "
    "broken frame.\n\n"
    'Answer with JSON only: {"flagged": [{"clip": <int>, "issue": "continuity"|"broken", '
    '"reason": "<short, name the specific mismatch>"}], "cells_seen": <int>}. '
    'An empty "flagged" list is the expected answer for a consistent sheet.'
)


def classify_sheet(sheet_path, note="", model=None, progress=None, question=None):
    """Review one contact sheet.

    Returns flagged clips, cells_seen, and the provider record (backend /
    provider / fallback). Advisory: names clips to look at; never unapproves
    or deletes. Attach with qc_service.attach_sheet_review (T10-13 / TRD-3 §10).
    The user prompt is the T10-14 accepted shape.
    """
    where, detail = available()
    if progress:
        progress(f"reviewing with {detail}")
    user = prompt_shape(question or DESCRIBE_DIFFERS)
    if note:
        user = f"{user}. Context: {note}"
    out, call = ask(sheet_path, REVIEW_SYSTEM, user, progress)
    obj = json_or_raise(out, "vision review")
    flagged = []
    for f in obj.get("flagged") or []:
        if not isinstance(f, dict) or "clip" not in f:
            continue
        try:
            clip = int(f["clip"])
        except (TypeError, ValueError):
            continue
        flagged.append({"clip": clip, "issue": str(f.get("issue", "other"))[:20],
                        "reason": str(f.get("reason", ""))[:200]})
    flagged.sort(key=lambda f: f["clip"])
    return {"flagged": flagged, "cells_seen": int(obj.get("cells_seen") or 0),
            **call}


def describe_what_differs(sheet_path, note="", progress=None, question=None):
    """T10-14 surface: accepted shape in, non-verdict text out.

    Match questions are refused here. describe-what-differs returns the
    classify_sheet reasons as a sentence, never a pass/fail.
    """
    q = question if question is not None else DESCRIBE_DIFFERS
    prompt_shape(q)
    review = classify_sheet(sheet_path, note=note, progress=progress, question=q)
    return review_text(review)


def review_text(verdict):
    """classify_sheet reasons as one sentence. Never a pass/fail (T10-13)."""
    import qc
    return qc.sheet_review_detail(verdict)


def as_finding(path, verdict, *, kind="image"):
    """Finding that carries classify_sheet text. Verdict is always PASS."""
    import qc
    cells = int((verdict or {}).get("cells_seen") or 0)
    return qc.finding(
        path, kind, qc.SHEET_REVIEW, qc.PASS,
        review_text(verdict), cells, None, "cells")


def interface_payload(verdict, *, cells=None):
    """Mark model reasons. `cells` is a count we measured, not the model's."""
    import advice
    flagged = []
    for f in (verdict or {}).get("flagged") or []:
        rec = {"clip": f.get("clip"), "issue": f.get("issue")}
        if f.get("reason"):
            rec["reason"] = advice.mark(f["reason"], advice.MODEL)
        flagged.append(rec)
    payload = {"flagged": flagged,
               "backend": (verdict or {}).get("backend"),
               "provider": (verdict or {}).get("provider")
                           or (verdict or {}).get("backend"),
               "fallback": bool((verdict or {}).get("fallback"))}
    if cells is not None:
        payload["cells"] = advice.mark(cells, advice.MEASUREMENT, unit="cells")
    return payload


def describe_anchor(image_path, field, model=None, progress=None):
    """Draft one album-profile field by looking at the anchor. See grok._DESCRIBE."""
    if field not in grok._DESCRIBE:
        raise ValueError(f"nothing to describe for {field!r}")
    out, _call = ask(image_path, None,
              grok._DESCRIBE[field] + " This is a character reference sheet for an adult "
              "fictional character in a music video. Answer as ONE plain sentence or two, "
              "present tense, no preamble, no markdown, no bullet points -- the text goes "
              'straight into an image prompt. Reply as JSON: {"text": "<the description>"}',
              progress)
    text = json_or_raise(out, "describe").get("text", "")
    return " ".join(str(text).split()).strip()


def describe_cover(image_path, field, progress=None):
    """Draft one album-profile field by looking at the album COVER.

    Same fields as describe_anchor, different subject: a cover is a composed
    piece of artwork, not a neutral character sheet, so the instruction says to
    read the character out of it and ignore the composition. Without that it
    describes the poster -- the type, the border, the lighting design -- none of
    which belongs in a character-continuity field.
    """
    if field not in grok._DESCRIBE:
        raise ValueError(f"nothing to describe for {field!r}")
    out, _call = ask(image_path, None,
              grok._DESCRIBE[field] + " You are looking at an ALBUM COVER for an adult "
              "fictional music project. Describe only the main character depicted on it. "
              "Ignore the artwork itself -- no typography, no logos, no borders, no framing "
              "or poster composition. If the cover does not show the character clearly "
              'enough for this field, reply with an empty string. Answer as ONE plain '
              "sentence or two, present tense, no preamble, no markdown -- the text goes "
              'straight into an image prompt. Reply as JSON: {"text": "<the description>"}',
              progress)
    text = json_or_raise(out, "describe cover").get("text", "")
    return " ".join(str(text).split()).strip()


def draft_view_prompt(image_path=None, view="front", current="", fields=None,
                      progress=None):
    """Recommend one character-sheet prompt for a single camera/pose.

    The text lands in the view's box for the operator to edit. It is not a
    storyboard beat and must not mention scenes, clips or a shot list.
    """
    import make_anchor
    fields = fields or {}
    spec = make_anchor.VIEWS.get(view) or {}
    framing = spec.get("framing") or view
    nude = make_anchor.is_nude_view(view)
    bits = [
        f"Write ONE character-sheet image prompt for this exact view: {view}.",
        f"Framing to keep: {framing.strip()}",
        "Nude sheet." if nude else "Clothed sheet.",
        "Positive statements only. Adult fictional character.",
        "Do not mention a storyboard, scene, clip, shot list or music-video beat.",
        "Match the drawing style of the reference photograph if one is attached.",
    ]
    for key in ("identity", "body", "wardrobe", "anatomy"):
        if fields.get(key):
            bits.append(f"{key}: {fields[key]}")
    if current:
        bits.append(f"Current wording the operator can replace: {current}")
    user = " ".join(bits) + ' Reply as JSON: {"text": "<the full prompt>"}'
    system = (
        "You draft character-sheet prompts for still identity locks. "
        "One paragraph. Present tense. No markdown. No storyboard language."
    )
    if image_path and os.path.isfile(image_path):
        raw, _call = ask(image_path, system, user, progress)
    else:
        raw, _used = ask_text(system, user, progress)
    text = json_or_raise(raw, f"draft {view}").get("text", "")
    return " ".join(str(text).split()).strip()


CAST_SYSTEM = (
    "You are looking at an ALBUM COVER for an adult fictional music project and proposing "
    "ONE named supporting character for its music videos -- not the lead, who already "
    "exists, but a second character who would fit this world: a duet partner, a rival, an "
    "antagonist.\n\n"
    "Base it on what the cover actually shows -- its setting, palette, era and mood. If a "
    "second figure is visible, describe THAT figure. Otherwise invent one that belongs in "
    "the same world.\n\n"
    "Every character is an adult. Describe appearance only.\n\n"
    'Reply with JSON only: {"name": "<a short name>", "role": "<two or three words, e.g. '
    '\\"rival DJ\\">", "identity": "<face, eyes, ears, hair, markings, build -- the traits '
    'that must not drift between frames>", "wardrobe": "<what is WORN: garments, cut, '
    'materials, hardware. Never what is absent>", "body": "<colouring and texture PER BODY '
    'PART: shoulders, arms, torso, hips, thighs, calves, naming the colour each time>"}. '
    "Each value is one or two plain sentences, present tense, no markdown."
)


def propose_character(image_path, progress=None):
    """Look at the album cover and draft one supporting character.

    Returns a dict of the same fields the add-character form has, so the
    proposal lands in the boxes for editing. Nothing is saved by this -- it is
    the wand for a whole character rather than for one field.
    """
    out, _call = ask(image_path, CAST_SYSTEM,
                     "Propose one supporting character for this album.",
                     progress)
    obj = json_or_raise(out, "cast proposal")
    keys = ("name", "role", "identity", "wardrobe", "body")
    return {k: " ".join(str(obj.get(k, "") or "").split()).strip()[:1000] for k in keys}


# ----------------------------------------------------------- audio edits --

EDIT_SYSTEM = (
    "You turn a plain-English instruction about an audio track into edit "
    "parameters for ffmpeg. The track is TRACK_SECONDS seconds long.\n\n"
    "Reply with JSON only: {\"trim_start\": <seconds from the start to cut off>, "
    "\"trim_end\": <keep audio up to this timestamp, or null for the end>, "
    "\"gain_db\": <volume change in dB>, \"fade_in\": <seconds>, "
    "\"fade_out\": <seconds>, \"note\": \"<one line saying what you did>\"}.\n\n"
    "Rules: every number is seconds from the START of the track, not a duration "
    "to remove from somewhere in the middle -- you can only cut from the ends. "
    "If the instruction asks to remove something in the MIDDLE, set the numbers "
    "to leave the track unchanged and say so in note. Use 0 for anything not "
    "asked for. Never invent a fade nobody asked for."
)


def read_edit_instruction(prompt, duration, progress=None):
    """Plain English -> edit parameters. Returns (params, note, model).

    Deliberately mapped onto the SAME five parameters the manual form has, so
    the result is deterministic ffmpeg, reversible, and clamped by exactly the
    same validation. The model reads the instruction; it does not touch audio.
    """
    out, model = ask_text(EDIT_SYSTEM.replace("TRACK_SECONDS", f"{duration:.1f}"),
                          prompt, progress)
    obj = json_or_raise(out, "edit instruction")

    def num(key, default=0.0):
        v = obj.get(key, default)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        return f if f == f and abs(f) != float("inf") else default

    params = {"trim_start": num("trim_start") or 0.0,
              "trim_end": num("trim_end", None),
              "gain_db": num("gain_db") or 0.0,
              "fade_in": num("fade_in") or 0.0,
              "fade_out": num("fade_out") or 0.0}
    return params, str(obj.get("note", ""))[:300], model


def demo():
    import subprocess, tempfile

    real_get, real_post = httpx.get, httpx.post

    with tempfile.TemporaryDirectory() as d:
        sheet = os.path.join(d, "sheet.jpg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64",
                        "-frames:v", "1", sheet], check=True, capture_output=True)

        # --- model discovery: a vl-looking id is picked up automatically ---
        class R:
            status_code = 200

            def __init__(self, payload):
                self._p = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._p

        global BASE, KEY, MODEL
        BASE, KEY, MODEL = "http://gw/v1", "k", ""
        httpx.get = lambda url, headers=None, timeout=None: R(
            {"data": [{"id": "gpt-oss-120b"}, {"id": "qwen3-vl"}]})
        assert local_model() == "qwen3-vl", local_model()
        assert available()[0] == "local"

        httpx.get = lambda url, headers=None, timeout=None: R({"data": [{"id": "gpt-oss-120b"}]})
        assert local_model() is None, "text-only fleet must not look like vision"
        assert available()[0] == "xai"

        # a gateway that is down is not an error, just not local
        def boom(url, headers=None, timeout=None):
            raise httpx.ConnectError("refused")

        httpx.get = boom
        assert local_model() is None

        # --- the local path is used, and its answer parsed ---
        httpx.get = lambda url, headers=None, timeout=None: R(
            {"data": [{"id": "qwen3-vl"}]})
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen["body"] = json
            payload = {"flagged": [{"clip": "7", "issue": "continuity",
                                    "reason": "pale legs, every other cell is black"},
                                   {"issue": "broken"}],
                       "cells_seen": 12}
            return type("P", (), {
                "status_code": 200,
                "json": staticmethod(lambda: {
                    "choices": [{"message": {"content": __import__("json").dumps(payload)}}]}),
                "text": "",
            })

        httpx.post = fake_post
        v = classify_sheet(sheet, note="T (r tier)")
        assert v["backend"] == "local", v
        assert [f["clip"] for f in v["flagged"]] == [7], v      # junk row dropped
        assert v["flagged"][0]["issue"] == "continuity"
        assert v["cells_seen"] == 12
        assert seen["body"]["model"] == "qwen3-vl"
        sys_msg = seen["body"]["messages"][0]["content"]
        assert "CONTINUITY" in sys_msg and "human-toned limbs" in sys_msg
        assert "camera angle" in sys_msg, "must not flag deliberate variation"
        user_msg = seen["body"]["messages"][1]["content"][0]["text"]
        assert DESCRIBE_DIFFERS in user_msg.lower()
        try:
            prompt_shape("Does this match the reference?")
            raise AssertionError("match question was accepted")
        except ValueError as e:
            assert "describe what differs" in str(e).lower(), e
        img = seen["body"]["messages"][1]["content"][1]["image_url"]["url"]
        assert img.startswith("data:image/jpeg;base64,")

        # --- a local failure falls through to xAI rather than failing ---
        def bad_post(url, headers=None, json=None, timeout=None):
            return type("P", (), {"status_code": 500, "text": "boom", "json": staticmethod(dict)})

        httpx.post = bad_post
        notes = []
        real_chat = grok._chat
        grok._chat = lambda model, messages, progress=None: '{"flagged": [], "cells_seen": 3}'
        try:
            v2 = classify_sheet(sheet, progress=notes.append)
            assert v2["flagged"] == [] and v2["cells_seen"] == 3, v2
            assert any("falling back to xAI" in n for n in notes), notes
        finally:
            grok._chat = real_chat

    # --- leading-zero ints from a local model still parse ------------------
    # qwen3-vl echoes the sheet's own label: {"clip": 003}
    assert json_or_raise('{"clip": 003, "ok": 1}', "t") == {"clip": 3, "ok": 1}
    assert json_or_raise('{"a": 0, "b": 10}', "t") == {"a": 0, "b": 10}, "valid JSON must be untouched"
    assert json_or_raise('{"s": "id 007"}', "t") == {"s": "id 007"}, "must not rewrite inside strings"
    try:
        json_or_raise("not json", "t")
        raise AssertionError("garbage parsed")
    except RuntimeError:
        pass

    # --- an instruction becomes clamped, reversible ffmpeg params ---------
    httpx.get = lambda url, headers=None, timeout=None: R({"data": [{"id": "qwen3.6:27b"},
                                                                    {"id": "qwen3-embed"}]})
    assert local_text_model() == "qwen3.6:27b", local_text_model()

    asked = {}

    def text_post(url, headers=None, json=None, timeout=None):
        asked["body"] = json
        payload = {"trim_start": 4.0, "trim_end": None, "gain_db": 0,
                   "fade_in": "0.5", "fade_out": 0, "note": "cut the first 4s"}
        return type("P", (), {"status_code": 200, "text": "",
                              "json": staticmethod(lambda: {"choices": [
                                  {"message": {"content": __import__("json").dumps(payload)}}]})})

    httpx.post = text_post
    params, note, model = read_edit_instruction("cut the giggling in the first 4 seconds", 195.8)
    assert params == {"trim_start": 4.0, "trim_end": None, "gain_db": 0.0,
                      "fade_in": 0.5, "fade_out": 0.0}, params      # strings coerced
    assert note == "cut the first 4s" and model == "qwen3.6:27b"
    assert "195.8" in asked["body"]["messages"][0]["content"], "model was not told the length"

    # a model that answers with junk must not put junk in an ffmpeg command
    def junk_post(url, headers=None, json=None, timeout=None):
        payload = {"trim_start": "nonsense", "gain_db": float("inf"), "fade_in": None}
        return type("P", (), {"status_code": 200, "text": "",
                              "json": staticmethod(lambda: {"choices": [
                                  {"message": {"content": __import__("json").dumps(payload)}}]})})

    httpx.post = junk_post
    params2, _, _ = read_edit_instruction("do something", 100.0)
    assert params2["trim_start"] == 0.0 and params2["gain_db"] == 0.0, params2
    assert all(v is None or v == v for v in params2.values()), params2

    httpx.get, httpx.post = real_get, real_post
    print("vision.py OK")


if __name__ == "__main__":
    demo()
