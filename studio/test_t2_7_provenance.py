"""T2-7: a version records the asked model and a timestamp during the call.

docs/TRD-2 §3.3: fields that merely exist can hold anything. The recorded
model must equal the model that was ASKED for, and created must lie
between the call's start and end.

Mutation: store a dummy/static model or timestamp independent of the
generation call → red.
"""
import time
from unittest.mock import patch

import arc
import prompts


ASKED = "asked-model-t2-7"


def _songs():
    return [{"id": 1, "title": "Track 1", "lyrics": "lyrics 1"},
            {"id": 2, "title": "Track 2", "lyrics": "lyrics 2"}]


def _raw():
    return {
        "premise": "A cat crosses a city and does not come back the same.",
        "acts": [{"name": "Leaving", "songs": [1, 2],
                  "turn": "she stops looking back"}],
        "songs": [{"song_id": 1, "position": 1, "role": "role 1",
                   "beat": "beat 1", "opens": "opens 1", "closes": "closes 1"},
                  {"song_id": 2, "position": 2, "role": "role 2",
                   "beat": "beat 2", "opens": "opens 2", "closes": "closes 2"}],
        "continuity": ["the collar is always brass"],
    }


def test_t2_7_version_records_asked_model_and_call_time():
    raw = _raw()

    def fake_chat_json(system, user, **kw):
        assert kw.get("model") == ASKED
        return raw, "xai/some-other-model"

    started = time.time()
    with patch.object(arc.chat, "chat_json", fake_chat_json):
        data, used = arc.generate(
            "Provenance Album", _songs(),
            direction="colder than it started",
            model=ASKED)
    ended = time.time()

    assert data["premise"] == raw["premise"]
    row = prompts.latest("Provenance Album", "arc")
    assert row is not None, "generate wrote no version"
    assert row["model"] == ASKED, row["model"]
    assert started <= row["created"] <= ended, (started, row["created"], ended)
