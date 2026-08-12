"""One JSON-chat interface, two real backends.

ALBUM_ARC_AND_STAGING_PLAN.md section 4's provider note: two real
implementations justify the seam, one would not. xAI is the backend that has
always been here and needs no new credential; OpenAI is the second, and exists
because a seam with a single implementation is an abstraction pretending to be
a decision.

Everything here returns PARSED JSON, because every caller wants JSON: both
providers are asked for `response_format: json_object` and a reply that is not
an object is an error rather than something to salvage. There is deliberately no
free-text mode -- add one when something actually needs it.

The xAI path delegates to grok._chat rather than reimplementing it. That
function streams, which is not a style choice: a 20-50 scene completion under a
non-streamed read timeout throws away everything produced so far when it trips,
and that cost a full run at 120s. An arc is the same shape of request.
"""
import json
import os

import creds

# ORDER IS DELIBERATE, and this is the reason: xai first.
#
# An album arc for an R or XXX release is a story about adult material, and xAI
# generates that text without refusing it. OpenAI declines or quietly sanitises
# the same request, and for an arc the second is the worse one -- a sanitised
# arc is not an error anyone sees, it is thirty-one storyboards written against
# a story with the teeth taken out of it.
#
# Sorting this list alphabetically, or otherwise "tidying" it, silently moves
# every default-backend arc to the provider that will refuse the adult ones.
# Both are always selectable; this is only what you get when you choose nothing.
BACKENDS = ("xai", "openai")

OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_TIMEOUT = float(os.environ.get("STUDIO_OPENAI_TIMEOUT", 600))
# Last-resort fallback only. The model is read at CALL time from the same file
# the key came from (STUDIO_OPENAI_MODEL beside OPENAI_API_KEY), because the
# box that has the key is the box that knows which model that key can reach --
# and a name hard-coded here is a 404 some months from now on a machine nobody
# is watching. Never guess a model from memory: check what answers.
OPENAI_MODEL_FALLBACK = "gpt-4o"


def openai_model():
    return creds.setting("STUDIO_OPENAI_MODEL", "openai") or OPENAI_MODEL_FALLBACK


# Ids on /v1/models that are NOT chat-completions models. The dropdown must not
# offer one: a control that looks available and 404s is the failure this codebase
# refuses everywhere else.
#
# MEASURED 2026-08-12, and worth the specificity -- gpt-5.5-pro-2026-04-23 was
# what OpenAI itself recommended for this exact task when asked, and it answers
# "This is not a chat model and thus not supported in the v1/chat/completions
# endpoint" in 0.5s. The -pro line uses a different endpoint. Asking a model
# which model to use is not the same as checking that the answer works.
_OPENAI_NOT_CHAT = ("embedding", "whisper", "tts", "dall-e", "sora", "moderation",
                    "realtime", "audio", "image", "transcribe", "search", "instruct",
                    "computer-use", "-pro", "codex", "moderation")


def list_models(backend=None):
    """Chat models this backend will actually accept, newest-looking last.

    Empty rather than raising when the provider cannot be reached: a model
    dropdown that cannot be populated is a smaller problem than a page that
    will not render, and every caller already handles "no list" by using the
    default.
    """
    backend = resolve(backend)
    if backend == "xai":
        import grok
        try:
            return sorted(grok.usable_chat_models(grok.list_models()))
        except Exception:
            return []
    import httpx
    key = creds.get("openai")
    if not key:
        return []
    try:
        r = httpx.get(f"{OPENAI_BASE}/models",
                      headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return []
    return sorted(i for i in ids
                  if i.startswith("gpt-") and not any(x in i for x in _OPENAI_NOT_CHAT))


def available():
    """Backends that have a key right now, in preference order. Read at call
    time, so storing a key on the Config page takes effect immediately."""
    return [b for b in BACKENDS if creds.get(b)]


def resolve(backend=None):
    """The backend to use. An explicit one is honoured even if its key is
    missing, so the failure names the provider that was asked for rather than
    silently doing the request somewhere else -- a fallback that quietly changed
    provider would make the model field on a stored arc a lie."""
    if backend:
        if backend not in BACKENDS:
            raise ValueError(f"unknown backend {backend!r}; known: {', '.join(BACKENDS)}")
        return backend
    have = available()
    if not have:
        raise RuntimeError(
            "no chat backend has an API key. Set one on the Config page, or export "
            + " or ".join(creds.PROVIDERS[b]["env"] for b in BACKENDS))
    return have[0]


class Refused(RuntimeError):
    """The provider declined the request on content grounds.

    Its own type because it is not a bug and not an outage: it is one provider
    saying no to material another will write. The caller can name the backend
    that does not refuse instead of reporting a failure the operator cannot act
    on -- which for an ALBUM ARC is the difference between "try xAI" and
    "something went wrong".
    """


def _refusal_note(model, detail):
    return (f"{model} declined this request on content grounds. An album arc for an R or "
            f"XXX release is a story about adult material, and xAI does not refuse it -- "
            f"pick the xai backend for this album. The provider said: "
            f"{' '.join(str(detail).split())[:200]}")


def chat_json(system, user, backend=None, model=None, progress=None):
    """(parsed_json, "backend/model"). Raises on anything that is not an object."""
    backend = resolve(backend)
    if backend == "xai":
        import grok
        model = grok._resolve_model(model)
        raw = grok._chat(model, [{"role": "system", "content": system},
                                 {"role": "user", "content": user}], progress)
    else:
        model = model or openai_model()
        raw = _openai_chat(model, system, user, progress)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"{backend} did not return JSON: {str(raw)[:300]}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"{backend} returned {type(data).__name__}, expected an object")
    return data, f"{backend}/{model}"


def _openai_chat(model, system, user, progress=None):
    import httpx
    key = creds.get("openai")
    if not key:
        raise RuntimeError("no OpenAI API key. Set one on the Config page or export "
                           "OPENAI_API_KEY.")
    if progress:
        progress(f"asking OpenAI ({model})")
    r = httpx.post(
        f"{OPENAI_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              "response_format": {"type": "json_object"}},
        timeout=httpx.Timeout(OPENAI_TIMEOUT, connect=30.0))
    if r.status_code >= 400:
        # scrubbed: an error body can echo the request, and the request carries
        # the key in a header some proxies helpfully include
        body = r.text.replace(key, "<redacted>")
        if "content_policy" in body or "content policy" in body.lower():
            raise Refused(_refusal_note(model, body[:300]))
        raise RuntimeError(f"OpenAI {r.status_code}: {body[:500]}")
    try:
        msg = r.json()["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"OpenAI reply had no choices: {r.text[:300]}") from e
    # A REFUSAL is a 200 with content null and this field set. Read it, or the
    # failure reads as a parsing bug -- "reply had no message content" -- when
    # what actually happened is that the provider declined the album.
    if msg.get("refusal"):
        raise Refused(_refusal_note(model, msg["refusal"]))
    content = msg.get("content")
    if not content:
        raise RuntimeError(f"OpenAI returned an empty message: {r.text[:300]}")
    return content


def demo():
    import types
    # --- resolve: explicit wins, absent key is named, no key at all refuses ---
    real_get = creds.get
    have = {"xai": "", "openai": ""}
    creds.get = lambda name: have.get(name, "")
    try:
        try:
            resolve()
            raise AssertionError("a backend was chosen with no key anywhere")
        except RuntimeError as e:
            assert "Config page" in str(e), e
        have["openai"] = "sk-x"
        assert resolve() == "openai" and available() == ["openai"]
        have["xai"] = "sk-y"
        assert resolve() == "xai", "preference order changed"
        # explicit is honoured even when it is not the preferred one
        assert resolve("openai") == "openai"
        try:
            resolve("anthropic")
            raise AssertionError("an unknown backend was accepted")
        except ValueError:
            pass

        # --- chat_json parses, and refuses anything that is not an object ---
        import sys
        fake = types.ModuleType("grok")
        fake._resolve_model = lambda m: m or "grok-stub"
        replies = {"v": '{"premise": "ok"}'}
        fake._chat = lambda model, messages, progress=None: replies["v"]
        real_grok = sys.modules.get("grok")
        sys.modules["grok"] = fake
        try:
            data, used = chat_json("sys", "user", backend="xai")
            assert data == {"premise": "ok"} and used == "xai/grok-stub", (data, used)

            replies["v"] = "not json at all"
            try:
                chat_json("sys", "user", backend="xai")
                raise AssertionError("a non-JSON reply was accepted")
            except RuntimeError as e:
                assert "did not return JSON" in str(e), e

            replies["v"] = "[1, 2, 3]"
            try:
                chat_json("sys", "user", backend="xai")
                raise AssertionError("a JSON array was accepted where an object is required")
            except RuntimeError as e:
                assert "expected an object" in str(e), e
        finally:
            if real_grok is not None:
                sys.modules["grok"] = real_grok
            else:
                del sys.modules["grok"]
        # --- list_models offers only what the endpoint accepts ---
        import httpx
        real_httpx_get = httpx.get

        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"data": [{"id": i} for i in (
                    "gpt-5.6-sol", "gpt-5.5", "gpt-5.5-pro", "gpt-5.5-pro-2026-04-23",
                    "gpt-5.4-nano", "text-embedding-3-large", "whisper-1",
                    "gpt-4o-realtime-preview", "gpt-5-search-api", "dall-e-3")]}

        httpx.get = lambda *a, **k: _R()
        try:
            got = list_models("openai")
        finally:
            httpx.get = real_httpx_get
        assert "gpt-5.6-sol" in got and "gpt-5.5" in got, got
        # -pro is NOT a chat-completions model. Measured: gpt-5.5-pro-2026-04-23,
        # which OpenAI itself recommended for storyboard writing when asked,
        # answers "This is not a chat model" in 0.5s. Offering it in a dropdown
        # would be a control that looks available and 404s.
        assert not [g for g in got if "-pro" in g], got
        for junk in ("text-embedding-3-large", "whisper-1", "dall-e-3",
                     "gpt-4o-realtime-preview", "gpt-5-search-api"):
            assert junk not in got, f"{junk} was offered as a chat model"

        # --- a content refusal is its own outcome, not a parse failure ---
        # Both shapes OpenAI uses, neither of which can be triggered on demand
        # without generating the material they refuse. The distinction that
        # matters: an operator reading this must be told to switch backend, not
        # that the studio broke.
        have["openai"] = "sk-live"

        class _Refusal:
            status_code = 200
            text = "{}"
            def json(self):
                return {"choices": [{"message": {"content": None,
                                                 "refusal": "I can't help with that."}}]}

        class _PolicyError:
            status_code = 400
            text = '{"error": {"code": "content_policy_violation", "message": "declined"}}'

        real_post = httpx.post
        for resp, shape in ((_Refusal(), "a 200 with message.refusal"),
                            (_PolicyError(), "a 400 content_policy_violation")):
            httpx.post = lambda *a, _r=resp, **k: _r
            try:
                _openai_chat("gpt-test", "sys", "user")
                raise AssertionError(f"{shape} was not treated as a refusal")
            except Refused as e:
                assert "xai" in str(e), f"{shape}: the message must name the backend that "\
                                        f"does not refuse -- got {e}"
                assert "declined this request" in str(e), e
            finally:
                httpx.post = real_post

        # and an empty reply is still an ordinary failure, not a refusal
        class _Empty:
            status_code = 200
            text = "{}"
            def json(self):
                return {"choices": [{"message": {"content": ""}}]}
        httpx.post = lambda *a, **k: _Empty()
        try:
            _openai_chat("gpt-test", "sys", "user")
            raise AssertionError("an empty reply was accepted")
        except Refused:
            raise AssertionError("an empty reply was misreported as a content refusal")
        except RuntimeError as e:
            assert "empty message" in str(e), e
        finally:
            httpx.post = real_post
    finally:
        creds.get = real_get
    print("chat.py OK")


if __name__ == "__main__":
    demo()
