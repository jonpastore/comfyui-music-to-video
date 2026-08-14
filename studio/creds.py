"""The one way anything in this studio reads a secret.

ALBUM_ARC_AND_STAGING_PLAN.md section 5. The decision recorded there was: store
keys now, add authentication later, accepting that anyone who can reach port
8000 can use them until then. `deploy.sh` now binds the studio to the tailscale
IP alone, which is the cheap mitigation that plan named.

Be honest about what the encryption buys. It protects the SQLITE FILE -- which
gets copied, backed up and synced -- because the key lives outside the data
directory. It does NOT protect against someone who can already read the
filesystem as the service user, and it does not protect against someone reaching
the unauthenticated port. Anything else would be a claim this design cannot
support.

Precedence is env, then file, then the store. An existing environment or config
file key WINS over a stored one, so nothing that works today starts depending on
the database, and a key exported for a one-off run still overrides.

The interface is the point. `creds.get(name)` is the only way a secret is read,
so HashiCorp Vault becomes a backend behind this one function when multiuser
arrives -- a swap, not a rewrite. Recorded as a future requirement: multiuser
implies Vault AND authentication on the studio itself, because multiuser without
auth is not a smaller version of this feature, it is a different and worse one.
"""
import os
import stat
import time

import db

# name -> (environment variable, optional KEY=VALUE file that also carries it).
# The file entry is how grok.py has always read the xAI key; keeping it here
# means adding a provider does not mean inventing a new lookup convention.
PROVIDERS = {
    "xai": {"label": "xAI (Grok)", "env": "XAI_API_KEY",
            "file": os.path.expanduser("~/.config/morpheus/grok-mcp.env"),
            "note": "storyboards, mix suggestions and the album arc"},
    "openai": {"label": "OpenAI", "env": "OPENAI_API_KEY",
               "file": os.path.expanduser("~/.config/morpheus/openai.env"),
               "note": "second album-arc backend"},
    # A webhook URL is a BEARER secret: anyone holding it can post to the channel,
    # there is no second factor, and it cannot be scoped. So it goes through the
    # same door as the API keys rather than into a config file in the repo --
    # which is also why fleet_watch.py reads it via creds.get and never takes it
    # as an argument that would end up in a process list or a shell history.
    "slack_webhook": {"label": "Slack incoming webhook", "env": "SLACK_WEBHOOK_URL",
                      "file": os.path.expanduser("~/.config/meowp-studio/slack.env"),
                      "note": "fleet_watch backend up/down alerts"},
}

# A plain KEY=VALUE file for anything not covered above, searched for every
# provider. Outside the repo on purpose -- a .env inside it would be rsynced to
# the render box by deploy.sh and is one `git add -A` away from being committed,
# which is why .gitignore carries it as well as belt and braces.
ENV_FILE = os.environ.get("STUDIO_ENV_FILE",
                          os.path.expanduser("~/.config/meowp-studio/.env"))

# Outside db.DATA on purpose: the whole point is that a copy of the database is
# useless without it. STUDIO_CRED_KEY moves it for a deployment that keeps
# secrets somewhere specific.
KEY_PATH = os.environ.get(
    "STUDIO_CRED_KEY", os.path.expanduser("~/.config/meowp-studio/cred.key"))


class Unavailable(RuntimeError):
    """Encryption is not available, so a secret CANNOT be stored.

    Deliberately fatal for a write and harmless for a read: a studio without the
    library keeps working exactly as it does today on env and file keys, and
    refuses to accept a new secret rather than writing one in plaintext. Storing
    a key unencrypted because a dependency is missing is the kind of silent
    downgrade this codebase refuses everywhere else.
    """


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise Unavailable(
            "the `cryptography` package is not installed, so a key cannot be stored "
            "encrypted -- and this refuses to store one any other way. Add it to "
            "studio/requirements.txt and redeploy, or keep using the environment "
            "variable, which still works and still wins.") from e
    return Fernet(_key(Fernet))


def _key(Fernet):
    """The encryption key, generated on first use, readable only by this user."""
    if os.path.isfile(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(KEY_PATH) or ".", exist_ok=True)
    key = Fernet.generate_key()
    # 0600 BEFORE the bytes land: creating it world-readable and chmod-ing
    # afterwards leaves a window in which the key is readable, and on a box that
    # syncs home directories that window is enough.
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def _from_file(path, env_name):
    if not path:
        return ""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{env_name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def get(name):
    """The secret for `name`, or "" -- never raises, and never logs the value.

    Read at CALL time, never at import, matching how grok.py has always read the
    xAI key: a rotated key takes effect without restarting the service.
    """
    p = PROVIDERS.get(name)
    if not p:
        return ""
    value = (os.environ.get(p["env"])
             or _from_file(p.get("file"), p["env"])
             or _from_file(ENV_FILE, p["env"]))
    if value:
        return value
    row = db.one("SELECT ciphertext FROM credentials WHERE name=?", name)
    if not row or not row["ciphertext"]:
        return ""
    try:
        return _fernet().decrypt(row["ciphertext"]).decode()
    except Exception:
        # a key file that has been replaced or lost. Not fatal: the caller is
        # told there is no secret, and the config page still says one is stored,
        # which is the truthful pair of statements.
        return ""


def setting(env_name, provider=None):
    """A NON-secret setting -- a model name, a base URL -- read with the same
    precedence as a key, from the same files.

    Separate from get() on purpose: this one is safe to render, log and put in
    an error message, and keeping the two apart is what stops a value that is
    printable today becoming a secret that leaks tomorrow.
    """
    value = os.environ.get(env_name)
    if value:
        return value
    paths = [ENV_FILE]
    if provider and PROVIDERS.get(provider, {}).get("file"):
        paths.insert(0, PROVIDERS[provider]["file"])
    for path in paths:
        value = _from_file(path, env_name)
        if value:
            return value
    return ""


def put(name, value):
    """Store (or replace) a secret. Raises Unavailable if it cannot be encrypted."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown credential {name!r}")
    value = (value or "").strip()
    if not value:
        raise ValueError("empty value -- use clear() to remove a credential")
    blob = _fernet().encrypt(value.encode())
    now = time.time()
    if db.one("SELECT id FROM credentials WHERE name=?", name):
        db.run("UPDATE credentials SET ciphertext=?, updated=? WHERE name=?", blob, now, name)
    else:
        db.run("INSERT INTO credentials (name, ciphertext, created, updated) VALUES (?,?,?,?)",
               name, blob, now, now)


def clear(name):
    db.run("DELETE FROM credentials WHERE name=?", name)


def status():
    """What the config page renders. Never the value -- only whether there is
    one, where it came from, and when it was last written.

    A secret that is never rendered cannot be shoulder-surfed out of a page that
    has no login, which is the whole reason this is write-only in the UI.
    """
    stored = {r["name"]: r for r in db.q("SELECT name, updated FROM credentials")}
    out = []
    for name, p in PROVIDERS.items():
        env = bool(os.environ.get(p["env"]))
        in_file = ""
        if not env:
            for path in (p.get("file"), ENV_FILE):
                if _from_file(path, p["env"]):
                    in_file = path
                    break
        row = stored.get(name)
        if env:
            source = f"environment ({p['env']})"
        elif in_file:
            source = f"file ({in_file})"
        elif row:
            source = "stored here, encrypted"
        else:
            source = ""
        out.append({"name": name, "label": p["label"], "note": p["note"],
                    "env": p["env"], "source": source, "set": bool(source),
                    "stored": bool(row), "updated": row["updated"] if row else None,
                    # an env or file key WINS, so say so rather than letting the
                    # page imply the stored one is in use
                    "shadowed": bool(row) and bool(env or in_file)})
    return out


def demo():
    import tempfile
    global KEY_PATH
    db.DATA = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(db.DATA, "t.db")
    db._local.__dict__.clear()
    KEY_PATH = os.path.join(tempfile.mkdtemp(), "cred.key")

    os.environ.pop("XAI_API_KEY", None)
    real_file = PROVIDERS["xai"]["file"]
    real_openai_file = PROVIDERS["openai"]["file"]
    PROVIDERS["xai"]["file"] = ""          # ignore this box's real key file
    PROVIDERS["openai"]["file"] = ""       # ignore real openai.env so test .env is consulted
    try:
        assert get("xai") == "", "a secret appeared from nowhere"
        assert get("no-such-provider") == ""

        try:
            put("xai", "sk-stored-value")
        except Unavailable:
            print("creds.py demo OK (cryptography not installed -- storing refused, "
                  "which is the designed behaviour)")
            return

        # 1. round trip, and the DATABASE must not contain the plaintext
        assert get("xai") == "sk-stored-value"
        blob = db.one("SELECT ciphertext FROM credentials WHERE name='xai'")["ciphertext"]
        assert b"sk-stored-value" not in bytes(blob), "the secret is in the database in clear"
        with open(db.DB_PATH, "rb") as f:
            assert b"sk-stored-value" not in f.read(), \
                "the secret is recoverable from the sqlite file, which is the one thing " \
                "this is supposed to prevent"

        # 2. the key file is the separation, and it is 0600
        mode = stat.S_IMODE(os.stat(KEY_PATH).st_mode)
        assert mode == 0o600, f"key file is {oct(mode)}, not 0600"

        # 3. env WINS over the store, so nothing that works today changes
        os.environ["XAI_API_KEY"] = "sk-from-env"
        assert get("xai") == "sk-from-env", "a stored key shadowed the environment"
        st = {s["name"]: s for s in status()}["xai"]
        assert st["shadowed"] and "environment" in st["source"], st
        del os.environ["XAI_API_KEY"]
        assert get("xai") == "sk-stored-value"

        # 4. status never carries the value
        assert all("sk-stored-value" not in str(s) for s in status()), "status leaked the secret"

        # 5. replace and clear
        put("xai", "sk-second")
        assert get("xai") == "sk-second"
        clear("xai")
        assert get("xai") == ""
        assert not db.one("SELECT id FROM credentials WHERE name='xai'")

        # 6. the general .env file is consulted for any provider, and a
        #    NON-secret setting reads with the same precedence from the same
        #    files -- that is how the model name travels beside the key
        global ENV_FILE
        real_env_file = ENV_FILE
        test_env_file = os.path.join(tempfile.mkdtemp(), ".env")
        with open(test_env_file, "w") as f:
            f.write("OPENAI_API_KEY=sk-from-dotenv\nSTUDIO_OPENAI_MODEL=gpt-test-9\n")
        try:
            os.environ.pop("OPENAI_API_KEY", None)
            # setting() and get() both consult ENV_FILE for openai key (no provider-specific file in test)
            # temporarily override the module global
            original_env_file = ENV_FILE
            ENV_FILE = test_env_file
            assert get("openai") == "sk-from-dotenv", f"the .env fallback was not consulted (got {get('openai')!r})"
            assert setting("STUDIO_OPENAI_MODEL", "openai") == "gpt-test-9"
            assert setting("STUDIO_NOTHING_SET") == ""
            # the environment still wins, for settings as well as secrets
            os.environ["STUDIO_OPENAI_MODEL"] = "gpt-from-env"
            assert setting("STUDIO_OPENAI_MODEL", "openai") == "gpt-from-env"
            del os.environ["STUDIO_OPENAI_MODEL"]
            src = {s["name"]: s for s in status()}["openai"]["source"]
            assert ".env" in src, f"status did not name the file the key came from: {src}"
        finally:
            ENV_FILE = original_env_file

        # 7. an unreadable key file is not a crash -- the caller is told there
        #    is no secret, which is true
        put("xai", "sk-third")
        with open(KEY_PATH, "wb") as f:
            f.write(b"not-a-valid-fernet-key")
        assert get("xai") == "", "a corrupt key file was not handled"
    finally:
        PROVIDERS["xai"]["file"] = real_file
        PROVIDERS["openai"]["file"] = real_openai_file
    print("creds.py demo OK")


if __name__ == "__main__":
    demo()
