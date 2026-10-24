# Accessibility checklist

Run this before the demo and before each submission. Do it once with a screen reader on (VoiceOver on Mac: Cmd+F5; NVDA on Windows) and once with the screen off or your eyes closed, keyboard only. Also check at 200% browser zoom.

None of this replaces testing with blind and low-vision people. We haven't done that yet; say so if asked.

## Everywhere
- [ ] Tab from the top: the first stop is "Skip to main content", and it works.
- [ ] Every page change announces the new page (focus moves to the main content; the tab title changes).
- [ ] Every button and input has a spoken name; nothing is read as just "button".
- [ ] Focus is always visible (orange outline).
- [ ] Dark mode toggle works and is announced as on/off.
- [ ] Status messages ("Saving…", "Model ready…") are announced without moving focus.
- [ ] Errors are announced as alerts and say what to do next.

## Upload
- [ ] "Choose a file" opens the picker with the keyboard; a wrong file type gets a clear error.
- [ ] "Load the demo scan" and "Try the public RoomPlan sample" both work, and the sample's provenance note is read with its button.

## Floor plan
- [ ] Tab reaches landmarks on the plan; Enter selects; arrow keys move by 0.1 m (Shift: 0.5 m), and each move is announced with the room.
- [ ] The landmark form fields (name, type, position, linked location) are all labeled.
- [ ] "Text description of the plan" lists rooms and landmarks, and "Read the plan aloud" reads it and can be stopped.
- [ ] Walkable paths: adding a path through a wall says why it was refused.

## 3D tactile map
- [ ] Download STL is the first action and announces the size.
- [ ] Camera buttons (reset, top view, zoom) work without a mouse.
- [ ] "Text description of the tactile map" covers size, scale, the cut corner, walls and doors, every symbol, and the legend.
- [ ] "Read the description aloud" works and stops.

## Voice explorer
- [ ] On arrival, focus is in the question box.
- [ ] Typing a question and pressing Enter answers it; focus returns to the box.
- [ ] Answers are announced by the screen reader (log region) and, if "Speak answers aloud" is on, spoken.
- [ ] With a screen reader running, turning off "Speak answers aloud" stops double speech.
- [ ] "Speak a question": rising tone, then speak, press again, falling tone, then the answer. Microphone denied gives a clear message and points to typing.
- [ ] "Replay answer" and "Stop speaking" work.
- [ ] Directions are also shown as a numbered list.
- [ ] The safety notice is present, and directions end with the cane / guide dog reminder.
- [ ] "Where am I?" says position isn't tracked.

## Walk-through
- [ ] "Start sound" works and moves focus to the walk area; the volume slider is labeled and starts low.
- [ ] In the walk area, arrows walk and turn, Shift+arrows turn 90°, T turns around, Space says what's around you.
- [ ] With headphones: a wall close on the right muffles only the right ear; walking toward a wall makes ticks speed up.
- [ ] Bumping into a wall plays a thud and says what's ahead, once (not on every repeat).
- [ ] Walking out the main entrance stops the noise and starts the two-note "no information" cue; walking back in restores it.
- [ ] On a phone: the buttons are easy to hit, holding Forward keeps walking, and sound plays with the silent switch on.

## Printed map (if printed)
- [ ] The cut corner is at the top left and easy to find.
- [ ] Door gaps can be found with a fingertip.
- [ ] All six symbols can be told apart by touch, and the legend matches.
- [ ] No sharp edges or stringing.
