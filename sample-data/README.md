# Sample data provenance

## `roomplan-real-sample.json`

- Source repository: https://github.com/RL-Z3D/open3dFloorplan-v1
- Original file: https://github.com/RL-Z3D/open3dFloorplan-v1/blob/main/test-roomplan.json
- Download URL: https://raw.githubusercontent.com/RL-Z3D/open3dFloorplan-v1/main/test-roomplan.json
- SHA-256: `a6af4fa3e67f9e8d26ce652d07d0a461330b6e744bedfc663810a4b0441dad2c`
- Top-level structural arrays in the copied file: 20 walls, 4 doors, 4 windows, 0 openings, 13 objects, 1 floor.

The file uses the serialized `CapturedRoom`-style structure (including category, confidence, dimensions, identifier, and 16-number transform fields). The source repository and public file make it a real external fixture, but do not establish that the JSON was emitted directly by Apple's `JSONEncoder` from a physical LiDAR scan. Keep that provenance caveat with demonstrations and reports. The integration test treats this downloaded copy as immutable and checks the expected array counts.

## `demo-building.json`

This is synthetic demo data authored for the project. It contains example landmarks and explicitly traversable graph edges so the route planner can be demonstrated without claiming the public scan contains semantic destinations or safe paths.
