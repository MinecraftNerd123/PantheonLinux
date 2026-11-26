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
