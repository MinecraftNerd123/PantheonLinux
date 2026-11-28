import re
import shutil
import subprocess

from pantheon.image import Frame


def _scale(frame, factor):
    if factor == 1:
        return frame
    rows, stride = [], frame.width * 3
    for y in range(frame.height):
        row = frame.data[y * stride:(y + 1) * stride]
        wide = b"".join(row[x * 3:x * 3 + 3] * factor for x in range(frame.width))
        rows.extend([wide] * factor)
    return Frame(frame.width * factor, frame.height * factor, b"".join(rows))


def read(frame, scale=2):
    binary = shutil.which("tesseract")
    if not binary:
        raise RuntimeError("OCR requires tesseract.")
    image = _scale(frame, scale).png()
    result = subprocess.run([binary, "stdin", "stdout", "--psm", "6", "-l", "eng"], input=image, capture_output=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError("OCR failed: " + result.stderr.decode("utf-8", "replace").strip()[:300])
    lines = [line.strip() for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    return " ".join(lines)


def _light(frame):
    # Keep light, blue-ish text (white, pink, blue gradients) and drop the darker game world behind it.
    data, out = frame.data, bytearray(len(frame.data))
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        value = 0 if b > 100 and r + g + b > 380 else 255
        out[i] = out[i + 1] = out[i + 2] = value
    return Frame(frame.width, frame.height, bytes(out))


def read_number(frame, filter="none"):
    if filter == "light":
        binary = shutil.which("tesseract")
        if not binary:
            raise RuntimeError("OCR requires tesseract.")
        result = subprocess.run([binary, "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=+0123456789"],
                                input=_scale(_light(frame), 6).png(), capture_output=True, timeout=20)
        text = result.stdout.decode("utf-8", "replace")
    else:
        text = read(frame, 3)
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    return max(numbers) if numbers else None
