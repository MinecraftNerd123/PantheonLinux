# Verification (Linux port)

Checked on Arch Linux, Hyprland 0.57.2 (Lua config), Python 3, GTK 4 / WebKitGTK 6.0, with Sober installed. These are local checks, not a public deployment or Roblox gameplay certification.

## Passed

- 12 Python tests (`tests/test_framework.py`): bundled Raids definition validates; entry retry sequence, right-click buttons and diagonal sprint holds; match-result victory, defeat and timeout; nested AND/OR/absent conditions; until loops including deadline interruption that releases held keys; retry failure continuation; cancellation releases input; schema rejection of unknown actions, unknown fields and recursive calls; placement-plan instance linking and ordering; FindText round trip, overlap suppression, bounded regions and mismatch tolerance; AHK-compatible JSON semantics (sorted maps, `true` → 1, `null` → "").
- 23 upstream Node UI tests, with the two source-inspection tests retargeted from AHK files to the Python host.
- Hyprland IPC on 0.57.2: client queries, float/move/resize/focus, special-workspace hiding, fullscreen state, z-order, cursor warp, dynamic shortcut binding and removal, dynamic window rules.
- `grim` region capture of an 800 × 600 area in about 22 ms; the native matcher searches a full client in about 4 ms.
- The GTK/WebKit host loads the unchanged UI; the bridge returns the macro catalogue and version from Python.

- Flatpak built with GNOME 51 and installed from the bundle; inside the sandbox Hyprland IPC, uinput, Tesseract, the native matcher and screen capture (via host grim) work, and the window opens floating at 1380 x 900.

## Not yet verified

- Live pinning of Sober and input reaching Roblox (see below).
- Live pinning of Sober over the dashboard, capture overlay positioning, and uinput input reaching Roblox inside Sober.
- Hyprland 0.57 denies screen capture to the sandboxed grim ("compositor doesn't support the screen capture protocol"); the host grim fallback through flatpak-spawn works, so the host needs grim installed.
- Legacy (hyprlang) Hyprland dispatch strings were written from the documented syntax and not exercised.
- Tesseract OCR accuracy compared with Windows OCR.
