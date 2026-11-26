import os
import shutil
import subprocess

from pantheon import paths
from pantheon.image import parse_ppm


class CaptureError(RuntimeError):
    pass


def _commands():
    commands = []
    local = shutil.which("grim")
    if local:
        commands.append([local])
    if paths.FLATPAK and shutil.which("flatpak-spawn"):
        commands.append(["flatpak-spawn", "--host", "grim"])
    return commands


_working = None


def grab(x, y, width, height):
    global _working
    commands = [_working] if _working else _commands()
    if not commands:
        raise CaptureError("Screen capture requires grim.")
    errors = []
    for command in commands:
        args = command + ["-t", "ppm", "-s", "1", "-g", "%d,%d %dx%d" % (x, y, width, height), "-"]
        try:
            result = subprocess.run(args, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as err:
            errors.append(str(err))
            continue
        if result.returncode == 0 and result.stdout.startswith(b"P6"):
            frame = parse_ppm(result.stdout)
            if frame.width != width or frame.height != height:
                raise CaptureError("Captured %d x %d instead of %d x %d. Set the Roblox monitor scale to 1 or keep Sober on one monitor."
                                   % (frame.width, frame.height, width, height))
            _working = command
            return frame
        errors.append(result.stderr.decode("utf-8", "replace").strip() or "exit %d" % result.returncode)
    _working = None
    raise CaptureError("Could not capture the screen: " + "; ".join(e for e in errors if e))
