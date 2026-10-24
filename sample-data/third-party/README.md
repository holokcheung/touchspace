# Third-party sample data

## `open3dfloorplan-test-roomplan.json`

- **Source:** [`test-roomplan.json`](https://github.com/RL-Z3D/open3dFloorplan-v1/blob/main/test-roomplan.json) from [RL-Z3D/open3dFloorplan-v1](https://github.com/RL-Z3D/open3dFloorplan-v1), at commit `fca8ff6752be5622a36c13faa4f7886d524c7b92`.
- **License:** MIT, © 2026 theLodgeStudio. The full text is in [`open3dfloorplan-LICENSE`](open3dfloorplan-LICENSE).
- **SHA-256:** `a6af4fa3e67f9e8d26ce652d07d0a461330b6e744bedfc663810a4b0441dad2c`. Unmodified copy.
- **Contents:** 20 walls, 4 doors, 4 windows, 0 openings, 13 objects, 1 floor, 4 sections.

**Provenance:** the file has the full structure of Apple's `CapturedRoom` encoding, including the opaque `coreModel` blob and `referenceOriginTransform`, which strongly suggests real `JSONEncoder` output from a RoomPlan scan. The source repository doesn't say who scanned it or where, and we have not verified that. It is **not** a scan made by the TouchSpace team, and not a Cal Hacks venue. Describe it as "a public RoomPlan export from another open-source project" in demos.

It is used as a regression fixture in `backend/tests/test_roomplan.py`.
