# Pantheon for Linux 1.0-beta.3

A Linux port of [Pantheon](https://github.com/PantheonSupport/Pantheon): a desktop launcher and visual macro editor for Roblox tower defence games. This fork targets **Roblox running in [Sober](https://sober.vinegarhq.org/) on Hyprland** and ships as a Flatpak. Macros are the same validated JSON configurations as upstream, run by a Python port of the shared engine, so macros exported from the Windows version import unchanged.

## Requirements

- Hyprland (0.4x with hyprlang config, or 0.55+ with Lua config; both are supported).
- Sober (`org.vinegarhq.Sober`).
- `grim` installed on the host. Hyprland does not give screen capture to sandboxed apps, so the Flatpak runs the host's `grim`.
- Write access to `/dev/uinput` for mouse and keyboard input. Either be in the `input` group or install the udev rule:

  ```bash
  sudo install -m644 packaging/70-pantheon-uinput.rules /etc/udev/rules.d/
  sudo udevadm control --reload && sudo udevadm trigger
  ```

- Monitor scale 1 on the monitor that shows Sober (captures are taken at logical resolution; fractional scaling blurs FindText patterns).

## Install (Flatpak)

Download `PantheonLinux.flatpak` from the releases page, then:

```bash
flatpak install --user PantheonLinux.flatpak
flatpak run io.github.MinecraftNerd123.PantheonLinux
```

Build it yourself:

```bash
flatpak install --user flathub org.flatpak.Builder org.gnome.Sdk//51 org.gnome.Platform//51
make flatpak
flatpak run io.github.MinecraftNerd123.PantheonLinux
```

`make bundle` writes `dist/Pantheon.flatpak` for distribution; install it with `flatpak install --user Pantheon.flatpak`.

## Run from source

Needs Python 3.11+, PyGObject with GTK 4 and WebKitGTK 6.0, a C compiler, `grim` and `tesseract` (with the `eng` language).

```bash
make run
```

## How the Windows pieces map

| Windows (upstream) | Linux (this fork) |
| --- | --- |
| AutoHotkey v2 host and engine | Python package `pantheon/` |
| WebView2 | GTK 4 + WebKitGTK 6.0; `pantheon/bridge.js` provides `window.chrome.webview` so `Lib/ui` runs unchanged |
| Win32 window pinning (SetWindowPos, topmost) | Hyprland IPC: float, move, resize, special workspace for hiding, z-order |
| GDI+ screen capture | `grim` (bundled; falls back to the host's `grim`) |
| FindText machine code | `pantheon/native/findtext.c`, a port of the same grayscale matcher; existing patterns are compatible |
| SendInput / ControlSend | `/dev/uinput` virtual device; cursor positioning through Hyprland |
| Windows OCR | Tesseract (bundled, English) |
| Global hotkeys | Hyprland binds registered only while Pantheon or Sober is focused |
| Registry settings | `~/.var/app/io.github.MinecraftNerd123.PantheonLinux/data/pantheon/settings.json` (Flatpak) or `~/.local/share/pantheon/` |
| In-place ZIP updater | `flatpak update` |

## Walled City Infinite macro

`macros/macro-walled-city-infinite.json` plays Anime Adventures Walled City in Infinite mode and loops with Replay:

1. On the vote screen it aligns the camera (fully top-down, then turns until the minimap arrow points straight down, so placements land in the same place every match) and clicks Yes until the match starts.
2. Places Bulby (slot 2), then three Demon Girls (slot 4) next to the path junction at spawn, turning in-game **Auto** on for each Demon Girl and then for Bulby (key **T**).
3. Waits for wave 30, opens Settings, scrolls to **Vote to Lose**, confirms **Vote**, and keeps retrying until the Defeat screen shows. As a backstop, from 12 minutes into the match it also votes once the wave counter reads 31 or more (three matching OCR reads), and it always votes at 25 minutes (about wave 50).
4. On the Defeat screen it counts the match as a victory if the wave counter reached 30 and a defeat if it did not, adds the gems shown under the wave counter to the **Gems** total next to Victories and Defeats, then clicks Next, clicks through rewards, presses **Replay**, and repeats.

Start it on the vote screen of a Walled City Infinite match, on the Defeat screen, or on the Return to lobby / Replay screen. Starting mid-match with units already placed stops at the first placement. Placements live in Placement setup under **Walled City (Infinite)**; `packaging/install-walled-city-plan.py` writes the default plan.

Pantheon sets its virtual mouse to a flat acceleration profile on Hyprland so camera turns are exact (10 px of movement ≈ 1°).

## Roblox and controls

Selecting a macro opens its workspace. Sober stays an independent window that Pantheon floats, resizes to an 800 × 600 client and moves over the live view. Switching away to another page moves Sober to the hidden `special:pantheon` workspace; unpinning or closing Pantheon restores its original floating, size, workspace and fullscreen state. Pantheon floats its own window at 1380 × 900 on start; set `PANTHEON_TILED=1` to keep it tiled.

Defaults: F1 positions Roblox, F2 starts/stops and F4 pauses/resumes. They are registered as Hyprland binds only while Pantheon or Sober has focus, and removed otherwise. Input only reaches the focused window, so while a macro runs Pantheon focuses Sober again whenever something else takes focus (pause with F4 or stop from Pantheon to use the computer).

In repeat mode an error no longer stops the macro: Pantheon logs it, runs the macro's `recover` sequence if it has one (Walled City votes to lose the broken match), and starts the next run. Five failed runs in a row stop it. The log and a half-size frame every 3 seconds of the last two runs are kept in `recordings/` in Pantheon's data folder (`~/.var/app/io.github.MinecraftNerd123.PantheonLinux/data/pantheon/recordings` for the Flatpak), with an `error.png` full screenshot when a run failed.

Coordinate picking and image capture show a frozen capture overlay over Sober. Left click selects a point; drag selects a region; Escape cancels.

## Flatpak permissions

| Permission | Why |
| --- | --- |
| `--filesystem=xdg-run/hypr` | Hyprland IPC for window control, cursor position and shortcuts |
| `--device=all` | `/dev/uinput` for input |
| `--talk-name=org.freedesktop.Flatpak` | Fallback to the host's `grim` when the compositor denies screen capture to sandboxed clients |
| `--share=network` | Discord webhooks and update checks, only when you use them |

Hyprland IPC can run commands on the host, so the sandbox is not a security boundary for this app. Review community macros before running them, as upstream advises.

## Files

| Location | Purpose |
| --- | --- |
| `pantheon/` | Host, engine, platform backends and native matcher |
| `Lib/ui/` | Web interface shared with upstream |
| `macros/` | Supplied macro JSON files, including Raids |
| `packaging/` | Flatpak manifest, desktop entry, metainfo and udev rule |
| `docs/` | Authoring and framework reference |

## Checks

```bash
make test
```

Runs the Python engine/schema/matcher tests and the upstream Node UI tests. See [VERIFICATION.md](VERIFICATION.md).

## Scope

Configurations automate the game's UI and movement through supported actions. They cannot supply executable code, file access, network requests or external icons. Roblox remains responsible for account and private-server access.

See [Macro authoring](docs/MACRO_AUTHORING.md), [Editor controls](docs/EDITOR_CONTROLS.md), [Shared placements](docs/SHARED_PLACEMENTS.md) and [Placed-unit actions](docs/PLACED_UNIT_ACTIONS.md). Original Pantheon icons and vendored notices are retained; see [THIRD_PARTY.md](THIRD_PARTY.md).
