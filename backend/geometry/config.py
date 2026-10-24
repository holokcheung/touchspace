"""All tunable numbers in one place. Model units are millimetres, scan units are metres."""

# --- Print geometry (mm) ---
SCALE = 50                 # 1:50 -> 1 m in the room becomes 20 mm on the map
WALL_THICKNESS_MM = 2.5    # fixed tactile width, NOT scaled from the real wall
WALL_HEIGHT_MM = 5.0       # how far walls rise above the base plate
BASE_THICKNESS_MM = 2.0    # thickness of the flat base plate
MARGIN_MM = 8.0            # empty border around the walls
MIN_DOOR_GAP_MM = 8.0      # door openings never get narrower than this (finger width)
OBJECT_HEIGHT_MM = 1.5     # furniture is a low bump, clearly lower than walls
BED_SIZE_MM = 256.0        # printer bed limit, used for a warning only

# --- Scan cleanup (metres / degrees) ---
ALIGN_TO_AXES = True       # rotate the whole scan so the main walls run along x and y
ORTHO_TOL_DEG = 5.0        # walls within this many degrees of 0/90 get snapped exactly
                           # (RoomPlan noise is ~1-2 deg; 5 keeps real 80-85 deg corners)
COLLINEAR_TOL_M = 0.15     # parallel wall pieces closer than this sideways are put on one line
SNAP_TOL_M = 0.25          # wall ends closer than this to another wall get extended to meet it
MIN_WALL_M = 0.10          # wall pieces shorter than this are scan noise and are removed
DOOR_SNAP_M = 0.30         # a door this close to a wall line is moved onto it

# --- What to show ---
INCLUDE_OBJECTS = True
# RoomPlan reports furniture only in its own fixed set of categories (bed, toilet, sink,
# table, sofa, storage, ...). Anything it does not recognise is simply left out of the
# JSON, so there is no "unknown" furniture to filter.
# We therefore KEEP every category by default and only drop the ones listed here.
# A category Apple adds in a future iOS version will show up automatically.
EXCLUDED_OBJECTS = {"chair"}   # small clutter that makes the map hard to read by touch
