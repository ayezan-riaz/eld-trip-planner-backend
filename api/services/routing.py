from dataclasses import dataclass
from typing import List, Tuple
import requests
from django.conf import settings


@dataclass
class RouteLeg:
    distance_miles: float
    duration_hours: float
    from_name: str
    to_name: str


@dataclass
class RouteResult:
    distance_miles: float
    duration_hours: float
    coordinates: List[Tuple[float, float]]
    legs: List[RouteLeg]


class RoutingError(Exception):
    pass


def get_route(points, names) -> RouteResult:
    coordinate_string = ";".join(f"{point.lon},{point.lat}" for point in points)

    response = requests.get(
        f"{settings.ROUTER_URL}/{coordinate_string}",
        params={
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        },
        headers={"User-Agent": settings.USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()

    routes = payload.get("routes") or []
    if not routes:
        raise RoutingError("No route was returned by OSRM.")

    route = routes[0]
    geometry = route["geometry"]["coordinates"]
    coordinates = [(lat, lon) for lon, lat in geometry]

    legs = []
    for index, leg in enumerate(route.get("legs", [])):
        legs.append(
            RouteLeg(
                distance_miles=meters_to_miles(float(leg["distance"])),
                duration_hours=seconds_to_hours(float(leg["duration"])),
                from_name=names[index],
                to_name=names[index + 1],
            )
        )

    return RouteResult(
        distance_miles=meters_to_miles(float(route["distance"])),
        duration_hours=seconds_to_hours(float(route["duration"])),
        coordinates=coordinates,
        legs=legs,
    )


def meters_to_miles(value: float) -> float:
    return value / 1609.344


def seconds_to_hours(value: float) -> float:
    return value / 3600.0
