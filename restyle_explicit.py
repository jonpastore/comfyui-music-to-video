#!/usr/bin/env python3
"""Restyle the EXPLICIT Rear Entrance storyboard to a suggestive-but-tasteful cut.

What it changes, per scene:
  - image_prompt: FRONT-LOADS a lyric-mapped suggestive beat (attitude / pose /
    eye-contact) so it actually renders (finding 1: only the front of the prompt
    is obeyed). Keeps the character lock (with the jacket phrase so build_song's
    outfit swap still fires), the world, the scene line, and a POSITIVE
    fully-clothed / non-graphic guardrail (finding 5: negatives are inert at cfg 1).
  - video_motion_prompt: front-loads a sensual-but-clothed motion beat.
  - story_action: a suggestive subject line for the detail/macro path
    (build_refs.tighten_for_detail reads this first).

Nothing here is graphic: no nudity, no anatomy focus, no sex acts. Purely mood,
confidence, flirtation and innuendo-as-atmosphere. Backs up the original first.
"""
import json, os, shutil, sys

SRC = "Street Cats/Rear Entrance/rear_entrance_explicit.json"

CHARACTER = ("adult anthropomorphic black feline woman DJ, sleek black fur, yellow-green almond eyes, "
             "long wavy black hair with subtle purple highlights, feline ears and tail, gold ear piercings, "
             "layered gold jewelry, black leather street/club jacket, fitted black pants, black boots, "
             "gold hardware and chains, confident mysterious expression, consistent face and proportions.")
WORLD = ("Street Cats visual world: neon-noir industrial warehouse district, wet concrete, black steel, "
         "chain-link fencing, exposed pipes, service corridors, loading docks, stairwells, red utility lights, "
         "deep magenta and purple club spill, small gold accents, atmospheric steam and haze, "
         "cinematic cyberpunk realism, premium underground electronic-music video, 16:9.")
MOTIF = ("Track motif: closed front entrance, service alley, badge lights, freight elevator, "
         "steel doors, backstage route.")
GUARD = ("Mature after-hours nightlife tone: confident, sensual, self-possessed body language, "
         "flirtatious eye contact and a sultry knowing attitude, adult innuendo carried purely as "
         "atmosphere and mood; adults only, fully clothed at all times, tasteful and non-graphic, "
         "no nudity, no exposed intimate anatomy, no body-part emphasis, no explicit sexual activity, "
         "no simulated sex, no fetish acts, no explicit gestures, no coercion.")
TECH = ("photorealistic cinematic 3D frame, premium music video production, realistic fur, "
        "realistic fabric and metal, volumetric haze, coherent anatomy, high detail, "
        "anamorphic composition, 16:9, no text in frame")

# Per-scene suggestive beat (front of image_prompt). Tasteful, clothed, mood-only.
BEAT = {
 1:"Sultry after-hours mood: the club's public face going dark while a warm, inviting glow leaks from the hidden rear route, a wordless invitation.",
 2:"Intimate, secretive back-alley mood, the camera drawn toward a warmer, more private glow deeper in the shadows.",
 3:"A single small green access light pulsing like a beckoning signal in the dark, teasing anticipation.",
 4:"She gives the closed front door a slow, dismissive glance, then a confident knowing half-smile and a subtle tilt of the head toward the back — 'not that way'.",
 5:"Leading the viewer with a playful glance back over her shoulder, a confident hip-led saunter, coat and hair swaying.",
 6:"Her sensual silhouette in profile as a hard light wipes across the frame, poised and unhurried.",
 7:"An unhurried, hypnotic, self-assured walk drawing the viewer deeper down the narrow corridor, fully in control.",
 8:"One teasing fingertip resting on a small steel service door, a quiet 'this one' look.",
 9:"Direct, inviting eye contact with the viewer, one hand on the doorframe, an arched brow and a slow knowing smile — 'you want inside?'.",
 10:"A confident beckoning glance back as the door opens and magenta fog spills out, welcoming the viewer through.",
 11:"Leaning back against the steel wall of the descending freight elevator, relaxed and completely in command, warm under-light.",
 12:"Rhythmic, flirtatious flash-cuts synced to the vocal chops: a smirk, a hand on a latch, a confident turn.",
 13:"Looking down on the crowded, ordinary public floor with an amused, superior half-smile — 'that's boring'.",
 14:"Slipping into a hidden corridor with a conspiratorial, inviting glance back as an acoustic panel closes behind her.",
 15:"Trailing her fingertips along a row of identical doors with teasing anticipation, choosing the right one.",
 16:"A playful, effortful lean of her shoulder against a heavy door that barely gives, a small determined smile.",
 17:"Leaning in with more intent and a satisfied smirk as the door finally yields and bass pressure leaks through.",
 18:"Stepping into the revealed hidden side room and owning it, a sultry adult crowd turning as she enters.",
 19:"Rhythmic, confident match-cuts of gates and doors opening on the beat with her assured movement.",
 20:"A knowing pause in the quiet haze, a teasing glance back over her shoulder — 'trust me'.",
 21:"Late, private, after-3AM intimacy: her confident silhouette by the one rear route still glowing.",
 22:"Her hand settling on the final backstage latch, claws resting, charged with anticipation.",
 23:"Approaching the door together with the camera, a focused, sultry, building intensity.",
 24:"Coaxing the door open in slow stages with a patient, teasing smile.",
 25:"A single decisive, commanding motion as the door swings wide, powerful and magnetic in a white-magenta hit.",
 26:"A triumphant, magnetic entrance owning the booth and stage as the whole floor ignites around her.",
 27:"A satisfied, in-control retreat back down the route with a final knowing glance as the lights strip away.",
}

# Per-scene sensual-but-clothed motion beat (front of video_motion_prompt).
MBEAT = {
 1:"slow atmospheric establishing drift, inviting glow pulsing",
 2:"slow sensual dolly along the alley, steam curling",
 3:"the green light pulses invitingly, rack focus",
 4:"a slow dismissive glance then a confident beckoning head-tilt",
 5:"she leads with a playful over-the-shoulder glance, hips leading, hair swaying",
 6:"her profile glides through a light wipe, poised",
 7:"a hypnotic confident walk drawing the viewer deeper",
 8:"a teasing fingertip rests on the door, a 'this one' look",
 9:"slow inviting eye contact and a knowing smile to camera",
 10:"a beckoning glance back as the door opens and fog spills",
 11:"she leans back against the elevator wall, relaxed and in command",
 12:"rhythmic flirtatious flash-cuts on the vocal chops",
 13:"an amused superior glance down at the ordinary crowd",
 14:"a conspiratorial glance back as the panel seals behind her",
 15:"fingertips trailing the doors with teasing anticipation",
 16:"a playful determined shoulder-lean against the heavy door",
 17:"leaning in with a satisfied smirk as it yields",
 18:"she steps in owning the room as the crowd turns",
 19:"confident match-cuts of doors opening on the beat",
 20:"a knowing pause and teasing glance back in the haze",
 21:"a confident silhouette holds by the glowing rear route",
 22:"her hand settles on the latch, charged anticipation",
 23:"a focused sultry approach in sync with the camera",
 24:"coaxing the door open in stages with a teasing smile",
 25:"one decisive commanding push as it swings wide",
 26:"a triumphant magnetic entrance as the floor ignites",
 27:"a satisfied in-control retreat with a final knowing glance",
}

# Suggestive subject line for the detail/macro/close path (tighten_for_detail).
SACT = {
 3:"a small green access light pulsing invitingly in the dark behind the building",
 6:"her sensual feline profile catching a hard light wipe",
 8:"a teasing fingertip resting on a small steel service door",
 9:"her face in close-up giving the viewer inviting eye contact and a knowing smile",
 12:"quick flirtatious detail cuts: a smirk, a hand on a latch, gold jewelry catching light",
 16:"her shoulder pressing playfully against a heavy steel door that barely gives",
 22:"her clawed hand settling on the final backstage door latch, charged with anticipation",
 25:"her hand delivering one decisive push as the door swings wide in a magenta light hit",
}

def main():
    d = json.load(open(SRC))
    if not os.path.exists(SRC + ".clean_bak"):
        shutil.copy(SRC, SRC + ".clean_bak")
    for s in d["scenes"]:
        n = s["scene_number"]
        beat = BEAT.get(n, "Confident, sultry, self-possessed nightlife attitude.")
        story = s.get("story", "")
        cam = s.get("camera", "")
        motion = s.get("motion", "")
        light = s.get("lighting", "")
        s["image_prompt"] = (f"{beat} {CHARACTER} {WORLD} {MOTIF} Scene: {story} "
                             f"Camera: {cam}. Motion context: {motion}. Lighting: {light}. "
                             f"{GUARD} {TECH}")
        mbeat = MBEAT.get(n, "confident sultry body language")
        s["video_motion_prompt"] = (
            f"{mbeat}; {motion}; camera movement: {cam}; sensual confident after-hours nightlife "
            f"body language, flirtatious eye contact, sultry knowing attitude, fully clothed, tasteful "
            f"and non-graphic, no explicit gesture; stable character identity, stable anatomy, "
            f"natural hair, cloth and tail physics")
        if n in SACT:
            s["story_action"] = SACT[n]
    json.dump(d, open(SRC, "w"), indent=2, ensure_ascii=False)
    print("restyled", len(d["scenes"]), "explicit scenes; backup at", SRC + ".clean_bak")

if __name__ == "__main__":
    main()
