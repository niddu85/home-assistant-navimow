"""Conversion of the mower's local map coordinates to GPS coordinates."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_378_137.0


def local_to_gps(
    x: float, y: float, dock_latitude: float, dock_longitude: float, rotation_deg: float
) -> tuple[float, float]:
    """Convert local map coordinates (meters from the dock) to latitude/longitude.

    With rotation 0 the local X axis points east and Y points north; a positive
    rotation turns the map clockwise around the dock. Distances are a few
    hundred meters at most, so a flat-earth approximation is accurate enough.
    """
    rotation = math.radians(rotation_deg)
    east = x * math.cos(rotation) + y * math.sin(rotation)
    north = -x * math.sin(rotation) + y * math.cos(rotation)
    latitude = dock_latitude + math.degrees(north / EARTH_RADIUS_M)
    longitude = dock_longitude + math.degrees(
        east / (EARTH_RADIUS_M * math.cos(math.radians(dock_latitude)))
    )
    return latitude, longitude
