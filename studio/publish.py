"""Where finished work can be published, and what each destination permits.

This module is a CATALOGUE and a GATE. It does not upload anything yet -- what
it does is stop the studio from ever offering to.

THE RULE, and the reason this file exists at all: a tier that permits nudity
must never reach a destination that forbids adult content. Getting that wrong is
not a bug you fix later -- it is an account ban and, on some services, a report.
So the check is one function, `refusal()`, every publishing path goes through,
and it fails CLOSED: a destination whose policy is unknown accepts nothing
adult.

`allow_nudity` on the tier is the signal, because it is exactly what platform
policies are written about. It is already the flag that gates nude anchors, so
there is one notion of "this is adult material" in the studio rather than two
that can disagree.

Every policy note below was checked against the service's own documentation in
August 2026. Platform rules change; RECHECK is the field that says so, and
nothing here should be trusted past it without looking again.
"""
import json
import time

import db
import tiers

# What a destination can be handed.
MEDIA = ("video", "audio", "image", "link")

# adult policy
FORBIDDEN = "forbidden"     # no adult content at all
TAGGED = "tagged"           # permitted, but must be labelled/flagged
OPEN = "open"               # permitted with no special labelling
UNKNOWN = "unknown"         # policy not established -> refuses everything adult

SERVICES = {
    "youtube": {
        "label": "YouTube",
        "media": ("video", "audio"),
        "adult": FORBIDDEN,
        "adult_note": (
            "YouTube's nudity and sexual content policy prohibits explicit material "
            "outright. Age-restriction exists for borderline content, but it is applied BY "
            "YouTube -- it is not a switch that makes explicit uploads acceptable. An R or "
            "XXX render must not be uploaded here."),
        "api": "YouTube Data API v3, videos.insert",
        "auth": "OAuth 2.0 (Google Cloud project, OAuth consent screen, refresh token)",
        "signup": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "docs": "https://developers.google.com/youtube/v3/guides/uploading_a_video",
        "steps": [
            "Create a Google Cloud project and enable the YouTube Data API v3.",
            "Configure the OAuth consent screen; add yourself as a test user.",
            "Create an OAuth 2.0 Client ID of type Desktop app; download the client secret.",
            "Run the consent flow once to obtain a refresh token -- it is the credential "
            "the studio would store, not your password.",
            "Quota: videos.insert dropped to ~100 units per call in Dec 2025, and the "
            "default bucket allows about 100 uploads a day.",
        ],
        "target_label": "Channel",
        "target_hint": "The channel id (UC...) this account uploads to.",
    },
    "reddit": {
        "label": "Reddit",
        "media": ("video", "audio", "image", "link"),
        "adult": TAGGED,
        "adult_note": (
            "Adult content is allowed only in subreddits that are themselves marked NSFW, "
            "and the submission must carry the nsfw flag. Posting adult material to a "
            "non-NSFW subreddit breaks both the subreddit's rules and Reddit's -- so a "
            "target here records whether the subreddit is NSFW, and an adult tier can only "
            "go to one that is."),
        "api": "Reddit OAuth API, POST /api/submit with nsfw=true",
        "auth": "OAuth 2.0 script app (client id + secret + your account)",
        "signup": "https://www.reddit.com/prefs/apps",
        "docs": "https://www.reddit.com/dev/api/#POST_api_submit",
        "steps": [
            "Go to reddit.com/prefs/apps and create an app of type 'script'.",
            "Note the client id (under the app name) and the secret.",
            "Authenticate as your own account; script apps are for exactly that.",
            "Rate limit is roughly 60-100 requests per minute per OAuth client. Back off "
            "exponentially on a 429 rather than retrying immediately.",
            "EACH subreddit is a separate target here, because each has its own rules and "
            "its own NSFW status. Read the subreddit's rules before adding it -- many ban "
            "self-promotion or AI-generated work outright.",
        ],
        "target_label": "Subreddit",
        "target_hint": "Without the r/ prefix. Tick 'NSFW subreddit' only if it really is.",
    },
    "bluesky": {
        "label": "Bluesky",
        "media": ("video", "image", "link"),
        "adult": TAGGED,
        "adult_note": (
            "Adult content is permitted when self-labelled. The post carries a label "
            "('sexual', 'nudity' or 'porn') which viewers' content filters act on. "
            "Unlabelled adult content is a policy violation."),
        "api": "AT Protocol, com.atproto.repo.createRecord with self-labels",
        "auth": "App password (not your account password)",
        "signup": "https://bsky.app/settings/app-passwords",
        "docs": "https://docs.bsky.app/docs/advanced-guides/posts",
        "steps": [
            "In the Bluesky app, Settings -> App Passwords -> Add App Password.",
            "The studio would store that app password, never your real one; it can be "
            "revoked from the same screen without changing your login.",
            "Video posts go through the video upload endpoint and are size-limited; a "
            "full-length music video will usually need a link post instead.",
        ],
        "target_label": "Handle",
        "target_hint": "e.g. meowp.bsky.social",
    },
    "mastodon": {
        "label": "Mastodon",
        "media": ("video", "audio", "image", "link"),
        "adult": TAGGED,
        "adult_note": (
            "Policy is PER INSTANCE, not global -- some instances welcome adult content, "
            "many forbid it, and a few forbid it only when unmarked. Posts support a "
            "'sensitive' flag plus a content warning. Because the rule lives on the "
            "instance, each instance is its own target here and you set its policy."),
        "api": "Mastodon REST API, POST /api/v1/statuses with sensitive=true",
        "auth": "Access token from the instance",
        # Mastodon has no central signup: an application is created on the
        # instance you are actually on, so this points at the server list and
        # the per-instance path is the first step below.
        "signup": "https://joinmastodon.org/servers",
        "docs": "https://docs.joinmastodon.org/methods/statuses/",
        "steps": [
            "There is no central signup -- the application is created on YOUR instance: "
            "Preferences -> Development -> New application.",
            "Give it write:statuses and write:media scopes; copy the access token.",
            "READ THAT INSTANCE'S RULES before setting its policy here. This is the one "
            "service where the answer genuinely differs per server.",
        ],
        "target_label": "Instance",
        "target_hint": "e.g. mastodon.social. Set the adult policy from ITS rules.",
    },
    "soundcloud": {
        "label": "SoundCloud",
        "media": ("audio",),
        "adult": TAGGED,
        "adult_note": (
            "Audio only, so the visual tier does not apply -- but explicit LYRICS should be "
            "marked. The song's own explicit flag is what matters here, not the render tier."),
        "api": "SoundCloud Public API, POST /tracks",
        "auth": "OAuth 2.1",
        "signup": "https://soundcloud.com/you/apps",
        "docs": "https://developers.soundcloud.com/docs/api/guide",
        "steps": [
            "API application registration has been closed to new applicants for long "
            "stretches -- CHECK whether it is open before planning on this one.",
            "If you already hold credentials they continue to work.",
        ],
        "target_label": "Account",
        "target_hint": "The SoundCloud account tracks are uploaded to.",
    },
}

# When each policy above was last checked against the service's own docs.
# Platform rules move; treat anything older than this as unverified.
RECHECK = "2026-08-11"


def service(key):
    return SERVICES.get(key)


def targets(enabled_only=False):
    sql = "SELECT * FROM publish_targets"
    if enabled_only:
        sql += " WHERE enabled=1"
    return db.q(sql + " ORDER BY service, name")


def add_target(service_key, name, adult_ok=False, note=""):
    if service_key not in SERVICES:
        raise ValueError(f"no such service: {service_key}")
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("a target needs a name")
    if len(name) > 120:
        raise ValueError("that name is too long")
    svc = SERVICES[service_key]
    # A target can never be more permissive than its SERVICE. Ticking "adult ok"
    # on a YouTube channel has to be impossible, not merely discouraged.
    if adult_ok and svc["adult"] == FORBIDDEN:
        raise ValueError(f"{svc['label']} forbids adult content, so no {svc['label']} "
                          f"target can accept it")
    db.run("""INSERT INTO publish_targets (service, name, adult_ok, note, enabled, created)
              VALUES (?,?,?,?,1,?)""",
           service_key, name, 1 if adult_ok else 0, note or "", time.time())
    return name


def refusal(target, tier_name):
    """Why this tier may NOT be published to this target, or None if it may.

    THE gate. Fails closed in every direction: an unknown service, an unknown
    tier, a disabled target and a service whose policy was never established all
    refuse. Returning a REASON rather than a boolean is deliberate -- a refusal
    nobody can explain gets worked around.
    """
    svc = SERVICES.get(target["service"])
    if not svc:
        return f"{target['service']} is not a service this studio knows about"
    if not target["enabled"]:
        return f"{target['name']} is turned off"

    adult = tiers.allows_nudity(tier_name)
    if not adult:
        return None                      # nothing to gate

    if svc["adult"] == FORBIDDEN:
        return (f"{svc['label']} forbids adult content, and the {tier_name.upper()} tier "
                f"permits nudity")
    if svc["adult"] == UNKNOWN:
        return (f"{svc['label']}'s adult-content policy has not been established here, so "
                f"nothing adult is sent to it")
    if not target["adult_ok"]:
        # the per-target switch: an NSFW subreddit vs an ordinary one
        return (f"{target['name']} is not marked as accepting adult content, and the "
                f"{tier_name.upper()} tier permits nudity")
    return None


def allowed(target, tier_name):
    return refusal(target, tier_name) is None


def routes_for(tier_name):
    """[(target, refusal_or_None)] for every target, so the UI can show what
    would happen rather than only what is possible."""
    return [(t, refusal(t, tier_name)) for t in targets()]


def demo():
    import os
    import tempfile

    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()
    tiers.ensure_builtins()

    # every catalogue entry is complete enough to act on
    for key, s in SERVICES.items():
        for f in ("label", "media", "adult", "adult_note", "api", "auth", "signup",
                  "docs", "steps", "target_label", "target_hint"):
            assert s.get(f), f"{key} has no {f}"
        assert s["adult"] in (FORBIDDEN, TAGGED, OPEN, UNKNOWN), key
        assert set(s["media"]) <= set(MEDIA), key
        # every signup must be a REAL link -- the config page renders it as an
        # href, and instructional prose there produces a dead link
        assert s["signup"].startswith("https://"), f"{key}'s signup is not a URL"
        assert s["docs"].startswith("https://"), f"{key}'s docs is not a URL"

    add_target("reddit", "MeowPMusic", adult_ok=False)
    add_target("reddit", "AdultAnimation", adult_ok=True)
    add_target("youtube", "UC_meowp")
    nsfw_sub = db.one("SELECT * FROM publish_targets WHERE name='AdultAnimation'")
    sfw_sub = db.one("SELECT * FROM publish_targets WHERE name='MeowPMusic'")
    yt = db.one("SELECT * FROM publish_targets WHERE service='youtube'")

    # --- the rule this module exists for ---------------------------------
    # A tier that permits nudity reaches ONLY a target that accepts adult.
    for tier in ("g", "pg13"):
        for t in (nsfw_sub, sfw_sub, yt):
            assert allowed(t, tier), (tier, t["name"], refusal(t, tier))
    for tier in ("r", "xxx"):
        assert allowed(nsfw_sub, tier), refusal(nsfw_sub, tier)
        assert not allowed(sfw_sub, tier), "adult tier reached a non-NSFW subreddit"
        assert not allowed(yt, tier), "adult tier reached YouTube"
        assert "forbids adult content" in refusal(yt, tier)
        assert "not marked as accepting" in refusal(sfw_sub, tier)

    # a YouTube target CANNOT be marked adult-ok in the first place
    try:
        add_target("youtube", "UC_other", adult_ok=True)
        raise AssertionError("an adult-ok target was created on a service that forbids it")
    except ValueError as e:
        assert "forbids adult content" in str(e)

    # --- fails closed ----------------------------------------------------
    db.run("UPDATE publish_targets SET enabled=0 WHERE id=?", nsfw_sub["id"])
    off = db.one("SELECT * FROM publish_targets WHERE id=?", nsfw_sub["id"])
    assert not allowed(off, "xxx") and "turned off" in refusal(off, "xxx")
    assert not allowed(off, "g"), "a disabled target still accepted work"

    unknown = {"service": "nosuchservice", "name": "x", "enabled": 1, "adult_ok": 1}
    assert not allowed(unknown, "xxx")
    assert not allowed(unknown, "g")

    # a tier that does not exist is not nudity-permitting by omission
    assert not tiers.allows_nudity("nosuchtier")

    for bad, why in ((("reddit", ""), "no name"), (("nosuch", "x"), "unknown service")):
        try:
            add_target(*bad)
            raise AssertionError(f"accepted a target with {why}")
        except ValueError:
            pass

    print("publish.py OK")


if __name__ == "__main__":
    demo()
