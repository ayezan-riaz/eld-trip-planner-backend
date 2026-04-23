from dataclasses import dataclass
from typing import Dict
import requests
from django.conf import settings


@dataclass
class GeocodedLocation:
    query: str
    lat: float
    lon: float
    display_name: str


class GeocodingError(Exception):
    pass


def geocode(query: str) -> GeocodedLocation:
    response = requests.get(
        settings.GEOCODER_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 1,
        },
        headers={"User-Agent": settings.USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload:
        raise GeocodingError(f"Could not geocode location: {query}")

    item = payload[0]
    return GeocodedLocation(
        query=query,
        lat=float(item["lat"]),
        lon=float(item["lon"]),
        display_name=item.get("display_name", query),
    )
