import ctypes
import os
import re
import subprocess
import threading

from pantheon import paths
from pantheon.framework.schema import bits_from_base64

_PART = re.compile(r"^\s*(?:<([^>\n]*)>)?\s*\*(\d{1,3})\s*\$\s*(\d{1,3})\.([0-9+/A-Za-z]+)\s*$")
_LIB = None
_LOCK = threading.Lock()
_CACHE = {}


def _library():
    global _LIB
    with _LOCK:
        if _LIB is not None:
            return _LIB
        source = os.path.join(paths.PACKAGE, "native", "findtext.c")
        candidates = [os.path.join(paths.PACKAGE, "native", "libpantheon-native.so"),
                      paths.data("cache", "libpantheon-native.so")]
        for candidate in candidates:
            if os.path.exists(candidate) and (not os.path.exists(source) or os.path.getmtime(candidate) >= os.path.getmtime(source)):
                break
        else:
            candidate = candidates[1]
            os.makedirs(os.path.dirname(candidate), exist_ok=True)
            compiler = os.environ.get("CC", "cc")
            result = subprocess.run([compiler, "-O2", "-shared", "-fPIC", "-o", candidate, source], capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError("Could not build the image matcher: " + result.stderr.strip())
        lib = ctypes.CDLL(candidate)
        lib.pantheon_findtext.restype = ctypes.c_int
        lib.pantheon_findtext.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_uint), ctypes.c_int]
        lib.pantheon_dark_frame.restype = ctypes.c_int
        lib.pantheon_dark_frame.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        _LIB = lib
        return lib


def parse(text):
    if text in _CACHE:
        return _CACHE[text]
    parts = []
    for part in text.split("|"):
        if "$" not in part:
            continue
        match = _PART.match(part)
        if not match:
            continue
        width = int(match.group(3))
        bits = re.sub(r"10*$", "", bits_from_base64(match.group(4)))
        if width < 1 or not bits or len(bits) % width:
            continue
        parts.append({"comment": (match.group(1) or "").strip(), "threshold": int(match.group(2)), "width": width,
                      "height": len(bits) // width, "bits": bits.encode("ascii")})
    if len(_CACHE) > 512:
        _CACHE.clear()
    _CACHE[text] = parts
    return parts


def find(frame, x1, y1, x2, y2, err1, err0, text, limit=10240):
    x, y = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1) + 1, abs(y2 - y1) + 1
    x, y = max(0, x), max(0, y)
    w, h = min(w, frame.width - x), min(h, frame.height - y)
    if w < 1 or h < 1:
        return []
    region = frame.crop(x, y, w, h)
    lib = _library()
    results = []
    for part in parse(text):
        out = (ctypes.c_uint * limit)()
        count = lib.pantheon_findtext(region.data, region.width * 3, region.width, region.height, part["threshold"],
                                      part["bits"], part["width"], part["height"], int(abs(err1) * 1024),
                                      int(abs(err0) * 1024), out, limit)
        if count < 0:
            raise MemoryError("The image matcher ran out of memory.")
        for i in range(count):
            px, py = (out[i] & 0xFFFF) + x, (out[i] >> 16) + y
            results.append({"x": px + part["width"] // 2, "y": py + part["height"] // 2, "left": px, "top": py,
                            "width": part["width"], "height": part["height"], "id": part["comment"]})
    return results


def dark(frame):
    return bool(_library().pantheon_dark_frame(frame.data, frame.width, frame.height))
