#!/usr/bin/env python3
"""Watch every render backend and say something when one changes state.

WHY THIS DOES NOT ASK SWARMUI. Two reasons, both measured on 2026-08-12.

1. SwarmUI cannot see a job posted straight to a backend's ComfyUI. Its
   GetCurrentStatus reported `live_gens: 0` while cerberus's own /queue had
   `running: 1` -- a real 3025-frame render, submitted direct because that is
   how an OOM comes back readable (clipmax/clip_max.py says so in its docstring).
   A monitor built on Swarm's view would have called that box idle.
2. A backend can be registered, listed, and hold nothing. Backend 1 was
   "running" and empty on 2026-08-12 and failed a real workflow in 0.6s.

So this asks each ComfyUI directly -- the same endpoint SwarmUI's own idle
monitor uses -- and reports what the box says about itself.

WHAT IT DELIBERATELY DOES NOT DO: touch SwarmUI. It does not need to. SwarmUI's
NetworkBackendUtils.IdleMonitor re-validates every 5 seconds and flips a backend
IDLE<->RUNNING on its own, so a box that comes back rejoins without help. And the
APIs a watchdog would want -- ToggleBackend, EditBackend, RestartBackends -- are
all behind --lock_settings, which is the only thing between an unauthenticated
SwarmUI and every visitor on the tailnet being `local` admin. Alerting is worth
having; unlocking that to automate it is not.

Run:  python3 fleet_watch.py            # one pass, print, alert on change
      python3 fleet_watch.py --loop 60  # keep watching
      python3 fleet_watch.py --demo     # self-check, no network
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import creds

# host -> label. Kept here rather than read from SwarmUI because the point is to
# notice when SwarmUI's view and the boxes disagree, and a monitor that learns
# the fleet FROM the thing it is checking cannot do that. models.BACKEND_STABILITY
# keys by host for the same reason.
# TAILNET ADDRESSES, not 127.0.0.1, even for the box the studio runs on. SwarmUI
# registers cerberus as http://127.0.0.1:8188 and that resolves ONLY from
# cerberus -- which is exactly why models.by_backend() reports backend 0 as
# unreachable from anywhere else, and why models.where() silently returned "no
# box can run this" earlier today. A monitor that can only be run on one machine
# is a monitor nobody runs; this one works from any box on the tailnet.
FLEET = {
    "100.103.148.120:8188": "cerberus RTX 5090 (studio)",
    "100.107.235.105:8188": "gamingpc RTX 5090",
    "100.95.184.29:8188": "peaches RTX 2080 Ti",
    "100.111.252.15:8188": "ethan RTX 5080 (WSL2)",
}

STATE_PATH = os.environ.get(
    "FLEET_WATCH_STATE",
    os.path.join(os.environ.get("STUDIO_DATA",
                                os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")),
                 "fleet_watch.json"))
TIMEOUT = float(os.environ.get("FLEET_WATCH_TIMEOUT", 8))
# Meta key in the state file (no "up" — transitions() skips it). Holds the
# last alert delivery outcome so an unreachable transport degrades to a
# recorded state change, never to silence (T9-17).
ALERT_KEY = "_alert"


def probe(hostport, timeout=TIMEOUT):
    """(up, detail). `features` is what SwarmUI's own idle monitor calls, so a
    box this says is up is a box SwarmUI will also accept within ~5 seconds."""
    try:
        with urllib.request.urlopen(f"http://{hostport}/system_stats", timeout=timeout) as r:
            s = json.loads(r.read())
    except Exception as e:                      # noqa: BLE001 -- any failure is "down"
        return False, f"{type(e).__name__}"
    dev = (s.get("devices") or [{}])[0]
    total = dev.get("vram_total") or 0
    free = dev.get("vram_free") or 0
    name = (dev.get("name") or "?").split(":")[0].strip()
    return True, f"{name}, {free / 2**30:.1f}/{total / 2**30:.1f} GiB free"


def busy(hostport, timeout=TIMEOUT):
    """Jobs the BOX knows about, including ones SwarmUI never saw."""
    try:
        with urllib.request.urlopen(f"http://{hostport}/queue", timeout=timeout) as r:
            q = json.loads(r.read())
        return len(q.get("queue_running") or []), len(q.get("queue_pending") or [])
    except Exception:                           # noqa: BLE001
        return None, None


def scan(fleet=None):
    out = {}
    for hostport, label in (fleet or FLEET).items():
        up, detail = probe(hostport)
        running, pending = busy(hostport) if up else (None, None)
        out[hostport] = {"label": label, "up": up, "detail": detail,
                         "running": running, "pending": pending}
    return out


def load_state(path=None):
    try:
        with open(path or STATE_PATH) as f:
            return json.load(f)
    except Exception:                           # noqa: BLE001 -- first run
        return {}


def save_state(state, path=None):
    path = path or STATE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)                       # atomic: a killed watcher never
                                                # leaves a half-written state that
                                                # reads as "everything changed"


def transitions(before, now):
    """Only CHANGES, and only ones we have a previous reading for.

    A first run must not announce four boxes as newly up -- that is noise on
    every restart of the watcher, and noise is how an alert channel gets muted,
    which costs more than the alert was worth.
    """
    out = []
    for hostport, cur in sorted(now.items()):
        was = before.get(hostport)
        if not was or "up" not in was:
            continue
        if bool(was["up"]) != bool(cur["up"]):
            out.append((hostport, cur["label"], cur["up"], cur["detail"]))
    return out


def notify(lines, webhook=None):
    """Post to Slack. Returns True if it went, False if there is no webhook.

    The URL is read through creds.get and never passed in as an argument: a
    webhook is a bearer secret and an argument shows up in `ps` and in shell
    history.
    """
    # None means "look it up"; an explicit "" means "there is no webhook". They
    # were the same thing via `webhook or creds.get(...)`, and the cost was that
    # demo()'s no-webhook case fell through to the REAL webhook and posted the
    # test string to the live channel. A self-check must not be able to message
    # anybody.
    hook = creds.get("slack_webhook") if webhook is None else webhook
    if not hook:
        return False
    body = json.dumps({"text": "\n".join(lines)}).encode()
    req = urllib.request.Request(hook, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode().strip() == "ok"


def render(now):
    rows = []
    for hostport, s in sorted(now.items()):
        mark = "UP  " if s["up"] else "DOWN"
        q = ("" if s["running"] is None
             else f"  queue {s['running']}r/{s['pending']}p")
        rows.append(f"  {mark} {s['label']:24s} {s['detail']}{q}")
    return rows


def once(state_path=None, webhook=None, quiet=False):
    before = load_state(state_path)
    now = scan()
    changed = transitions(before, now)
    if not quiet:
        print(time.strftime("%H:%M:%S"), "fleet:")
        print("\n".join(render(now)))
    # Host readings always land; ALERT_KEY records whether the transport
    # delivered. An unreachable transport degrades to that record, never to
    # silence (T9-17). No-change polls keep the last alert outcome.
    out = dict(now)
    if ALERT_KEY in before:
        out[ALERT_KEY] = before[ALERT_KEY]
    if changed:
        lines = []
        for _hostport, label, up, detail in changed:
            lines.append(f"{'🟢 ONLINE' if up else '🔴 OFFLINE'}  *{label}*  — {detail}")
        lines.append("_meowp-studio fleet_watch_")
        try:
            sent = notify(lines, webhook)
            if sent:
                out[ALERT_KEY] = {"delivered": True, "ts": time.time(),
                                  "lines": lines}
            else:
                # No webhook is still not silence: the change is on disk.
                out[ALERT_KEY] = {"delivered": False, "reason": "no_webhook",
                                  "ts": time.time(), "lines": lines}
            if not quiet:
                print("  alert:", "sent" if sent else "NO WEBHOOK CONFIGURED")
        except Exception as e:                  # noqa: BLE001
            # An alert that fails must not stop the watching, and must not be
            # silent about failing either. The undelivered record is the
            # durable half; stderr is the live half.
            out[ALERT_KEY] = {
                "delivered": False,
                "reason": f"{type(e).__name__}: {e}",
                "ts": time.time(),
                "lines": lines,
            }
            print(f"  alert FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    save_state(out, state_path)
    return now, changed


def demo():
    import tempfile
    # transitions: first reading is never an alert, a flip is
    a = {"h": {"label": "box", "up": True, "detail": "x", "running": 0, "pending": 0}}
    b = {"h": {"label": "box", "up": False, "detail": "URLError", "running": None,
               "pending": None}}
    assert transitions({}, a) == [], "a first run alerted; every restart would spam"
    assert transitions(a, a) == [], "an unchanged box alerted"
    # THE ANTI-FLOOD RULE, stated as a loop rather than a single call: a box that
    # stays down through many scans must alert ONCE, on the edge. A monitor that
    # re-alerts every interval is a monitor whose channel gets muted, and a muted
    # channel is worse than no channel -- it looks like coverage and is not.
    fired, state = 0, a
    for _ in range(20):                         # 20 intervals, box down for 19
        nxt = b if state is not a or fired else b
        fired += len(transitions(state, nxt))
        state = nxt
    assert fired == 1, f"a box down for 20 scans alerted {fired} times"
    # and it must alert again when it genuinely comes back
    assert len(transitions(state, a)) == 1, "the recovery after a long outage was missed"
    assert [t[2] for t in transitions(a, b)] == [False], transitions(a, b)
    assert [t[2] for t in transitions(b, a)] == [True], transitions(b, a)
    # a box we have never seen before appearing mid-run is also not an alert,
    # because "new" is not "came back"
    two = dict(a, other={"label": "n", "up": True, "detail": "", "running": 0, "pending": 0})
    assert transitions(a, two) == [], "a newly ADDED box announced itself as recovered"

    # state survives a round trip and is written atomically
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        save_state(a, p)
        assert load_state(p) == a
        assert not os.path.exists(p + ".tmp"), "left a temp file behind"
        # unreadable state is a first run, not a crash
        open(p, "w").write("{not json")
        assert load_state(p) == {}

    # no webhook configured is a FALSE, not an exception: the watcher keeps
    # watching on a box where the secret was never stored
    assert notify(["x"], webhook="") is False

    # a down box reports no queue rather than zero, because zero is a claim
    up, detail = probe("127.0.0.1:1", timeout=0.4)
    assert up is False and "Error" in detail, (up, detail)
    assert busy("127.0.0.1:1", timeout=0.4) == (None, None)
    print("fleet_watch.py OK")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    elif "--loop" in sys.argv:
        every = float(sys.argv[sys.argv.index("--loop") + 1])
        while True:
            try:
                once()
            except Exception as e:              # noqa: BLE001 -- a watcher that
                print(f"scan failed: {e}", file=sys.stderr)   # dies is worse than
            time.sleep(every)                   # one that misses a scan
    else:
        once()
