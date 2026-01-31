import math
import re
from typing import Optional, Tuple

_NUM = r"(\d+(?:\.\d+)?)"
POINT_PATTERN = re.compile(r"\[\[\s*" + _NUM + r"\s*,\s*" + _NUM + r"\s*\]\]")
BBOX_PATTERN = re.compile(
    r"\[\[\s*"
    + _NUM
    + r"\s*,\s*"
    + _NUM
    + r"\s*,\s*"
    + _NUM
    + r"\s*,\s*"
    + _NUM
    + r"\s*\]\]"
)


def extract_first_point(text: str) -> Optional[Tuple[float, float]]:
    match = POINT_PATTERN.search(text)
    if not match:
        return None
    try:
        x = float(match.group(1))
        y = float(match.group(2))
        return x, y
    except Exception:
        return None


def extract_last_bbox(text: str) -> Optional[Tuple[float, float, float, float]]:
    matches = list(BBOX_PATTERN.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    try:
        x1 = float(match.group(1))
        y1 = float(match.group(2))
        x2 = float(match.group(3))
        y2 = float(match.group(4))
        return x1, y1, x2, y2
    except Exception:
        return None


def scale_norm_to_pixels(
    x_norm: float, y_norm: float, width: int, height: int
) -> Tuple[int, int]:
    x_px = int(math.floor((x_norm / 1000.0) * width))
    y_px = int(math.floor((y_norm / 1000.0) * height))
    x_px = max(0, min(width - 1, x_px))
    y_px = max(0, min(height - 1, y_px))
    return x_px, y_px
