import re

CURRENT = "1.0-beta.3"
_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")


def parts(value):
    match = _PATTERN.match(value) if isinstance(value, str) and len(value) <= 80 else None
    if not match:
        raise ValueError("Invalid Pantheon version requirement.")
    pre = match.group(4).split(".") if match.group(4) else []
    for part in pre:
        if re.match(r"^0[0-9]+$", part):
            raise ValueError("Invalid Pantheon prerelease version.")
    return [int(match.group(1)), int(match.group(2)), int(match.group(3) or 0), pre]


def compare(left, right):
    a, b = parts(left), parts(right)
    for i in range(3):
        if a[i] != b[i]:
            return 1 if a[i] > b[i] else -1
    a, b = a[3], b[3]
    if not a or not b:
        return 0 if len(a) == len(b) else (1 if not a else -1)
    for x, y in zip(a, b):
        if x == y:
            continue
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            return 1 if int(x) > int(y) else -1
        if xn != yn:
            return -1 if xn else 1
        return 1 if x.lower() > y.lower() else -1
    return 0 if len(a) == len(b) else (1 if len(a) > len(b) else -1)


def require(value):
    if compare(CURRENT, value) < 0:
        raise ValueError("This macro requires Pantheon " + value + " or newer. Installed version: " + CURRENT + ".")
