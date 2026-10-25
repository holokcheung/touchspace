"""Reconstruct the venue's ground floor, retaining interior partitions for 3D.

Coordinates are hand-traced in the official PDF page 1 rendered at 150% (1188 x
918). See ../palace-of-fine-arts/README.md for references and modeling limits.
No PDF/image library is needed to regenerate the two application fixtures.
Run from any directory: python3 sample-data/scripts/make_palace_of_fine_arts.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTS = [ROOT / "palace-of-fine-arts.json", ROOT.parent / "frontend/standalone/maps/palace-of-fine-arts.json"]
SOURCE_URL = "https://palaceoffinearts.com/wp-content/uploads/sites/4/2025/04/PFA-Master-Floorplan.pdf"
# Retain the earlier OSM end-to-end scale, applied to the new trace's extents.
M_PER_PX = 273.8 / (1115 - 62)


def pt(px, py):
    # The parking sheet's compass points west up: page right = north.
    return {"x": round((py - 153) * M_PER_PX, 3),
            "y": round((px - 62) * M_PER_PX, 3)}


def poly(points):
    return [pt(*p) for p in points]


walls, doors, rooms, landmarks = [], [], [], []


def wall(wid, a, b, shell=False):
    if math.dist(a, b) < 0.1:
        raise ValueError(f"Degenerate wall: {wid}")
    walls.append({"id": wid, "start": pt(*a), "end": pt(*b),
                  "thickness": 0.4 if shell else 0.18,
                  "height": 8.0 if shell else 3.0, "confidence": "medium",
                  "metadata": {"reference_page": 1, "height_is_assumed": True}})
    return wid


def path(wid, points, closed=False, shell=False):
    pairs = list(zip(points, points[1:] + points[:1] if closed else points[1:]))
    return [wall(f"w_{wid}_{i:02}", a, b, shell) for i, (a, b) in enumerate(pairs)]


def door(did, wid, fraction=0.5, width=1.2):
    w = next(w for w in walls if w["id"] == wid)
    a, b = w["start"], w["end"]
    doors.append({"id": f"d_{did}", "kind": "door", "wall_id": wid,
                  "position": {k: round(a[k] + fraction * (b[k] - a[k]), 3) for k in "xy"},
                  "width": width, "confidence": "medium"})


def room(rid, name, points, description=""):
    rooms.append({"id": f"r_{rid}", "name": name, "polygon": poly(points), "description": description})


def enclosed(rid, name, points, entries=(), description=""):
    ids = path(rid, points, closed=True)
    for i, fraction, width in entries:
        door(f"{rid}_{i}", ids[i], fraction, width)
    room(rid, name, points, description)
    return ids


def landmark(lid, name, kind, x, y, description=""):
    landmarks.append({"id": f"lm_{lid}", "name": name, "type": kind,
                      "position": pt(x, y), "description": description, "source": "manual"})


# Curved shell traced with more samples. Openings belong to explicit wall IDs;
# no nearest-wall guessing, which can attach interior doors to the outer shell.
OUTER = [(62,240),(105,220),(153,200),(201,185),(248,173),(294,163),
         (340,157),(390,154),(436,153),(480,155),(525,160),(570,170),
         (615,181),(660,195),(705,211),(750,230),(795,253),(840,278),
         (883,307),(925,339),(967,375),(1007,414),(1045,456),
         (1081,503),(1115,553)]
INNER = [(156,425),(195,408),(240,393),(285,381),(330,371),(375,364),
         (420,360),(465,362),(510,368),(555,378),(600,391),(645,407),
         (690,428),(735,452),(777,481),(818,514),(856,551),(892,593),
         (938,656)]
SHELL = OUTER + [(1078,575),(1068,562),(1032,584),(991,607),(970,620),
                 (979,631)] + INNER[::-1]
shell_ids = path("shell", SHELL, closed=True, shell=True)
# These openings are visible on the plan: loading, public, business and lagoon exits.
door("loading", shell_ids[7], 0.72, 5.0)


def shell_door(did, p, width):
    # Restrict projection to the shell only. Check distance to catch a bad trace.
    q = pt(*p)
    candidates = []
    for wid in shell_ids:
        w = next(w for w in walls if w["id"] == wid)
        a, b = w["start"], w["end"]
        vx, vy = b["x"]-a["x"], b["y"]-a["y"]
        t = max(0, min(1, ((q["x"]-a["x"])*vx+(q["y"]-a["y"])*vy)/(vx*vx+vy*vy)))
        candidates.append((math.hypot(q["x"]-a["x"]-t*vx,q["y"]-a["y"]-t*vy),wid,t))
    distance, wid, t = min(candidates)
    assert distance < 1.5, (did, distance)
    door(did, wid, t, width)


shell_door("public_entrance", (385,363), 3.6)
shell_door("business_entrance", (1007,598), 2.4)
shell_door("lagoon_exit", (758,469), 2.4)
shell_door("north_exit", (901,604), 2.0)

# Round breakout block, two distinct rooms divided by the slanting center wall.
cx, cy, rx, ry = 544, 264, 45, 39
ring = [(cx+rx*math.cos(t),cy+ry*math.sin(t)) for t in [2*math.pi*i/40 for i in range(40)]]
ring_ids = path("breakout_ring", ring, closed=True)
door("breakout1",ring_ids[20],0.5,1.5)
door("breakout2",ring_ids[3],0.5,1.5)
# The divider leans slightly right at its upper end; include the connecting door.
divider = wall("w_breakout_divider",(542,225),(528,301))
door("breakout_connect",divider,0.5,1.1)
# Split the curved floor polygons at the actual chord intersections.
# Circle outline and divider differ by <0.7 m at their endpoints in this trace.
room("breakout1","Breakout 1",[(528,301)]+ring[13:30]+[(542,225)])
room("breakout2","Breakout 2",[(542,225)]+ring[31:]+ring[:12]+[(528,301)])

# Breakouts 3/4 share one wall (avoid duplicate collision/tactile geometry).
block = [(619,230),(692,252),(664,339),(591,317)]
bids = path("breakout34",block,closed=True)
wall("w_breakout34_divider",(605,273),(678,295))
door("breakout3",bids[3],0.78,1.2)
door("breakout4",bids[1],0.7,1.2)
room("breakout3","Breakout 3",[block[0],block[1],(678,295),(605,273)])
room("breakout4","Breakout 4",[(605,273),(678,295),block[2],block[3]])

enclosed("breakout5","Breakout 5",[(903,367),(951,410),(910,452),(877,405)],[(2,0.55,1.8)])
enclosed("breakout6","Breakout 6",[(784,443),(819,441),(842,459),(862,476),(886,494),
                                         (886,517),(868,534),(831,506),(802,481),(768,459)],
         [(2,0.5,1.5),(9,0.4,1.5)])
# Breakout 7 is an open event zone; the drawing shows no enclosing west wall.
room("breakout7","Breakout 7",[(951,411),(1028,431),(1071,488),(1005,533),(981,486),(939,447)],
     "Open event area beside the mezzanine stairs; no partition across the circulation aisle.")
path("breakout7_service",[(968,410),(1001,435),(1023,414)])

# Service strip along Palace Drive: catering, restrooms and escape rooms.
path("catering",[(525,160),(520,185),(565,196),(573,171)])
room("catering","Catering prep",[(480,155),(525,160),(520,185),(565,196),(559,215),(480,194)])
for rid,name,points in [
    ("restroom_catering_w","Women's restroom by catering",[(573,171),(615,181),(605,209),(565,198)]),
    ("restroom_catering_m","Men's restroom by catering",[(615,181),(655,193),(647,222),(605,209)]),
    ("service_store","Service storage",[(655,193),(691,205),(679,235),(647,222)]),
]:
    enclosed(rid,name,points,[(2,0.5,1.1)])

staff = [(729,247),(776,268),(822,294),(869,325),(856,356),(873,365),(858,389),(844,381),(817,391),(692,323)]
# The full block is restricted, with a long central corridor and office partitions.
staff_ids = enclosed("staff","Staff offices (no access)",staff,[(7,0.5,1.5)],
                      "Restricted block; internal office partitions traced approximately from the venue plan.")
path("staff_corridor",[(717,293),(751,310),(785,329),(820,350),(849,370)])
for i,(a,b) in enumerate([
    ((729,247),(717,276)),((753,258),(738,286)),((776,268),(759,305)),
    ((799,281),(780,319)),((822,294),(800,337)),((845,309),(825,351)),
    ((717,293),(703,319)),((745,307),(727,340)),((771,321),(753,356)),
    ((796,337),(777,370)),((820,350),(800,384)),
]):
    wid=wall(f"w_office_{i:02}",a,b)
    # Leave a door near the corridor end of each approximate office divider.
    door(f"office_{i:02}",wid,0.72,0.9)
# Palace Games occupies the outer strip above the staff block.
room("palace_games","Palace Games (no access)",[(705,211),(750,230),(795,253),(840,278),(883,307),(925,339),
                                               (885,358),(869,325),(822,294),(776,268),(729,247)])
path("games_front",[(729,247),(705,240),(692,270)])
for i,(a,b) in enumerate([((763,237),(750,268)),((807,260),(791,285)),((853,287),(837,304))]):
    wall(f"w_games_{i}",a,b)

# Lagoon-side back-of-house strip, retaining the open circulation alongside it.
path("back_of_house",[(499,346),(542,352),(585,363),(627,378),(668,391),(663,407)])
wall("w_back_of_house_start",(499,346),(496,365))
room("back_of_house","Available back of house",[(499,346),(542,352),(585,363),(627,378),(668,391),(663,407),
                                                (645,407),(600,391),(555,378),(510,368),(496,365)])
door("back_of_house", "w_back_of_house_02", 0.6, 1.2)
# Green rooms and service room at the south end.
path("south_service",[(93,226),(115,277),(215,237),(201,185)])
room("south_service","South service area (no access)",[(62,240),(93,226),(115,277),(85,289)])
path("green_rooms",[(101,318),(119,310),(133,339),(116,347)])
path("green_room_two",[(132,380),(160,368),(178,403)])
room("green_rooms","Green rooms",[(85,289),(115,277),(178,403),(156,425)])
# North end lobby, restrooms and theater boundary, visible on the source.
path("north_lobby",[(916,626),(1051,544),(1078,575)])
door("theater_lobby","w_north_lobby_00",0.62,2.0)
path("north_services",[(1005,533),(1071,488)])
path("north_restroom",[(1051,544),(1089,520)])
room("restroom_north","North end restroom",[(1051,544),(1089,520),(1115,553),(1078,575)])
path("lobby_south_wc",[(938,640),(957,628),(969,649)])
room("restroom_lobby","Restroom by business entrance",[(916,626),(938,656),(969,639),(957,619)])
room("theater","Theater area",[(831,520),(865,534),(892,570),(916,626),(1005,572),(964,548),(901,540)])

# Open-floor areas: boundaries color the floor only, never create fictitious walls.
# Put small rooms first for roomAt(); a complete shell floor fills circulation gaps.
room("pavilion","Pavilion",[(115,277),(215,237),(201,185),(248,173),(270,300),(195,408),(156,425)])
room("atrium","Atrium",[(248,173),(340,157),(390,154),(436,153),(460,310),(420,360),(375,364),(330,371),(195,408),(270,300)])
room("broadway1","Broadway 1",[(436,153),(480,155),(499,225),(499,303),(591,317),(585,363),(510,368),(465,362),(420,360),(460,310)])
room("broadway2","Broadway 2",[(591,317),(664,339),(692,270),(692,323),(817,391),(777,421),(735,452),(690,428),(645,407),(663,407),(668,391)])
room("broadway3","Broadway 3",[(817,391),(877,405),(910,452),(981,486),(1005,533),(901,540),(886,517),(886,494),(842,459),(819,441),(784,443),(768,459),(735,452),(777,421)])
room("circulation","First-floor circulation",SHELL,"Continuous ground-floor footprint; upper mezzanine is not modeled.")

for lid,name,kind,x,y,description in [
    ("public_entrance","Public entrance","entrance",385,351,"Public doors on the lagoon side, near the atrium."),
    ("business_entrance","Business entrance","entrance",1007,590,"North end lobby doors beside the theater area."),
    ("loading","Loading doors","other",425,164,"Loading doors on Palace Drive."),
    ("pavilion","Pavilion","room",225,280,"Open event area at the south end."),
    ("atrium","Atrium","room",354,307,"Open event area beside the public entrance."),
    ("green_rooms","Green rooms","room",142,359,"Service rooms at the south end."),
    ("catering","Catering prep","room",543,187,"Prep area beside the service restrooms."),
    ("restroom_north","Restrooms by catering prep","restroom",589,194,"Service restrooms along Palace Drive."),
    ("palace_games","Palace Games","room",780,262,"Restricted escape-room strip along Palace Drive; separate venue access."),
    ("staff","Staff offices (no access)","room",775,340,"Restricted staff office block."),
    ("breakout1","Breakout 1","room",518,262,"One half of the circular room."),
    ("breakout2","Breakout 2","room",561,267,"Other half of the circular room."),
    ("breakout3","Breakout 3","room",646,266,"Outer room of the rectangular breakout block."),
    ("breakout4","Breakout 4","room",632,308,"Inner room of the rectangular breakout block."),
    ("breakout5","Breakout 5","room",913,410,"Enclosed breakout beside the mezzanine stairs."),
    ("breakout6","Breakout 6","room",843,489,"Angled room along the lagoon side."),
    ("breakout7","Breakout 7","room",1000,468,"Open event area at the north end."),
    ("stairs","Stairs to the mezzanine","stairs",934,464,"Stairs beside Breakout 5; upper level is not modeled."),
    ("theater","Theater","room",926,574,"Theater area shown on the first-floor venue plan."),
    ("restroom_east","Restroom, north end","restroom",1084,549,"Restroom at the north end beside Breakout 7."),
    ("restroom_south","Restroom by the business entrance","restroom",946,639,"Restroom beside the business entrance lobby."),
    ("broadway1","Broadway 1","room",492,329,"Open floor around the circular breakout block."),
    ("broadway2","Broadway 2","room",705,369,"Main circulation beside staff offices."),
    ("broadway3","Broadway 3","room",818,420,"Open floor between Breakouts 5 and 6."),
    ("back_of_house","Available back of house","room",578,380,"Narrow service strip along the lagoon wall."),
]:
    landmark(lid,name,kind,x,y,description)

floor_map = {
    "schema_version": "1.0", "id": "palace-of-fine-arts",
    "name": "Palace of Fine Arts, first floor", "units": "meters",
    "source": {"kind": "manual", "description":
        f"Interior reconstruction traced from the official PFA Master Floorplan, page 1: {SOURCE_URL} "
        "(accessed 2026-10-25). North up. Approximate scale retained from OpenStreetMap "
        "(c) OpenStreetMap contributors, 273.8 m overall span. Interior walls, door positions "
        "and room footprints are hand-traced; heights (8 m shell / 3 m partitions) and wall "
        "thicknesses are illustrative, not surveyed. Ground floor only; mezzanine not modeled. "
        "Restricted areas are labeled, not verified public routes."},
    "floor_level": 0, "walls": walls, "doors": doors, "openings": [],
    "windows": [], "objects": [], "rooms": rooms, "landmarks": landmarks,
    "start_landmark_id": "lm_public_entrance",
}


def preview():
    """Reviewable SVG in source drawing orientation, with model doorway cuts."""
    def page(p):
        return (p["y"]/M_PER_PX+62,p["x"]/M_PER_PX+153)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="40 125 1100 560">',
             '<rect x="40" y="125" width="1100" height="560" fill="#fff"/>']
    for r in reversed(rooms):
        points=" ".join(f"{x:.2f},{y:.2f}" for x,y in map(page,r["polygon"]))
        fill = "#deddd5" if "no access" in r["name"].lower() else "#edf2ec"
        parts.append(f'<polygon points="{points}" fill="{fill}" stroke="#c5d0c6" stroke-width="0.5"/>')
    for w in walls:
        a,b=page(w["start"]),page(w["end"])
        parts.append(f'<path d="M{a[0]},{a[1]} L{b[0]},{b[1]}" stroke="#263c35" stroke-width="1.8"/>')
    for d in doors:
        w=next(w for w in walls if w["id"]==d["wall_id"])
        a,b=page(w["start"]),page(w["end"]); x,y=page(d["position"])
        dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
        h=d["width"]/M_PER_PX/2
        parts.append(f'<path d="M{x-dx/length*h},{y-dy/length*h} L{x+dx/length*h},{y+dy/length*h}" stroke="#fff" stroke-width="3"/>')
    for l in landmarks:
        x,y=page(l["position"])
        parts.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#af6335"/><text x="{x+4}" y="{y-4}" font-family="sans-serif" font-size="9">{l["name"]}</text>')
    parts.append('</svg>')
    return "\n".join(parts)+"\n"


if __name__ == "__main__":
    text = json.dumps(floor_map, indent=2) + "\n"
    for out in OUTS:
        out.write_text(text)
        print(f"wrote {out}")
    (ROOT / "palace-of-fine-arts/reconstruction.svg").write_text(preview())
    print(f"{len(walls)} walls, {len(doors)} doors, {len(rooms)} room/area polygons")
