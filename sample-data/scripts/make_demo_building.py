"""Write sample-data/demo-building.json, the synthetic TouchSpace demo floor.

This layout is invented for demonstration. It is not a scan of any real
building (including the Cal Hacks venue).

Layout (meters, plan y up), 16 m x 10 m:

    y=10 +-----------+--------+---------------+
         | Meeting   |Restroom| Study Room B  |
         | Room A    |        |               |
    y=6  +----d------+---d----+-----d---------+
         |  Central Hallway                   d  <- Exit (east wall)
    y=4  +--opening--+--d--+-d-+------d-------+
         |   Lobby    |Stair|Elev| Storage    |
         |  (info)    |well |    |            |
    y=0  +-----d------+-----+----+------------+
               ^ Main Entrance

Run from the repo root:  python sample-data/scripts/make_demo_building.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "demo-building.json"

EXTERIOR = 0.25
INTERIOR = 0.12


def pt(x: float, y: float) -> dict:
    return {"x": x, "y": y}


def build() -> dict:
    walls: list[dict] = []

    def wall(wid: str, x1: float, y1: float, x2: float, y2: float, thickness: float) -> None:
        walls.append({"id": wid, "start": pt(x1, y1), "end": pt(x2, y2), "thickness": thickness, "height": 2.7})

    # Exterior shell
    wall("w_south", 0, 0, 16, 0, EXTERIOR)
    wall("w_east", 16, 0, 16, 10, EXTERIOR)
    wall("w_north", 16, 10, 0, 10, EXTERIOR)
    wall("w_west", 0, 10, 0, 0, EXTERIOR)
    # Hallway south side (y=4), split where the south rooms meet it
    wall("w_hall_s_lobby", 0, 4, 7, 4, INTERIOR)
    wall("w_hall_s_stairs", 7, 4, 10, 4, INTERIOR)
    wall("w_hall_s_elevator", 10, 4, 12, 4, INTERIOR)
    wall("w_hall_s_storage", 12, 4, 16, 4, INTERIOR)
    # Hallway north side (y=6)
    wall("w_hall_n_meeting", 0, 6, 6, 6, INTERIOR)
    wall("w_hall_n_restroom", 6, 6, 9, 6, INTERIOR)
    wall("w_hall_n_study", 9, 6, 16, 6, INTERIOR)
    # Partitions between rooms
    wall("w_meeting_restroom", 6, 6, 6, 10, INTERIOR)
    wall("w_restroom_study", 9, 6, 9, 10, INTERIOR)
    wall("w_lobby_stairs", 7, 0, 7, 4, INTERIOR)
    wall("w_stairs_elevator", 10, 0, 10, 4, INTERIOR)
    wall("w_elevator_storage", 12, 0, 12, 4, INTERIOR)

    doors = [
        {"id": "d_main_entrance", "position": pt(3.5, 0), "width": 1.6, "wall_id": "w_south"},
        {"id": "d_exit", "position": pt(16, 5), "width": 1.0, "wall_id": "w_east"},
        {"id": "d_meeting", "position": pt(4.5, 6), "width": 1.0, "wall_id": "w_hall_n_meeting"},
        {"id": "d_restroom", "position": pt(7.5, 6), "width": 0.9, "wall_id": "w_hall_n_restroom"},
        {"id": "d_study", "position": pt(11.0, 6), "width": 1.0, "wall_id": "w_hall_n_study"},
        {"id": "d_stairs", "position": pt(8.5, 4), "width": 1.0, "wall_id": "w_hall_s_stairs"},
        {"id": "d_elevator", "position": pt(11.0, 4), "width": 1.1, "wall_id": "w_hall_s_elevator"},
        {"id": "d_storage", "position": pt(14.0, 4), "width": 0.9, "wall_id": "w_hall_s_storage"},
    ]
    openings = [
        {"id": "o_lobby_hall", "position": pt(3.0, 4), "width": 3.0, "wall_id": "w_hall_s_lobby"},
    ]
    windows = [
        {"id": "win_meeting", "position": pt(3.0, 10), "width": 2.0, "wall_id": "w_north"},
        {"id": "win_study", "position": pt(12.5, 10), "width": 2.0, "wall_id": "w_north"},
    ]

    def obj(oid: str, category: str, x: float, y: float, w: float, d: float, h: float, *, rot: float = 0.0,
            label: str | None = None, tactile: bool = False) -> dict:
        return {"id": oid, "category": category, "position": pt(x, y), "width": w, "depth": d, "height": h,
                "rotation": rot, "label": label, "include_in_tactile": tactile}

    objects = [
        obj("obj_meeting_table", "table", 3.0, 8.2, 2.4, 1.1, 0.75, label="Meeting table", tactile=True),
        obj("obj_meeting_chair_1", "chair", 2.2, 7.3, 0.5, 0.5, 0.9),
        obj("obj_meeting_chair_2", "chair", 3.8, 7.3, 0.5, 0.5, 0.9),
        obj("obj_meeting_chair_3", "chair", 2.2, 9.1, 0.5, 0.5, 0.9),
        obj("obj_meeting_chair_4", "chair", 3.8, 9.1, 0.5, 0.5, 0.9),
        obj("obj_info_desk", "table", 5.6, 1.4, 1.8, 0.8, 1.05, label="Information desk counter"),
        obj("obj_lobby_sofa", "sofa", 1.3, 1.6, 0.9, 2.0, 0.8),
        obj("obj_toilet", "toilet", 8.4, 9.4, 0.4, 0.7, 0.8),
        obj("obj_sink", "sink", 6.5, 8.0, 0.5, 0.6, 0.9, rot=1.5708),
        obj("obj_stairs", "stairs", 8.5, 1.9, 1.4, 2.8, 3.0),
        obj("obj_study_desk_1", "table", 11.5, 9.3, 1.6, 0.7, 0.75),
        obj("obj_study_desk_2", "table", 14.2, 9.3, 1.6, 0.7, 0.75),
        obj("obj_storage_shelf", "storage", 15.5, 2.0, 0.5, 3.0, 2.0),
    ]

    rooms = [
        {"id": "r_lobby", "name": "Lobby", "polygon": [pt(0, 0), pt(7, 0), pt(7, 4), pt(0, 4)]},
        {"id": "r_stairwell", "name": "Stairwell", "polygon": [pt(7, 0), pt(10, 0), pt(10, 4), pt(7, 4)]},
        {"id": "r_elevator", "name": "Elevator", "polygon": [pt(10, 0), pt(12, 0), pt(12, 4), pt(10, 4)]},
        {"id": "r_storage", "name": "Storage", "polygon": [pt(12, 0), pt(16, 0), pt(16, 4), pt(12, 4)]},
        {"id": "r_hallway", "name": "Central Hallway", "polygon": [pt(0, 4), pt(16, 4), pt(16, 6), pt(0, 6)]},
        {"id": "r_meeting", "name": "Meeting Room A", "polygon": [pt(0, 6), pt(6, 6), pt(6, 10), pt(0, 10)]},
        {"id": "r_restroom", "name": "Restroom", "polygon": [pt(6, 6), pt(9, 6), pt(9, 10), pt(6, 10)]},
        {"id": "r_study", "name": "Study Room B", "polygon": [pt(9, 6), pt(16, 6), pt(16, 10), pt(9, 10)]},
    ]

    nodes: list[dict] = []

    def node(nid: str, x: float, y: float, *, label: str | None = None, kind: str = "place",
             room: str | None = None, landmark: str | None = None) -> None:
        nodes.append({"id": nid, "position": pt(x, y), "label": label, "kind": kind,
                      "room_id": room, "landmark_id": landmark})

    node("n_entrance", 3.5, 0.6, label="Inside the main entrance", room="r_lobby", landmark="lm_entrance")
    node("n_lobby", 3.2, 2.2, label="Lobby", room="r_lobby")
    node("n_info", 5.4, 2.4, label="In front of the information desk", room="r_lobby", landmark="lm_info")
    node("n_hall_lobby", 3.0, 5.0, label="Hallway, at the lobby opening", kind="junction", room="r_hallway")
    node("n_hall_meeting", 4.5, 5.0, label="Hallway, outside Meeting Room A", kind="junction", room="r_hallway")
    node("n_hall_restroom", 7.5, 5.0, label="Hallway, outside the restroom", kind="junction", room="r_hallway")
    node("n_hall_stairs", 8.5, 5.0, label="Hallway, outside the stairwell", kind="junction", room="r_hallway")
    node("n_hall_study", 11.0, 5.0, label="Hallway, between Study Room B and the elevator", kind="junction", room="r_hallway")
    node("n_hall_storage", 14.0, 5.0, label="Hallway, outside storage", kind="junction", room="r_hallway")
    node("n_exit", 15.6, 5.0, label="At the exit door", room="r_hallway", landmark="lm_exit")
    node("n_door_meeting", 4.5, 6.0, label="Meeting Room A door", kind="door")
    node("n_meeting", 4.6, 7.4, label="Meeting Room A", room="r_meeting", landmark="lm_meeting")
    node("n_door_restroom", 7.5, 6.0, label="Restroom door", kind="door")
    node("n_restroom", 7.5, 7.6, label="Restroom", room="r_restroom", landmark="lm_restroom")
    node("n_door_study", 11.0, 6.0, label="Study Room B door", kind="door")
    node("n_study", 12.5, 7.8, label="Study Room B", room="r_study", landmark="lm_study")
    node("n_door_stairs", 8.5, 4.0, label="Stairwell door", kind="door")
    node("n_stairs", 8.5, 3.5, label="Bottom of the stairs", room="r_stairwell", landmark="lm_stairs")
    node("n_door_elevator", 11.0, 4.0, label="Elevator door", kind="door")
    node("n_elevator", 11.0, 2.8, label="Elevator", room="r_elevator", landmark="lm_elevator")
    node("n_door_storage", 14.0, 4.0, label="Storage door", kind="door")
    node("n_storage", 14.0, 2.5, label="Storage", room="r_storage")

    pairs = [
        ("n_entrance", "n_lobby"), ("n_lobby", "n_info"), ("n_lobby", "n_hall_lobby"),
        ("n_hall_lobby", "n_hall_meeting"), ("n_hall_meeting", "n_hall_restroom"),
        ("n_hall_restroom", "n_hall_stairs"), ("n_hall_stairs", "n_hall_study"),
        ("n_hall_study", "n_hall_storage"), ("n_hall_storage", "n_exit"),
        ("n_hall_meeting", "n_door_meeting"), ("n_door_meeting", "n_meeting"),
        ("n_hall_restroom", "n_door_restroom"), ("n_door_restroom", "n_restroom"),
        ("n_hall_study", "n_door_study"), ("n_door_study", "n_study"),
        ("n_hall_stairs", "n_door_stairs"), ("n_door_stairs", "n_stairs"),
        ("n_hall_study", "n_door_elevator"), ("n_door_elevator", "n_elevator"),
        ("n_hall_storage", "n_door_storage"), ("n_door_storage", "n_storage"),
    ]
    edges = [{"id": f"e_{a[2:]}__{b[2:]}", "a": a, "b": b, "source": "synthetic"} for a, b in pairs]

    def landmark(lid: str, name: str, ltype: str, x: float, y: float, node_id: str, description: str) -> dict:
        return {"id": lid, "name": name, "type": ltype, "position": pt(x, y), "nav_node_id": node_id,
                "description": description, "source": "synthetic"}

    landmarks = [
        landmark("lm_entrance", "Main Entrance", "entrance", 3.5, 0.6, "n_entrance",
                 "Double-width door in the middle of the south wall of the lobby."),
        landmark("lm_info", "Information Desk", "information", 5.6, 2.2, "n_info",
                 "Staffed counter on the east side of the lobby."),
        landmark("lm_hallway", "Central Hallway", "hallway", 8.0, 5.0, "n_hall_restroom",
                 "Two-meter-wide corridor running east to west across the building."),
        landmark("lm_meeting", "Meeting Room A", "room", 3.0, 8.0, "n_meeting",
                 "Room with a large central table and four chairs."),
        landmark("lm_restroom", "Restroom", "restroom", 7.5, 7.6, "n_restroom",
                 "Single restroom on the north side of the hallway."),
        landmark("lm_study", "Study Room B", "room", 12.5, 8.0, "n_study",
                 "Quiet room with two desks along the north wall."),
        landmark("lm_stairs", "Stairs", "stairs", 8.5, 2.6, "n_stairs",
                 "Stairwell entered from the south side of the hallway."),
        landmark("lm_elevator", "Elevator", "elevator", 11.0, 2.4, "n_elevator",
                 "Elevator entered from the south side of the hallway."),
        landmark("lm_exit", "Exit", "exit", 15.6, 5.0, "n_exit",
                 "Door at the east end of the hallway."),
    ]

    return {
        "schema_version": "1.0",
        "id": "demo-building",
        "name": "TouchSpace Demo Building (synthetic)",
        "units": "meters",
        "source": {
            "kind": "synthetic",
            "description": "Invented single-floor layout for demonstrating TouchSpace. Not a scan of a real place.",
        },
        "floor_level": 0,
        "walls": walls,
        "doors": doors,
        "openings": openings,
        "windows": windows,
        "objects": objects,
        "rooms": rooms,
        "landmarks": landmarks,
        "navigation": {"nodes": nodes, "edges": edges},
        "start_landmark_id": "lm_entrance",
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
