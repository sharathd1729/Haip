"""Distance maths for the GPS checks. Pure, no database. Good to a few metres over a trip-sized area, plenty for a 1.5 km
corridor; no map library and no routing engine (the planned road is the ordered list of points the manager set)."""

from __future__ import annotations

import math

EARTH_KM = 6371.0088
MAX_JUMP_KMH = 150  # two fixes further apart than this speed allows = a bad fix, not distance driven


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


def _segment_km(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    # Flat projection around p: x east, y north, in km.
    k = math.cos(math.radians(p[0]))

    def xy(q):
        return (math.radians(q[1] - p[1]) * EARTH_KM * k, math.radians(q[0] - p[0]) * EARTH_KM)

    (ax, ay), (bx, by) = xy(a), xy(b)
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


def distance_to_line_km(p: tuple[float, float], line: list[tuple[float, float]]) -> float:
    """Shortest distance from p to a polyline (a single point counts as a line of length 0)."""
    if not line:
        return math.inf
    if len(line) == 1:
        return haversine_km(p, line[0])
    return min(_segment_km(p, line[i], line[i + 1]) for i in range(len(line) - 1))


def track_km(points: list[tuple]) -> float:
    """Distance along fixes [(at, lat, lng), ...] in time order, skipping jumps no vehicle could make."""
    total = 0.0
    prev = None
    for at, lat, lng in points:
        if prev is not None:
            d = haversine_km((prev[1], prev[2]), (lat, lng))
            hours = (at - prev[0]).total_seconds() / 3600
            if hours > 0 and d / hours > MAX_JUMP_KMH:
                continue  # drop this fix, keep measuring from the last good one
            total += d
        prev = (at, lat, lng)
    return round(total, 1)
