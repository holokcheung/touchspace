"""Grounded spatial Q&A over a FloorMap.

Every fact in an answer comes from the map: landmark and room positions, the
navigation graph, and text the map's editors wrote. The parser is deterministic. An
optional language model (see `gemini.py`) may only help pick an intent and match a place
name to a known id; it never writes geometry, places or routes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel

from app.models.map import FloorMap, Landmark, LandmarkType, Point2D, Room
from app.services.routing import SAFETY_NOTE, RouteResult, RoutingError, compass, meters, plan_route

Intent = Literal["help", "overview", "list", "where", "nearby", "route", "whereami", "describe", "clarify", "unknown"]

SYMBOLS = {
    LandmarkType.entrance: "solid triangle", LandmarkType.exit: "solid square",
    LandmarkType.restroom: "solid circle", LandmarkType.stairs: "three parallel bars",
    LandmarkType.elevator: "hollow ring", LandmarkType.information: "plus sign",
}

TYPE_WORDS: dict[LandmarkType, list[str]] = {
    LandmarkType.restroom: ["restroom", "bathroom", "toilet", "washroom", "wc", "lavatory", "loo", "mens room",
                            "womens room", "mens", "womens", "ladies room"],
    LandmarkType.entrance: ["entrance", "entry", "front door", "main door", "way in"],
    LandmarkType.exit: ["exit", "way out", "emergency exit"],
    LandmarkType.stairs: ["stairs", "staircase", "stairway", "steps", "stairwell"],
    LandmarkType.elevator: ["elevator", "lift"],
    LandmarkType.information: ["information", "info", "reception", "front desk", "help desk", "info desk"],
}

STOP = {"the", "a", "an", "my", "this", "that", "please", "me", "to", "of", "is", "are", "where", "s", "there", "here"}
WEAK = {"room", "area", "door", "main"}
GENERIC = WEAK | {"space", "building", "place", "map", "layout", "floor", "it", "everything", "whole", "entire", "around"}

EXAMPLES = ["Describe this room.", "Where is the restroom?", "How do I get there from the main entrance?",
            "What is near the entrance?", "How do I get from the entrance to the exit?"]


class AskContext(BaseModel):
    last_place_id: str | None = None
    current_place_id: str | None = None
    avoid_stairs: bool = False


class AskResult(BaseModel):
    answer: str
    intent: Intent
    place_ids: list[str] = []
    route: RouteResult | None = None
    context: AskContext
    understood_by: Literal["rules", "gemini"] = "rules"
    safety_note: str | None = None
    suggestions: list[str] = []


@dataclass
class Place:
    id: str
    name: str
    position: Point2D
    landmark: Landmark | None = None
    room: Room | None = None

    @property
    def type(self) -> LandmarkType | None:
        return self.landmark.type if self.landmark else None


# --------------------------------------------------------------------------- text helpers


def norm(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in norm(text).split() if t not in STOP]


def _strip_qualifiers(name: str) -> str:
    return re.sub(r"\(.*?\)", "", name).strip()


def join_names(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


# --------------------------------------------------------------------------- places


def polygon_centroid(poly: list[Point2D]) -> Point2D:
    a = cx = cy = 0.0
    for p, q in zip(poly, poly[1:] + poly[:1]):
        cross = p.x * q.y - q.x * p.y
        a += cross
        cx += (p.x + q.x) * cross
        cy += (p.y + q.y) * cross
    if abs(a) < 1e-9:
        return Point2D(x=sum(p.x for p in poly) / len(poly), y=sum(p.y for p in poly) / len(poly))
    return Point2D(x=cx / (3 * a), y=cy / (3 * a))


def point_in(p: Point2D, poly: list[Point2D]) -> bool:
    inside = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a.y > p.y) != (b.y > p.y) and p.x < a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y):
            inside = not inside
    return inside


def all_places(fmap: FloorMap) -> list[Place]:
    places = [Place(id=lm.id, name=lm.name, position=lm.position, landmark=lm) for lm in fmap.landmarks]
    taken = {norm(_strip_qualifiers(p.name)) for p in places}
    for r in fmap.rooms:
        if norm(_strip_qualifiers(r.name)) not in taken:
            places.append(Place(id=r.id, name=r.name, position=polygon_centroid(r.polygon), room=r))
    return places


def room_containing(fmap: FloorMap, p: Point2D) -> Room | None:
    return next((r for r in fmap.rooms if point_in(p, r.polygon)), None)


def _token_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_places(fmap: FloorMap, phrase: str) -> list[tuple[Place, float]]:
    """Places matching a spoken phrase, best first. Tolerates synonyms and small slips."""
    q = norm(phrase)
    q_tokens = [t for t in tokens(phrase)]
    if not q_tokens:
        return []
    q_text = " ".join(q_tokens)
    scored: list[tuple[Place, float]] = []
    for place in all_places(fmap):
        name = norm(_strip_qualifiers(place.name))
        n_tokens = [t for t in name.split() if t not in STOP]
        score = 0.0
        if q_text == " ".join(n_tokens) or q == name:
            score = 1.0
        elif len(q_text) >= 3 and any(t not in GENERIC for t in q_tokens) and (q_text in name or name in q_text):
            score = 0.9
        words = TYPE_WORDS.get(place.type, []) if place.type else []
        if any(re.search(rf"\b{re.escape(w)}\b", q) for w in words):
            score = max(score, 0.88)
        # Synonym appearing in a room's own name (e.g. "stairwell" room for "stairs").
        if score < 0.8:
            for t, ws in TYPE_WORDS.items():
                if any(re.search(rf"\b{re.escape(w)}\b", q) for w in ws) and any(w in name for w in ws):
                    score = max(score, 0.75)
        strong = [t for t in n_tokens if t not in WEAK] or n_tokens
        if strong:
            hits = sum(1 for t in strong if any(_token_sim(t, qt) >= 0.8 for qt in q_tokens))
            if hits:
                score = max(score, 0.55 + 0.35 * hits / len(strong))
        score = max(score, _token_sim(q_text, " ".join(n_tokens)) * 0.85)
        if score >= 0.6:
            if place.landmark is not None:
                score += 0.01  # prefer a landmark over a same-named room
            scored.append((place, score))
    scored.sort(key=lambda x: -x[1])
    return scored


def resolve(fmap: FloorMap, phrase: str) -> tuple[Place | None, list[Place]]:
    """(best match, other close matches). Ambiguous when the second is nearly as good."""
    matches = match_places(fmap, phrase)
    if not matches:
        return None, []
    best, best_score = matches[0]
    close = [p for p, s in matches[1:] if best_score - s < 0.04 and norm(p.name) != norm(best.name)]
    # "Bedroom" vs "Bedroom 2": same name apart from a number. Unless the question names the
    # number, ask which one rather than silently picking the first.
    def base(name: str) -> str:
        return re.sub(r"\s*\d+$", "", norm(_strip_qualifiers(name)))
    if not re.search(r"\d", norm(phrase)):
        close += [p for p, s in matches[1:] if s >= 0.8 and p not in close and base(p.name) == base(best.name)
                  and norm(p.name) != norm(best.name)]
    return best, close


# --------------------------------------------------------------------------- spatial descriptions


def region(fmap: FloorMap, p: Point2D) -> str:
    b = fmap.bounds
    if b is None:
        return "map"
    fx = (p.x - b.min_x) / max(b.width, 1e-9)
    fy = (p.y - b.min_y) / max(b.depth, 1e-9)
    ns = "south" if fy < 1 / 3 else "north" if fy > 2 / 3 else ""
    ew = "west" if fx < 1 / 3 else "east" if fx > 2 / 3 else ""
    if ns and ew:
        return f"{ns}{ew} corner"
    if ns or ew:
        return f"{ns or ew} side"
    return "middle"


def direction_from(a: Point2D, b: Point2D) -> str:
    """Compass direction of b as seen from a."""
    return compass(math.degrees(math.atan2(b.y - a.y, b.x - a.x)))


def _neighbors(fmap: FloorMap, place: Place, limit: int, max_dist: float | None = None) -> list[tuple[Place, float]]:
    out = []
    for other in all_places(fmap):
        if other.id == place.id:
            continue
        if other.room is not None and point_in(place.position, other.room.polygon):
            continue  # the room that contains this place isn't a useful reference point
        d = math.dist(place.position.as_tuple(), other.position.as_tuple())
        if d < 0.5 or (max_dist is not None and d > max_dist):
            continue
        out.append((other, d))
    out.sort(key=lambda x: (x[0].landmark is None, x[1]))
    kept: list[tuple[Place, float]] = []
    for other, d in out:
        if other.room is not None and any(k.landmark is not None and point_in(k.position, other.room.polygon) for k, _ in kept):
            continue  # e.g. skip "Stairwell" once "Stairs" (inside it) is already listed
        kept.append((other, d))
    return kept[:limit]


def _route_origin(fmap: FloorMap, ctx: AskContext) -> str | None:
    for ref in (ctx.current_place_id, fmap.start_landmark_id):
        if ref and fmap.landmark_by_id(ref):
            return ref
    return None


def describe_place(fmap: FloorMap, place: Place, ctx: AskContext) -> str:
    parts = [f"{place.name} is on the {region(fmap, place.position)} of the map"]
    room = room_containing(fmap, place.position)
    if room and norm(_strip_qualifiers(room.name)) != norm(_strip_qualifiers(place.name)):
        parts[0] += f", inside {room.name}"
    parts[0] += "."
    refs = _neighbors(fmap, place, 2)
    if refs:
        rel = [f"{meters(d)} {direction_from(o.position, place.position)} of {o.name}" for o, d in refs]
        parts.append(f"It's {join_names(rel)}.")
    lm = place.landmark
    if lm is not None:
        if lm.description:
            parts.append(lm.description if lm.description.endswith(".") else lm.description + ".")
        if lm.source == "detected":
            parts.append("The scanner detected this, and nobody has confirmed it yet.")
        if lm.show_on_tactile and lm.type in SYMBOLS and fmap.tactile.include_landmarks:
            parts.append(f"On the tactile map it's the {SYMBOLS[lm.type]}.")
    return " ".join(parts)


def overview(fmap: FloorMap) -> str:
    b = fmap.bounds
    parts = [f"This is {fmap.name}."]
    if fmap.source.kind == "synthetic":
        parts.append("It's a made-up demo layout, not a scan of a real building.")
    if b is not None:
        parts.append(f"It's about {b.width:.0f} meters wide and {b.depth:.0f} meters deep, with north at the top of the map.")
    if fmap.rooms:
        parts.append(f"It has {len(fmap.rooms)} rooms or areas: {join_names([r.name for r in fmap.rooms])}.")
    by_type: dict[LandmarkType, list[str]] = {}
    for lm in fmap.landmarks:
        by_type.setdefault(lm.type, []).append(lm.name)
    for t, label in ((LandmarkType.entrance, "Entrances"), (LandmarkType.exit, "Exits")):
        if by_type.get(t):
            parts.append(f"{label}: {join_names(by_type[t])}.")
    others = [n for t, ns in by_type.items() if t not in (LandmarkType.entrance, LandmarkType.exit, LandmarkType.room, LandmarkType.hallway) for n in ns]
    if others:
        parts.append(f"Other landmarks: {join_names(others)}.")
    start = fmap.landmark_by_id(fmap.start_landmark_id) if fmap.start_landmark_id else None
    if start:
        parts.append(f"The starting point is {start.name}.")
    if not fmap.navigation.edges:
        parts.append("No walkable paths are recorded yet, so I can describe places but can't give directions.")
    return " ".join(parts)


# --------------------------------------------------------------------------- intent parsing


ROUTE_RE = re.compile(r"\b(how (do|can|would|should) i (get|go|reach|walk|find my way)|directions?|route|take me|"
                      r"guide me|navigate|lead me|way to|get (to|there)|go to|walk to|path to|get from)\b")
NEAR_RE = re.compile(r"\b(near|nearby|next to|close to|around|beside|by the)\b")
WHERE_RE = re.compile(r"\b(where|find|locate|how far)\b")
DESCRIBE_RE = re.compile(r"\b(describe|overview|tell me about|layout|what does .* look like|what is this|what s this|"
                         r"what is here|summar)\b")
LIST_RE = re.compile(r"\b(list|what (places|rooms|landmarks|destinations)|which (places|rooms)|what can i go|"
                     r"what is on (the|this) map|what s on (the|this) map|what s here)\b")
HELP_RE = re.compile(r"\b(help|what can (i|you) (ask|do|say)|how does this work)\b")
WHEREAMI_RE = re.compile(r"\bwhere am i\b")


@dataclass
class Parsed:
    intent: Intent
    target: str | None = None
    origin: str | None = None
    target_is_there: bool = False


def _after(pattern: str, q: str) -> str | None:
    m = re.search(pattern, q)
    return m.group(1).strip() if m and m.group(1).strip() else None


def parse(question: str) -> Parsed:
    q = norm(question)
    if not q:
        return Parsed("help")
    if WHEREAMI_RE.search(q):
        return Parsed("whereami")
    if HELP_RE.search(q) and not ROUTE_RE.search(q):
        return Parsed("help")
    if ROUTE_RE.search(q) or re.search(r"\bfrom .+ to .+", q):
        origin = _after(r"\bfrom (.+?)(?= to |$)", q)
        target = _after(r"\b(?:get|go|walk|way|directions|route|path|reach|take me|lead me|guide me|navigate)? ?to (.+?)(?= from |$)", q)
        there = bool(re.search(r"\b(get|go|walk|reach|back) there\b|\bthere from\b|\bto there\b", q))
        if target and target.startswith("there"):
            target, there = None, True
        if not target and not there:
            target = _after(r"\breach (.+?)(?= from |$)", q) or _after(r"\bfind my way to (.+?)(?= from |$)", q)
        return Parsed("route", target=target, origin=origin, target_is_there=there)
    if LIST_RE.search(q):
        return Parsed("list")
    if NEAR_RE.search(q) and not WHERE_RE.search(q.split(" near")[0] if " near" in q else ""):
        target = _after(r"\b(?:near|nearby|next to|close to|around|beside|by)\b (.+)$", q)
        return Parsed("nearby", target=target)
    if WHERE_RE.search(q):
        target = _after(r"\b(?:where (?:is|are|s|can i find|do i find)?|find|locate|how far is|how far)\b (.+)$", q)
        return Parsed("where", target=target)
    if DESCRIBE_RE.search(q):
        target = _after(r"\b(?:describe|tell me about)\b (.+)$", q)
        return Parsed("describe", target=target)
    return Parsed("unknown", target=q)


# --------------------------------------------------------------------------- answering


def _known_places_sentence(fmap: FloorMap) -> str:
    names = [lm.name for lm in fmap.landmarks] or [r.name for r in fmap.rooms]
    return f"Places I know: {join_names(names[:12])}." if names else "This map has no named places yet."


def answer(fmap: FloorMap, question: str, ctx: AskContext | None = None) -> AskResult:
    ctx = ctx or AskContext()
    p = parse(question)

    def result(text: str, intent: Intent, places: list[Place] = (), route: RouteResult | None = None,
               last: str | None = None, suggestions: list[str] | None = None) -> AskResult:
        new_ctx = ctx.model_copy(update={"last_place_id": last or ctx.last_place_id})
        return AskResult(answer=text, intent=intent, place_ids=[pl.id for pl in places], route=route, context=new_ctx,
                         safety_note=SAFETY_NOTE if route is not None and route.found else None,
                         suggestions=suggestions or [])

    def lookup(phrase: str | None, *, use_last: bool = False) -> tuple[Place | None, AskResult | None]:
        if (not phrase or use_last) and ctx.last_place_id:
            place = next((pl for pl in all_places(fmap) if pl.id == ctx.last_place_id), None)
            if place:
                return place, None
        if not phrase:
            return None, result(f"Which place do you mean? {_known_places_sentence(fmap)}", "clarify")
        best, close = resolve(fmap, phrase)
        if best is None:
            shown = " ".join(tokens(phrase)) or phrase
            return None, result(f"I couldn't find \"{shown}\" on this map. {_known_places_sentence(fmap)}", "clarify")
        if close:
            options = join_names([best.name, *[c.name for c in close]]).replace(" and ", " or ")
            return None, result(f"Did you mean {options}?", "clarify", [best, *close])
        return best, None

    if p.intent == "help":
        return result("You can ask me about this map. For example: " + " ".join(f'"{e}"' for e in EXAMPLES[:4]), "help",
                      suggestions=EXAMPLES)
    if p.intent == "whereami":
        origin = _route_origin(fmap, ctx)
        lm = fmap.landmark_by_id(origin) if origin else None
        text = "I can't track where you are; this map doesn't follow your position. "
        text += f"Your chosen starting point is {lm.name}." if lm else "Choose a starting point so I can give directions."
        return result(text, "whereami")
    if p.intent == "list":
        groups: dict[str, list[str]] = {}
        for lm in fmap.landmarks:
            groups.setdefault(lm.type.value, []).append(lm.name)
        if not groups:
            return result(_known_places_sentence(fmap), "list")
        text = "I know these places: " + join_names([n for ns in groups.values() for n in ns]) + "."
        return result(text, "list", suggestions=[f"Where is the {fmap.landmarks[0].name}?"])
    if p.intent in ("describe", "unknown") and (not p.target or p.intent == "describe"):
        if p.target and any(t not in GENERIC for t in tokens(p.target)):
            place, _ = resolve(fmap, p.target)
            if place:
                return result(describe_place(fmap, place, ctx), "describe", [place], last=place.id)
        if p.intent == "describe":
            return result(overview(fmap), "overview", suggestions=EXAMPLES[1:3])

    if p.intent == "where" or (p.intent == "unknown" and p.target):
        place, problem = lookup(p.target)
        if problem:
            if p.intent == "unknown":
                return result("I can answer questions about this map: where places are, what's nearby, directions "
                              "between places, or a description of the space. " + _known_places_sentence(fmap),
                              "unknown", suggestions=EXAMPLES)
            return problem
        text = describe_place(fmap, place, ctx)
        origin = _route_origin(fmap, ctx)
        if origin and origin != place.id and place.landmark is not None:
            try:
                r = plan_route(fmap, origin, place.id, avoid_stairs=ctx.avoid_stairs)
                if r.found:
                    text += f" From {r.origin_name}, it's {meters(r.distance_m)} along the recorded paths."
            except RoutingError:
                pass
        return result(text, "where", [place], last=place.id,
                      suggestions=["How do I get there?", f"What is near the {place.name}?"])

    if p.intent == "nearby":
        place, problem = lookup(p.target)
        if problem:
            return problem
        near = _neighbors(fmap, place, 4, max_dist=6.0)
        if not near:
            return result(f"Nothing else is marked within 6 meters of {place.name}.", "nearby", [place], last=place.id)
        items = [f"{o.name}, {meters(d)} to the {direction_from(place.position, o.position)}" for o, d in near]
        return result(f"Near {place.name}: " + "; ".join(items) + ".", "nearby", [place, *[o for o, _ in near]],
                      last=place.id)

    if p.intent == "route":
        dest, problem = lookup(p.target, use_last=p.target_is_there)
        if problem:
            return problem
        if p.origin:
            origin_place, problem = lookup(p.origin)
            if problem:
                return problem
            origin_id = origin_place.id
        else:
            origin_id = _route_origin(fmap, ctx)
            if origin_id is None:
                return result("Where are you starting from? Choose a starting point, or ask like "
                              "\"How do I get to the exit from the main entrance?\"", "clarify", [dest], last=dest.id)
        if dest.landmark is None or (origin_id and not fmap.landmark_by_id(origin_id)):
            return result(f"{dest.name} isn't linked to the walking paths, so I can't give directions to it.",
                          "route", [dest], last=dest.id)
        try:
            r = plan_route(fmap, origin_id, dest.id, avoid_stairs=ctx.avoid_stairs)
        except RoutingError as exc:
            return result(str(exc), "route", [dest], last=dest.id)
        if not r.found:
            return result(r.reason or "I couldn't find a route.", "route", [dest], route=r, last=dest.id)
        text = f"From {r.origin_name} to {r.destination_name} is {meters(r.distance_m)}. {r.spoken}"
        return result(text, "route", [dest], route=r, last=dest.id,
                      suggestions=[f"What is near the {dest.name}?", "Describe this room."])

    return result("I can answer questions about this map: where places are, what's nearby, directions between places, "
                  "or a description of the space. " + _known_places_sentence(fmap), "unknown", suggestions=EXAMPLES)
