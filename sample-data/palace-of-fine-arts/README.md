# Palace of Fine Arts reconstruction

The sample now retains interior geometry for the 3D walkthrough instead of reducing the building to its outer shell for the DotPad. Both application copies are generated from the same trace.

## References

- [Official PFA Master Floorplan](https://palaceoffinearts.com/wp-content/uploads/sites/4/2025/04/PFA-Master-Floorplan.pdf), accessed October 25, 2026. Page 1 supplies ground-floor walls, rooms and door locations. Page 3 shows a mezzanine; page 4 provides architectural/site context and the compass. This is the same source named by the old sample, but its interior detail was previously discarded.
- [Official venue presentation](https://palaceoffinearts.com/wp-content/uploads/sites/4/2024/09/Palace-of-Fine-Arts-Venue-Presentation.pdf) corroborates the arrangement of event spaces.
- Scale retains the earlier sample's approximate 273.8 m end-to-end span attributed to OpenStreetMap, © OpenStreetMap contributors ([ODbL](https://www.openstreetmap.org/copyright)). This is not a new survey or an independently verified dimension.

## What is reconstructed

The curved shell, divided circular Breakouts 1–2, rectangular Breakouts 3–4, angled Breakouts 5–6, service/restroom blocks, green rooms, staff office partitions, back-of-house strip and north entrance lobby are represented with walls and doorway gaps. Breakout 7 and Broadway remain open zones where the source shows no enclosing partition. Staff offices and Palace Games retain their restricted-area labels.

The drawing is traced manually using coordinates from page 1 rendered at 150% (1188 × 918). Page right becomes north; page down becomes east. The model uses meters with north up. See [reconstruction.svg](reconstruction.svg) for a generated overview in the source drawing's orientation. This overview is drawn from our model geometry, not a copy of the PDF.

## Limits

This is an approximate ground-floor reconstruction. Door centers and widths, small office divisions, and wall thicknesses are approximate. Shell heights of 8 m and partition heights of 3 m are illustrative, explicitly marked in wall metadata, and do not claim measured elevations. The mezzanine, stair geometry, theater seating, restroom fixtures, furniture and fine architectural detail are not reconstructed. Stair positions are landmarks only. The floor plan does not establish accessible routes or permission to enter restricted areas.

## Regenerate

From the repository root:

```sh
python3 sample-data/scripts/make_palace_of_fine_arts.py
```

This updates `sample-data/palace-of-fine-arts.json`, `frontend/standalone/maps/palace-of-fine-arts.json` and the SVG overview. The standard 3D walkthrough extrudes these walls and leaves the door gaps open. Reopen the Palace sample in the main app to create a fresh copy; previously saved maps keep their existing geometry.
