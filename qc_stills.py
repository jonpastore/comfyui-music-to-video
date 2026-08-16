#!/usr/bin/env python3
"""Score a directory of stills with the studio QC stack.

Tier 1: qc.check_image (opens, not_blank, not_uniform, lighting cast).
Tier 2: qc.score_identity_artefact vs the job's source photo (colour histogram).
Vision: vision.score_candidate vs the source, plus a hallucination checklist.

Never a gate on the histogram alone (T3-17). Extra-person / ghost / melt from
the vision checklist is what we reject on. Each reject also names a prompt /
graph fix from the 2026-08-15 measured loop. Judge the picture last.

usage:
  python3 qc_stills.py --dir anchor5/nude-qc --map looking-back=anchor5/looking-back.jpg
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "studio"))
import qc
import vision

HALLUC_SYSTEM = (
    "You inspect one generated character image. Answer JSON only: "
    '{"extra_person": <bool>, "ghost": <bool>, "melted": <bool>, '
    '"clothes": <bool>, "extra_tails": <bool>, "is_her_species": <bool>, '
    '"pose": "<short>", "anatomy_visible": <bool>, '
    '"notes": "<one short sentence>"}.'
)
HALLUC_USER = (
    "Flag extra_person if there is more than one figure. "
    "Flag ghost if a transparent double, smear, or second body is behind her. "
    "Flag melted if limbs, face, or anatomy are unreadable garbage. "
    "clothes is true if a garment, harness, boots, or gloves remain "
    "(jewelry and hoop earrings are not clothes). "
    "is_her_species is true only if this is a black feline-headed woman "
    "with cat ears and a tail, not a human woman and not a different character. "
    "anatomy_visible is true only if vulva or anus is actually drawn and readable. "
    "extra_tails is true if more than one tail is visible."
)


# Measured 2026-08-15 on this fleet. A finding without a prompt/graph fix is
# only a label. Identity-wrong already says "edit the text" (T3-28); these
# are the still-specific counterparts.
PROMPT_FIXES = (
    ("extra_person",
     "Empty latent + a contradictory source pose invents a second body. "
     "Use make_anchor empty latent with identity refs only, or image-latent "
     "with pose wording that MATCHES the source. Do not attach a stranger pose plate."),
    ("ghost",
     "Image-latent asked for a different pose than the encoded photo. "
     "Rewrite the leading pose clause to the source pose (i08). "
     "Do not ask kneeling on a standing encode."),
    ("melted",
     "CFG>2 or Lightning LoRA at cfg>1. Stay CFG 2.0 / 50 / LoRA 0. New seed."),
    ("not_her",
     "Drop 'human body/anatomy/form/skin' from the positive (T4-14). "
     "Bind anatomy to 'a darker shade of that same skin'. Identity photo as image1. "
     "Do not use meowp_*_poseplate.png as image2."),
    ("clothes",
     "Denoise<=0.95 on a clothed encode keeps the outfit. Denoise 1.0. "
     "Seed 843167749 undresses; 129080599 holds leather. "
     "Do not name garments in the positive. Jewelry stays as a positive keep."),
    ("extra_tails",
     "Short negative already has 'extra tails'. Do not raise CFG (3+ adds tails). New seed."),
    ("anatomy_missing",
     "Pose, not prompt, exposes anatomy. Same-pose 3/4 standing cannot show vulva. "
     "Need an exposing source pose or a pose plate that is HER, not the charcoal stranger."),
    ("olive_cast",
     "Backdrop lighting lock. Keep 'plain flat uniform neutral grey studio'. "
     "Do not add olive/green/sage to the negative unless you are A/B testing that term."),
)


def _worst(findings):
    return qc.worst(findings)


def score_one(path, identity, prompt=""):
    row = {"path": path, "name": os.path.basename(path)}
    findings = qc.check_image(path, {})
    row["tier1"] = _worst(findings)
    row["lighting"] = next((f["detail"] for f in findings if f["check"] == "channel_balance"), "")
    row["t1"] = [{"check": f["check"], "verdict": f["verdict"], "detail": f["detail"]}
                 for f in findings if f["verdict"] != qc.PASS]
    try:
        ident = qc.score_identity_artefact(path, identity)
        row["identity_hist"] = round(ident["score"], 4)
    except Exception as e:
        row["identity_hist"] = None
        row["identity_err"] = str(e)[:120]
    try:
        vis = vision.score_candidate(path, [identity] if identity else [], prompt, print)
        row["vision"] = vis
    except Exception as e:
        row["vision"] = {"error": str(e)[:200]}
    try:
        raw = vision.ask(path, HALLUC_SYSTEM, HALLUC_USER, print)
        hall = vision.json_or_raise(raw, "hallucination check")
        row["halluc"] = hall
    except Exception as e:
        row["halluc"] = {"error": str(e)[:200]}
    h = row.get("halluc") or {}
    reject = []
    if row["tier1"] == qc.REJECT:
        reject.append("tier1")
    if h.get("extra_person"):
        reject.append("extra_person")
    if h.get("ghost"):
        reject.append("ghost")
    if h.get("melted"):
        reject.append("melted")
    if h.get("is_her_species") is False:
        reject.append("not_her")
    if h.get("extra_tails"):
        reject.append("extra_tails")
    if h.get("clothes"):
        reject.append("clothes")
    if h.get("anatomy_visible") is False:
        reject.append("anatomy_missing")
    if any(f["check"] == "channel_balance" and f["verdict"] != qc.PASS for f in findings):
        reject.append("olive_cast")
    row["reject"] = reject
    row["keep"] = not reject or reject == ["anatomy_missing"] or reject == ["clothes"] or set(reject) <= {"clothes", "anatomy_missing"}
    # clothes/anatomy-missing are usable same-pose nudes (i08); still emit fixes
    row["prompt_fixes"] = prompt_fixes(row)
    return row


def prompt_fixes(row):
    """One recommended rewrite per finding. Order is PROMPT_FIXES."""
    flags = set(row.get("reject") or [])
    h = row.get("halluc") or {}
    if h.get("clothes"):
        flags.add("clothes")
    if h.get("anatomy_visible") is False:
        flags.add("anatomy_missing")
    out = []
    for key, text in PROMPT_FIXES:
        if key in flags:
            out.append({"finding": key, "fix": text})
    return out


def infer_identity(name, mapping):
    for key, src in mapping.items():
        if key in name:
            return src
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--map", action="append", default=[],
                    help="substring=identity/path (repeatable)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    mapping = {}
    for item in args.map:
        k, _, v = item.partition("=")
        mapping[k] = v
    files = sorted(p for p in (os.path.join(args.dir, f) for f in os.listdir(args.dir))
                   if p.lower().endswith((".png", ".jpg", ".jpeg")))
    report = []
    for p in files:
        ident = infer_identity(os.path.basename(p), mapping)
        print(f"=== {os.path.basename(p)} vs {ident or '(none)'}", flush=True)
        report.append(score_one(p, ident))
    dest = args.out or os.path.join(args.dir, "qc_report.json")
    json.dump(report, open(dest, "w"), indent=2)
    print("\n# keep / reject")
    for r in report:
        mark = "KEEP" if r["keep"] else "DROP " + ",".join(r["reject"])
        vis = (r.get("vision") or {})
        h = r.get("halluc") or {}
        print(f"{mark:28s} {r['name']}  hist={r.get('identity_hist')}  "
              f"vis_id={vis.get('identity')} vis_p={vis.get('prompt')}  "
              f"clothes={h.get('clothes')} pose={h.get('pose')}  {h.get('notes','')}")
        for fx in r.get("prompt_fixes") or []:
            print(f"    FIX {fx['finding']}: {fx['fix']}")
    print(f"\n{sum(1 for r in report if r['keep'])}/{len(report)} keep -> {dest}")


if __name__ == "__main__":
    main()
