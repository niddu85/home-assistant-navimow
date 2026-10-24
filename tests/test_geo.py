"""Tests for the local to GPS conversion."""
from __future__ import annotations

import math

import pytest

from custom_components.navimow.geo import EARTH_RADIUS_M, local_to_gps

LAT, LON = 45.0, 9.0
M_PER_DEG_LAT = math.radians(1) * EARTH_RADIUS_M
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(LAT))


def _offset_m(lat: float, lon: float) -> tuple[float, float]:
    """East and north offset from the dock, in meters."""
    return (lon - LON) * M_PER_DEG_LON, (lat - LAT) * M_PER_DEG_LAT


@pytest.mark.parametrize(
    ("x", "y", "rotation", "east", "north"),
    [
        (0, 0, 37, 0, 0),
        (10, 0, 0, 10, 0),
        (0, 10, 0, 0, 10),
        (10, 0, 90, 0, -10),  # map turned clockwise: X points south
        (0, 10, 90, 10, 0),
        (10, 0, -90, 0, 10),
        (10, 0, 180, -10, 0),
    ],
)
def test_local_to_gps(x, y, rotation, east, north) -> None:
    lat, lon = local_to_gps(x, y, LAT, LON, rotation)
    got_east, got_north = _offset_m(lat, lon)
    assert got_east == pytest.approx(east, abs=1e-6)
    assert got_north == pytest.approx(north, abs=1e-6)
