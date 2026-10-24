# Soundscape: hearing walls before you reach them

The **Walk-through** tab (`/maps/{id}/walk`) lets someone practice walking through a mapped building with headphones. A soft noise plays in each ear. When a wall or piece of furniture is close on one side, that ear's noise gets muffled, as if the wall were blocking it. Soft ticks mean something is in your path, and they speed up as it gets closer.

It's **simulated from the map**, not live sensing. It only knows what's on the map: no people, open or closed doors, or moved furniture. The same sound design is meant for a later live iPhone version using LiDAR (see below).

## Controls

| Action | Keyboard (focus the walk area) | Touch |
| --- | --- | --- |
| Step forward / back (25 cm) | Up / Down arrow, or W / S | Forward / Back (hold to keep walking) |
| Turn 15° | Left / Right arrow, or A / D | Turn left / Turn right |
| Turn 90° | Shift + Left / Right | Left 90° / Right 90° |
| Turn around | T | Turn around |
| What's around me? | Space or Enter | What's around me? |

Spoken announcements (optional, Cartesia voice when configured):
- walking through a door ("Through the door, into Restroom");
- entering a room;
- coming within 1.2 m of a landmark ("Restroom, 1 meter ahead on your left");
- the compass direction when it changes;
- bumping into something ("Wall ahead"; the bump sound repeats, the words don't).

## The sound, and why

| What you hear | Means |
| --- | --- |
| Pink noise, the same in both ears | Nothing close on either side |
| One ear muffled (duller and a little quieter) | A surface on that side, closer than 2.5 m; fully muffled at 0.3 m |
| Soft ticks in both ears, getting faster | Something in your path within 2 m |
| Low thud (plus vibration on Android) | You bumped into something |
| Two rising notes | You walked through a doorway |
| Noise stops, two falling notes every 2 seconds | **No information here** (outside the map) |

Design choices:
- **Silence never means anything.** Silence could mean either "open space" or "the app stopped working", so lost information gets its own repeating cue instead.
- **Pink noise, not white.** It's softer on the ears over long periods.
- **Each ear gets its own independent noise**, so the sound feels wide rather than coming from the middle of your head.
- **A narrow "ahead" zone** (±12°, about body width at 2 m), so it means "in my path", not "somewhere in front".
- **Low volume by default**, and the page says to keep it low enough to hear the room. Use open-ear or bone-conduction headphones, or AirPods in transparency mode. The app only changes its own sound; it never blocks real-world sound.

## Shared settings: `shared/soundscape.json`

All the numbers live in one file, read by both the web app and the iPhone app:

| Section | What it sets |
| --- | --- |
| `zones` | Left / ahead / right as angle ranges (0° = straight ahead, positive = right) |
| `sensing` | Range and ray spacing on the web; `lidar_camera_zones` is the phone's version: slices of the depth image, plus a confidence floor and a staleness timeout |
| `noise` | Level, default volume, smoothing time |
| `muffle` | Distance → low-pass cutoff (log scale) and gain, with a curve |
| `ahead_pulse` | Distance → tick rate |
| `cues` | Bump, doorway, no-data: notes, length, vibration, repeat |
| `walk` | Step size, turn angles, body radius (web only) |

The formulas:
- **Muffling:**
  - `t = clamp((open_at − d) / (open_at − muffled_at), 0, 1)` and `amount = t^curve`
  - `cutoff = open_cutoff × (muffled_cutoff / open_cutoff)^amount`
  - `gain = open_gain + (muffled_gain − open_gain) × amount`
- **Ticks:** linear from `slowest_hz` at `start_at_m` to `fastest_hz` at `fastest_at_m`; none beyond `start_at_m`.

Code:
- **Web logic:** `frontend/src/lib/soundscape.ts` (sensing, walking, muffle and tick formulas).
- **Web audio:** `frontend/src/lib/soundscapeAudio.ts` (Web Audio).
- **iPhone:** `ios-scanner/TouchSpaceScanner/SoundscapeSettings.swift`. It decodes the same file, which is bundled into the app, and has the same two formulas.
  - The Swift file was compiled with the command-line Swift compiler and run against the real JSON. Its numbers match the TypeScript exactly.
  - It hasn't been built inside the iOS app yet (no Xcode here).

## Using it on a phone

1. On the Mac, run the frontend so other devices can reach it:
   ```bash
   cd frontend && npm run dev -- --host 0.0.0.0
   ```
   Vite prints a `Network:` address.
2. Put the phone on the same Wi-Fi network and open that address, for example `http://192.168.x.x:5173`. Venue Wi-Fi often blocks devices from reaching each other; a phone hotspot that the Mac joins works around that.
3. Open a map, then the **Walk-through** tab. Put on headphones and tap **Start sound**.

On iPhone, the page asks Safari to play through the silent switch. Vibration isn't available in iPhone Safari, so cues are sound only there.

The Voice Explorer's microphone needs HTTPS, so it won't work from a phone over plain `http://`. The walk-through doesn't need the microphone.

## The live iPhone version (not built yet)

The plan for live sensing, using the same settings:
1. **Depth:** run ARKit with `frameSemantics = .sceneDepth` on a LiDAR iPhone.
2. **Zones:**
   - For each frame, split the depth map into `lidar_camera_zones` slices.
   - Drop pixels below `min_confidence`.
   - Take a low percentile of depth in each slice, rather than the single minimum, to ignore noise.
3. **Ears:** give each ear its own noise source in `AVAudioEngine`, each through a low-pass filter (`AVAudioUnitEQ`). Set them with `SoundscapeSettings.muffle(forDistance:)` and smooth over `smoothing_s`.
4. **Ticks:** schedule them with `pulseRate(forDistance:)`.
5. **Lost tracking:** if tracking is limited or no fresh depth has arrived for `stale_after_s`, fade the noise and play the `no_data` cue. Never fall silent.
6. **Optional:** use ARKit's mesh classification to tell doors from walls for announcements.

The camera only sees about 60° ahead. On the phone, "left" and "right" mean the edges of what the camera sees, not the person's sides.

**Limits to state plainly:**
- LiDAR misses glass, mirrors and very dark surfaces, and objects outside the camera's view (low, overhead, behind).
- It reaches about 5 m.
- It says "something was detected here", never "the path is clear". It's a complement to a cane or guide dog.
