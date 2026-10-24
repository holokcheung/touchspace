# TouchSpace AI — Geometry backend

Turns an Apple RoomPlan JSON export into a 3D-printable tactile floor map (STL).

## Run

```
pip install -r requirements.txt
python main.py samples/test-roomplan.json -o map.stl
```

Results go to `output/`: `map.stl` (print it), `map_preview.png` (top-view check) and
`map_labels.json` (room names with map coordinates in mm, for the frontend and voice).

## Folders

| Path | What it is |
|---|---|
| `main.py` | Runs the pipeline. |
| `parse.py` | RoomPlan JSON -> walls, doors, objects, room labels. Only file that knows the JSON format. |
| `clean.py` | Fixes scan errors: rotation, crooked walls, corner gaps, split walls, misplaced doors. |
| `plan.py` | Builds the 2D tactile plan (fixed wall width, minimum door gap). |
| `model.py` | Extrudes the plan into 3D and saves the STL. |
| `config.py` | All tunable numbers (scale, heights, tolerances, excluded furniture). |
| `samples/` | Example scans. `test-roomplan.json` is a real RoomPlan export (backup for demos). |
| `tests/` | Self-checks and test-data generators. |
| `output/` | Generated results (not committed). |

## Tests

```
python tests/check_pipeline.py      # core checks on the samples
python tests/test_edge_cases.py     # 16 broken-scan cases (created automatically)
python tests/make_random_room.py    # a new random messy flat to try
```

## Credits

`samples/test-roomplan.json` is a sample RoomPlan export from
[openPlan3D](https://github.com/laanlabs/openPlan3D) (MIT License). See their LICENSE file for the copyright notice.
