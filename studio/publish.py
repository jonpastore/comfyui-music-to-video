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
    "x": {
        "label": "X (Twitter)",
        "media": ("video", "image", "link"),
        "adult": TAGGED,
        "adult_note": (
            "The only mainstream destination here that permits explicit material, and the "
            "one with the most conditions attached. The posting account must be enrolled in "
            "the Adult Content Creator programme (verified ID), the account's own 'sensitive "
            "media' setting must be on, and every post must carry the right one of three "
            "labels: Sensitive, Adult or Explicit. Since Feb 2026 AI-GENERATED adult content "
            "must ALSO carry an AI-content disclosure label -- which is everything this "
            "studio produces, so that label is not optional for us."),
        "api": "X API v2, POST /2/media/upload (INIT/APPEND/FINALIZE) then POST /2/tweets",
        "auth": "OAuth 2.0 with PKCE, user context",
        "signup": "https://developer.x.com/en/portal/dashboard",
        "docs": "https://docs.x.com/x-api/media/quickstart/media-upload-chunked",
        "steps": [
            "Video upload is CHUNKED: init, append segments under 5 MB, finalize, then poll "
            "processing before the media_id can be attached to a post.",
            "Enrol the account in the Adult Content Creator programme before posting anything "
            "from an adult tier; without it the correct label is not even available.",
            "This is the one PAID API here. Since Feb 2026 new developers land on pay-per-use "
            "(about $0.01 a post); the old Basic/Pro tiers are closed to new signups.",
        ],
        "target_label": "Account",
        "target_hint": "The @handle posts go to. Tick adult only if it is ACC-enrolled.",
    },
    "tiktok": {
        "label": "TikTok",
        "media": ("video",),
        "adult": FORBIDDEN,
        "adult_note": (
            "Sexually explicit content is prohibited, and TikTok moderates far more "
            "aggressively than its written policy implies. Nothing above the clean tiers "
            "should be pointed at it."),
        "api": "TikTok Content Posting API, /v2/post/publish/video/init/",
        "auth": "OAuth 2.0 (TikTok for Developers app, video.publish scope)",
        "signup": "https://developers.tiktok.com/",
        "docs": "https://developers.tiktok.com/doc/content-sharing-guidelines",
        "steps": [
            "An UNAUDITED app can only post SELF_ONLY (private), to at most 5 users per 24 "
            "hours, and the account must itself be private at the time. Public posting needs "
            "the app to pass TikTok's audit -- plan for that, it is not a formality.",
            "The API requires the posting UI to show a preview and take explicit consent "
            "before upload, and to collect the commercial-content disclosure. An uploader "
            "that silently posts does not meet their terms.",
            "Vertical video only, in practice. A 16:9 music video will be letterboxed.",
        ],
        "target_label": "Account",
        "target_hint": "The TikTok account videos are posted to.",
    },
    "vimeo": {
        "label": "Vimeo",
        "media": ("video",),
        "adult": TAGGED,
        "adult_note": (
            "Pornography and sexually explicit content are prohibited, but non-sexual nudity "
            "and sexuality with a clear creative or narrative purpose ARE allowed when the "
            "video is rated correctly. So an R render can go here rated mature; an XXX one "
            "cannot go here at all. THE STUDIO CANNOT TELL THOSE APART -- adult_ok is a "
            "single switch and tiers are not ranked -- so ticking it on a Vimeo target trusts "
            "you to keep explicit renders off it."),
        "api": "Vimeo API, POST /me/videos with tus resumable upload",
        "auth": "OAuth 2.0, personal access token with upload scope",
        "signup": "https://developer.vimeo.com/apps",
        "docs": "https://developer.vimeo.com/api/upload/videos",
        "steps": [
            "Upload access is not granted by default: request it on the app, and it is "
            "reviewed. A free account also has a weekly upload quota.",
            "Set the content rating on the video (nudity / drugs / language / violence) at "
            "upload. An unrated video that needs a rating is a guidelines violation, not a "
            "detail -- this is the switch that makes an R render acceptable here.",
        ],
        "target_label": "Account",
        "target_hint": "The Vimeo account videos are uploaded to.",
    },
    "dailymotion": {
        "label": "Dailymotion",
        "media": ("video",),
        "adult": FORBIDDEN,
        "adult_note": (
            "Pornographic and sexually explicit content is prohibited outright. There is a "
            "sensitive-content restriction for borderline material, applied BY Dailymotion, "
            "and it is not a switch that makes explicit uploads acceptable."),
        "api": "Dailymotion Data API, POST /me/videos",
        "auth": "OAuth 2.0 (API key + secret)",
        "signup": "https://www.dailymotion.com/partner/developer",
        "docs": "https://developers.dailymotion.com/api/platform-api/reference/",
        "steps": [
            "Create an API key in the partner space; upload needs the 'manage_videos' scope.",
            "Upload is two steps: GET an upload URL from /file/upload, PUT the file to it, "
            "then create the video from the returned url.",
        ],
        "target_label": "Channel",
        "target_hint": "The Dailymotion channel videos are uploaded to.",
    },
    "odysee": {
        "label": "Odysee",
        "media": ("video", "audio"),
        "adult": FORBIDDEN,
        "adult_note": (
            "Worth stating because its reputation says otherwise: Odysee's community "
            "guidelines prohibit pornographic material. NSFW content generally must be "
            "tagged mature and is then unlisted, but explicit material is not permitted at "
            "all, so this fails closed like the rest."),
        "api": "LBRY SDK (lbrynet) publish -- Odysee is a front end to the LBRY network",
        "auth": "A local lbrynet daemon holding your channel's key",
        "signup": "https://odysee.com/$/signup",
        "docs": "https://lbry.tech/api/sdk",
        "steps": [
            "There is no simple upload REST endpoint: publishing means running lbrynet "
            "locally and calling its publish method with your channel's claim.",
            "That daemon holds a wallet key. Treat it like a credential, not a config file.",
            "The heaviest lift of any destination here -- take it last, if at all.",
        ],
        "target_label": "Channel",
        "target_hint": "The @channel name claims are published under.",
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
