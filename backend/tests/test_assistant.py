from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.services.assistant import AskContext, answer, match_places, parse
from app.services.floorplan import process_map
from app.services.storage import MapStore
from tests.conftest import REPO_ROOT


@pytest.fixture
def demo(demo_map):
    return process_map(demo_map).map


# --------------------------------------------------------------------------- the demo script


def test_demo_conversation(demo):
    """The exact questions from the pitch, in order, with a follow-up that depends on context."""
    r1 = answer(demo, "Where is the restroom?")
    assert r1.intent == "where" and r1.place_ids == ["lm_restroom"]
    assert "Restroom is on the north side of the map" in r1.answer
    assert "solid circle" in r1.answer  # ties the answer to the printed map
    assert "about 12 meters along the recorded paths" in r1.answer

    r2 = answer(demo, "How do I get there from the main entrance?", r1.context)
    assert r2.intent == "route" and r2.route is not None and r2.route.found
    assert r2.route.origin_name == "Main Entrance" and r2.route.destination_name == "Restroom"
    assert r2.safety_note and "cane" in r2.safety_note
    assert r2.answer.startswith("From Main Entrance to Restroom is about 12 meters.")


@pytest.mark.parametrize("question", ["Describe this room.", "Describe the building", "Give me an overview"])
def test_overview_questions(demo, question):
    r = answer(demo, question)
    assert r.intent == "overview"
    assert "made-up demo layout" in r.answer  # never presented as a real scan
    assert "Main Entrance" in r.answer and "Exit" in r.answer


def test_nearby_lists_real_neighbors_with_directions(demo):
    r = answer(demo, "What is near the entrance?")
    assert r.intent == "nearby"
    assert "Information Desk, about 2.5 meters to the northeast" in r.answer
    assert "Stairwell" not in r.answer  # its Stairs landmark is already listed


def test_route_between_two_named_places(demo):
    r = answer(demo, "How do I get from the entrance to the exit?")
    assert r.route.found and r.route.origin_name == "Main Entrance" and r.route.destination_name == "Exit"


# --------------------------------------------------------------------------- understanding


@pytest.mark.parametrize("phrase,expected", [
    ("bathroom", "lm_restroom"), ("toilet", "lm_restroom"), ("lift", "lm_elevator"),
    ("info desk", "lm_info"), ("reception", "lm_info"), ("staircase", "lm_stairs"),
    ("front door", "lm_entrance"), ("way out", "lm_exit"), ("meeting room", "lm_meeting"),
    ("study room", "lm_study"), ("studdy room b", "lm_study"), ("restrom", "lm_restroom"),
])
def test_place_matching_handles_synonyms_and_slips(demo, phrase, expected):
    assert match_places(demo, phrase)[0][0].id == expected


def test_parse_routes():
    p = parse("How do I get to the restroom from the entrance?")
    assert (p.intent, p.target, p.origin) == ("route", "the restroom", "the entrance")
    p = parse("how do i get from the lobby to the exit")
    assert (p.intent, p.target, p.origin) == ("route", "the exit", "the lobby")
    p = parse("How do I get there from the main entrance?")
    assert p.intent == "route" and p.target_is_there and p.origin == "the main entrance"
    assert parse("take me to the lift").target == "the lift"


def test_unknown_place_lists_what_is_known(demo):
    r = answer(demo, "Where is the kitchen?")
    assert r.intent == "clarify"
    assert 'couldn\'t find "kitchen"' in r.answer and "Places I know:" in r.answer


def test_off_topic_question_is_not_answered_with_made_up_facts(demo):
    r = answer(demo, "What's the weather like?")
    assert r.intent == "unknown" and r.place_ids == []
    assert "I can answer questions about this map" in r.answer


def test_where_am_i_does_not_claim_tracking(demo):
    r = answer(demo, "Where am I?")
    assert "can't track where you are" in r.answer and "Main Entrance" in r.answer


def test_route_without_any_start_asks_for_one(demo):
    demo.start_landmark_id = None
    r = answer(demo, "How do I get to the exit?")
    assert r.intent == "clarify" and "Where are you starting from?" in r.answer


def test_chosen_current_place_is_used_as_origin(demo):
    r = answer(demo, "How do I get to the exit?", AskContext(current_place_id="lm_study"))
    assert r.route.origin_name == "Study Room B"


def test_no_recorded_paths_means_no_directions(demo):
    demo.navigation.edges = []
    r = answer(demo, "How do I get to the exit?")
    assert r.route is not None and not r.route.found
    assert "no recorded walkable path" in r.answer
    assert r.safety_note is None


def test_ambiguous_names_ask_which_one():
    data = json.loads((REPO_ROOT / "sample-data/third-party/open3dfloorplan-test-roomplan.json").read_text())
    from app.services.importers import import_scan
    fmap = process_map(import_scan(data).map).map
    r = answer(fmap, "Where is the bedroom?")
    assert r.intent == "clarify" and "Did you mean" in r.answer and "Bedroom 2" in r.answer
    assert answer(fmap, "Where is bedroom 1?").place_ids == ["lm_area_bedroom1"]
    # Imported scans have no walking paths yet: no invented directions.
    r = answer(fmap, "How do I get to the bathroom?", AskContext(current_place_id=fmap.landmarks[0].id))
    assert "can't" in r.answer.lower() or "no recorded" in r.answer.lower()
    assert r.route is None or not r.route.found


def test_detected_landmarks_are_flagged_as_unconfirmed():
    data = json.loads((REPO_ROOT / "sample-data/third-party/open3dfloorplan-test-roomplan.json").read_text())
    from app.services.importers import import_scan
    fmap = process_map(import_scan(data).map).map
    r = answer(fmap, "Where is the bathroom?")
    assert "nobody has confirmed it yet" in r.answer


# --------------------------------------------------------------------------- API


def test_ask_api_keeps_conversation_context(tmp_path):
    store = MapStore(tmp_path)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        map_id = client.post("/api/demo").json()["map"]["id"]
        first = client.post(f"/api/maps/{map_id}/ask", json={"question": "Where is the restroom?"}).json()
        assert first["context"]["last_place_id"] == "lm_restroom"
        second = client.post(f"/api/maps/{map_id}/ask",
                             json={"question": "How do I get there?", "context": first["context"]}).json()
        assert second["route"]["found"] and second["route"]["destination_name"] == "Restroom"
        assert second["route"]["spoken"].startswith("Start at Main Entrance.")
        assert client.post(f"/api/maps/{map_id}/ask", json={"question": ""}).status_code == 422
        assert client.post("/api/maps/none-1234/ask", json={"question": "hi"}).status_code == 404
    finally:
        app.dependency_overrides.clear()
