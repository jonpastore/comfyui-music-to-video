# Meow P Studio UX prototype

Disposable, mock-data-only prototype for the UI/UX review. It deliberately has no production API calls, no external assets, no storage, and no connection to the FastAPI studio.

## Open it

From this directory, either open `index.html` directly in a browser or serve it locally:

```bash
python3 -m http.server 8011
```

Then visit `http://127.0.0.1:8011/`.

## What it demonstrates

- Comparison of Operations Control Room, recommended Production Desk, and Review Theatre using shared mock evidence.
- Production Desk: attention-led work, scene-plan batch approval, timeline-led video review, progressive technical evidence, set arrangement, and release state.
- Fixture switcher covering normal, running/partial, missing-media, exhausted repair, keeper review, stale-plan, paid-cloud, empty, and partial-release conditions.
- Shared-keeper asset context: canonical asset, album/tier membership, reconciled and legacy-only compatibility, plus a safe review hold that does not expose migration internals.
- Keyboard-visible focus, dialog escape/close behavior, a skip link, responsive monitoring layouts, and the shared ghost-X dismiss control.

## Limits

This is a visual/interaction prototype. Its controls only update local mock state; it does not test server-authoritative authorization, actual media playback, real screen-reader announcements, persistent state, or production async contracts.
