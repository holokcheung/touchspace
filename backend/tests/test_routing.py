from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.models import NavEdge
from app.services.routing import RoutingError, plan_route, shortest_path, build_graph, turn_phrase
from app.services.storage import MapStore


def test_valid_route_is_shortest_over_recorded_paths(demo_map):
    r = plan_route(demo_map, "lm_entrance", "lm_restroom")
    assert r.found
    assert r.node_ids[0] == "n_entrance" and r.node_ids[-1] == "n_restroom"
    assert "n_door_restroom" in r.node_ids, "must go through the restroom doorway"
    # distance is the sum of the recorded edges actually walked
    nodes = {n.id: n.position for n in demo_map.navigation.nodes}
    walked = sum(math.dist(nodes[a].as_tuple(), nodes[b].as_tuple()) for a, b in zip(r.node_ids, r.node_ids[1:]))
    assert r.distance_m == pytest.approx(walked, abs=0.01)


def test_every_route_step_follows_a_recorded_edge(demo_map):
    edges = {frozenset((e.a, e.b)) for e in demo_map.navigation.edges}
    for dest in ("lm_exit", "lm_study", "lm_elevator", "lm_info", "lm_stairs"):
        r = plan_route(demo_map, "lm_entrance", dest)
        assert r.found
        for a, b in zip(r.node_ids, r.node_ids[1:]):
            assert frozenset((a, b)) in edges, f"{a}->{b} is not a recorded path"


def test_instructions_are_derived_from_the_path(demo_map):
    r = plan_route(demo_map, "lm_entrance", "lm_restroom")
    text = r.spoken
    assert text.startswith("Start at Main Entrance.")
    assert "Head north, toward the top of the map" in text  # first leg: entrance -> hallway goes up the map
    assert "Turn right" in text  # facing north, the hallway east is to the right
    assert "Meeting Room A door on your left" in text  # north side of the hallway while walking east
    assert "Restroom door, then go through it" in text
    assert text.rstrip().endswith("You'll reach Restroom.")
    # Each walking step's distance adds up to the total.
    assert sum(s.distance_m for s in r.steps) == pytest.approx(r.distance_m, abs=0.05)


def test_disconnected_destination_reports_no_route(demo_map):
    demo_map.navigation.edges = [e for e in demo_map.navigation.edges if "n_door_storage" not in (e.a, e.b)]
    r = plan_route(demo_map, "lm_entrance", "n_storage")
    assert not r.found and r.steps == [] and r.node_ids == []
    assert "no recorded walkable path" in r.reason


def test_untraversable_edges_are_not_used(demo_map):
    for e in demo_map.navigation.edges:
        if {e.a, e.b} == {"n_hall_restroom", "n_door_restroom"}:
            e.traversable = False
    assert not plan_route(demo_map, "lm_entrance", "lm_restroom").found


def test_avoid_stairs_routes_around_stair_nodes(demo_map):
    # Add a shortcut that goes through the stairs: it must be skipped when avoiding stairs.
    demo_map.navigation.edges.append(NavEdge(id="e_shortcut_a", a="n_info", b="n_stairs"))
    demo_map.navigation.edges.append(NavEdge(id="e_shortcut_b", a="n_stairs", b="n_hall_study"))
    direct = plan_route(demo_map, "lm_info", "lm_elevator")
    assert "n_stairs" in direct.node_ids
    avoiding = plan_route(demo_map, "lm_info", "lm_elevator", avoid_stairs=True)
    assert avoiding.found and "n_stairs" not in avoiding.node_ids
    assert avoiding.distance_m > direct.distance_m


def test_avoid_stairs_explains_when_only_stairs_connect(demo_map):
    for e in demo_map.navigation.edges:
        if e.id == "e_hall_lobby__hall_meeting":
            e.accessibility = "has_steps"
    r = plan_route(demo_map, "lm_entrance", "lm_exit", avoid_stairs=True)
    assert not r.found and "uses stairs" in r.reason
    assert plan_route(demo_map, "lm_entrance", "lm_exit").found


def test_same_start_and_end(demo_map):
    r = plan_route(demo_map, "lm_exit", "lm_exit")
    assert r.found and r.spoken == "You're already at Exit."


def test_unknown_or_unlinked_places_are_errors(demo_map):
    with pytest.raises(RoutingError, match="not a known place"):
        plan_route(demo_map, "lm_entrance", "lm_nowhere")
    demo_map.landmarks[1].nav_node_id = None
    for n in demo_map.navigation.nodes:
        if n.landmark_id == demo_map.landmarks[1].id:
            n.landmark_id = None
    with pytest.raises(RoutingError, match="isn't linked"):
        plan_route(demo_map, "lm_entrance", demo_map.landmarks[1].id)


def test_turn_words():
    assert turn_phrase(5) is None
    assert turn_phrase(40) == "bear left"
    assert turn_phrase(-90) == "turn right"
    assert turn_phrase(170) == "turn around"


def test_dijkstra_prefers_shorter_total_distance(demo_map):
    graph = build_graph(demo_map)
    path, length = shortest_path(graph, "n_hall_lobby", "n_exit")
    assert path[0] == "n_hall_lobby" and path[-1] == "n_exit"
    assert length == pytest.approx(15.6 - 3.0, abs=0.01)  # straight down the hallway


@pytest.fixture
def client(tmp_path):
    store = MapStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_api(client):
    map_id = client.post("/api/demo").json()["map"]["id"]
    r = client.post(f"/api/maps/{map_id}/route", json={"origin": "lm_entrance", "destination": "lm_exit"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] and body["spoken"].startswith("Start at Main Entrance.")
    assert "cane" in body["safety_note"]
    assert len(body["points"]) == len(body["node_ids"])
    bad = client.post(f"/api/maps/{map_id}/route", json={"origin": "lm_entrance", "destination": "nope"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unroutable"
    missing = client.post("/api/maps/none-1234/route", json={"origin": "a", "destination": "b"})
    assert missing.status_code == 404
