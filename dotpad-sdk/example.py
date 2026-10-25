from dotpad_sdk import DotPad, MockBackend, ViewerServer

pad = DotPad(MockBackend())
pad.on_button(lambda event: print(event.button.value, event.action.value))
with ViewerServer(pad) as viewer:
    print(viewer.url)
    with pad:
        pad.display_graphics(bytes([0xff]*300))
        pad.display_braille(b"\x01\x03\x09")
        pad.refresh_graphics()
        pad.refresh_braille()
        input("Enter to stop\n")
