from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
import math


MAX_DRIVING_HOURS_PER_SHIFT = 11.0
MAX_DRIVING_WINDOW_HOURS = 14.0
BREAK_AFTER_CUMULATIVE_DRIVING_HOURS = 8.0
BREAK_DURATION_HOURS = 0.5
RESET_OFF_DUTY_HOURS = 10.0
CYCLE_LIMIT_HOURS = 70.0
CYCLE_RESET_HOURS = 34.0
FUEL_EVERY_MILES = 1000.0
PICKUP_HOURS = 1.0
DROPOFF_HOURS = 1.0
DEFAULT_CARRIER = "ELD Trip Planner Demo Carrier"
DEFAULT_HOME_TERMINAL = "Planner Terminal"


@dataclass
class Activity:
    status: str
    start: datetime
    end: datetime
    label: str
    location: str
    coordinate: Optional[Tuple[float, float]] = None
    meta: Dict = field(default_factory=dict)

    @property
    def duration_hours(self) -> float:
        return round((self.end - self.start).total_seconds() / 3600.0, 2)


@dataclass
class Stop:
    type: str
    start: datetime
    end: datetime
    label: str
    location: str
    coordinate: Optional[Tuple[float, float]] = None
    duration_hours: float = 0.0
    day_index: int = 0
    meta: Dict = field(default_factory=dict)


@dataclass
class PlannerInput:
    current_location_label: str
    pickup_location_label: str
    dropoff_location_label: str
    route_coordinates: List[Tuple[float, float]]
    leg_distances_miles: List[float]
    leg_durations_hours: List[float]
    current_cycle_used: float
    start_time: Optional[datetime] = None
    current_coordinate: Optional[Tuple[float, float]] = None
    pickup_coordinate: Optional[Tuple[float, float]] = None
    dropoff_coordinate: Optional[Tuple[float, float]] = None


class HOSPlanner:
    def __init__(self, planner_input: PlannerInput):
        self.input = planner_input
        self.route_coordinates = planner_input.route_coordinates or []
        self.route_cumulative_miles = build_cumulative_miles(self.route_coordinates)
        self.total_route_miles = sum(planner_input.leg_distances_miles)
        self.current_time = self._initial_start_time()
        self.shift_start: Optional[datetime] = self.current_time
        self.shift_driving_hours = 0.0
        self.driving_since_break = 0.0
        self.cycle_used = float(planner_input.current_cycle_used)
        self.miles_since_fuel = 0.0
        self.route_miles_completed = 0.0
        self.activities: List[Activity] = []
        self.stops: List[Stop] = []
        self.current_day_index = 1

    def plan(self) -> Dict:
        for leg_index, (leg_miles, leg_hours) in enumerate(zip(self.input.leg_distances_miles, self.input.leg_durations_hours)):
            origin_label = self.input.current_location_label if leg_index == 0 else self.input.pickup_location_label
            destination_label = self.input.pickup_location_label if leg_index == 0 else self.input.dropoff_location_label
            destination_coordinate = self.input.pickup_coordinate if leg_index == 0 else self.input.dropoff_coordinate
            self._drive_leg(
                leg_miles=leg_miles,
                leg_hours=leg_hours,
                origin_label=origin_label,
                destination_label=destination_label,
                destination_coordinate=destination_coordinate,
            )

            if leg_index == 0:
                self._add_on_duty_task(
                    hours=PICKUP_HOURS,
                    label="Pickup",
                    location=self.input.pickup_location_label,
                    coordinate=self.input.pickup_coordinate,
                    stop_type="pickup",
                )
            else:
                self._add_on_duty_task(
                    hours=DROPOFF_HOURS,
                    label="Dropoff",
                    location=self.input.dropoff_location_label,
                    coordinate=self.input.dropoff_coordinate,
                    stop_type="dropoff",
                )

        days = self._build_daily_logs()
        summary = self._build_summary(days)
        assumptions = [
            "Property-carrying driver under the 70-hour/8-day rule.",
            "No adverse driving conditions are applied.",
            "Pickup and dropoff each consume 1 hour of on-duty not-driving time.",
            "Fuel stops are inserted at least every 1,000 route miles.",
            "If the weekly cycle is exhausted and more driving remains, a 34-hour restart is inserted because prior 8-day detail is not provided.",
        ]

        return {
            "summary": summary,
            "route": {
                "distance_miles": round(self.total_route_miles, 1),
                "duration_hours": round(sum(self.input.leg_durations_hours), 2),
                "coordinates": [{"lat": lat, "lng": lng} for lat, lng in self.route_coordinates],
            },
            "stops": [serialize_stop(stop) for stop in self.stops],
            "days": days,
            "planning_assumptions": assumptions,
        }

    def _initial_start_time(self) -> datetime:
        if self.input.start_time:
            return self.input.start_time.replace(second=0, microsecond=0)
        now = datetime.utcnow().replace(second=0, microsecond=0)
        return now

    def _drive_leg(
        self,
        leg_miles: float,
        leg_hours: float,
        origin_label: str,
        destination_label: str,
        destination_coordinate: Optional[Tuple[float, float]],
    ) -> None:
        remaining_miles = leg_miles
        remaining_hours = leg_hours

        if remaining_miles <= 0 or remaining_hours <= 0:
            return

        avg_speed = remaining_miles / remaining_hours if remaining_hours else 50.0

        while remaining_hours > 1e-6:
            if self.shift_start is None:
                self._start_new_shift()

            hours_until_cycle_limit = max(0.0, CYCLE_LIMIT_HOURS - self.cycle_used)
            if hours_until_cycle_limit <= 1e-6:
                self._insert_cycle_restart()
                continue

            window_elapsed = hours_between(self.shift_start, self.current_time)
            hours_until_window_end = max(0.0, MAX_DRIVING_WINDOW_HOURS - window_elapsed)
            hours_until_drive_limit = max(0.0, MAX_DRIVING_HOURS_PER_SHIFT - self.shift_driving_hours)
            hours_until_break = max(0.0, BREAK_AFTER_CUMULATIVE_DRIVING_HOURS - self.driving_since_break)
            miles_until_fuel = max(0.0, FUEL_EVERY_MILES - self.miles_since_fuel)
            hours_until_fuel = miles_until_fuel / avg_speed if avg_speed > 0 else remaining_hours

            block_hours = min(
                remaining_hours,
                hours_until_cycle_limit,
                hours_until_window_end,
                hours_until_drive_limit,
                hours_until_break,
                hours_until_fuel,
            )

            if block_hours <= 1e-6:
                self._resolve_zero_block(hours_until_window_end, hours_until_drive_limit, hours_until_break, hours_until_fuel)
                continue

            start = self.current_time
            end = start + timedelta(hours=block_hours)
            miles_driven = avg_speed * block_hours
            self.route_miles_completed += miles_driven
            coordinate = self._interpolated_coordinate(self.route_miles_completed)

            self.activities.append(
                Activity(
                    status="driving",
                    start=start,
                    end=end,
                    label=f"Drive toward {destination_label}",
                    location=destination_label,
                    coordinate=coordinate,
                    meta={
                        "miles": round(miles_driven, 1),
                        "origin": origin_label,
                        "destination": destination_label,
                    },
                )
            )

            self.current_time = end
            self.shift_driving_hours += block_hours
            self.driving_since_break += block_hours
            self.cycle_used += block_hours
            self.miles_since_fuel += miles_driven
            remaining_hours -= block_hours
            remaining_miles -= miles_driven

            self._update_day_index()

            if remaining_hours <= 1e-6:
                break

    def _resolve_zero_block(
        self,
        hours_until_window_end: float,
        hours_until_drive_limit: float,
        hours_until_break: float,
        hours_until_fuel: float,
    ) -> None:
        if hours_until_window_end <= 1e-6 or hours_until_drive_limit <= 1e-6:
            self._insert_off_duty_reset(RESET_OFF_DUTY_HOURS, "10-hour off-duty reset")
            return

        if hours_until_break <= 1e-6 and hours_until_fuel <= 1e-6:
            self._add_stop(
                stop_type="fuel_break",
                hours=BREAK_DURATION_HOURS,
                status="on_duty",
                label="Fuel stop + 30-minute break",
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
                reset_break=True,
                reset_fuel=True,
            )
            return

        if hours_until_break <= 1e-6:
            self._add_stop(
                stop_type="break",
                hours=BREAK_DURATION_HOURS,
                status="off_duty",
                label="30-minute break",
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
                reset_break=True,
            )
            return

        if hours_until_fuel <= 1e-6:
            self._add_stop(
                stop_type="fuel",
                hours=BREAK_DURATION_HOURS,
                status="on_duty",
                label="Fuel stop",
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
                reset_fuel=True,
            )
            return

        self._insert_off_duty_reset(RESET_OFF_DUTY_HOURS, "10-hour off-duty reset")

    def _add_on_duty_task(
        self,
        hours: float,
        label: str,
        location: str,
        coordinate: Optional[Tuple[float, float]],
        stop_type: str,
    ) -> None:
        start = self.current_time
        end = start + timedelta(hours=hours)
        activity = Activity(
            status="on_duty",
            start=start,
            end=end,
            label=label,
            location=location,
            coordinate=coordinate,
            meta={"task": label.lower()},
        )
        self.activities.append(activity)
        self.stops.append(
            Stop(
                type=stop_type,
                start=start,
                end=end,
                label=label,
                location=location,
                coordinate=coordinate,
                duration_hours=round(hours, 2),
                day_index=self.current_day_index,
                meta={"task": label.lower()},
            )
        )
        self.current_time = end
        self.cycle_used += hours
        self._update_day_index()

    def _add_stop(
        self,
        stop_type: str,
        hours: float,
        status: str,
        label: str,
        location: str,
        coordinate: Optional[Tuple[float, float]],
        reset_break: bool = False,
        reset_fuel: bool = False,
    ) -> None:
        start = self.current_time
        end = start + timedelta(hours=hours)
        self.activities.append(
            Activity(
                status=status,
                start=start,
                end=end,
                label=label,
                location=location,
                coordinate=coordinate,
            )
        )
        self.stops.append(
            Stop(
                type=stop_type,
                start=start,
                end=end,
                label=label,
                location=location,
                coordinate=coordinate,
                duration_hours=round(hours, 2),
                day_index=self.current_day_index,
            )
        )
        self.current_time = end
        if status == "on_duty":
            self.cycle_used += hours
        if reset_break:
            self.driving_since_break = 0.0
        if reset_fuel:
            self.miles_since_fuel = 0.0
        self._update_day_index()

    def _insert_off_duty_reset(self, hours: float, label: str) -> None:
        start = self.current_time
        end = start + timedelta(hours=hours)
        self.activities.append(
            Activity(
                status="off_duty",
                start=start,
                end=end,
                label=label,
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
            )
        )
        self.stops.append(
            Stop(
                type="off_duty_reset",
                start=start,
                end=end,
                label=label,
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
                duration_hours=round(hours, 2),
                day_index=self.current_day_index,
            )
        )
        self.current_time = end
        self.shift_start = None
        self.shift_driving_hours = 0.0
        self.driving_since_break = 0.0
        self._update_day_index()

    def _insert_cycle_restart(self) -> None:
        start = self.current_time
        end = start + timedelta(hours=CYCLE_RESET_HOURS)
        self.activities.append(
            Activity(
                status="off_duty",
                start=start,
                end=end,
                label="34-hour restart",
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
            )
        )
        self.stops.append(
            Stop(
                type="cycle_restart",
                start=start,
                end=end,
                label="34-hour restart",
                location=self._approx_location_label(),
                coordinate=self._interpolated_coordinate(self.route_miles_completed),
                duration_hours=CYCLE_RESET_HOURS,
                day_index=self.current_day_index,
            )
        )
        self.current_time = end
        self.shift_start = None
        self.shift_driving_hours = 0.0
        self.driving_since_break = 0.0
        self.cycle_used = 0.0
        self._update_day_index()

    def _start_new_shift(self) -> None:
        self.shift_start = self.current_time
        self.shift_driving_hours = 0.0
        self.driving_since_break = 0.0

    def _build_daily_logs(self) -> List[Dict]:
        if not self.activities:
            return []

        start_day = self.activities[0].start.date()
        end_day = self.activities[-1].end.date()
        days = []
        current_date = start_day

        while current_date <= end_day:
            day_start = datetime.combine(current_date, time(0, 0))
            day_end = day_start + timedelta(days=1)

            segments = split_activities_for_day(self.activities, day_start, day_end)
            normalized_segments = fill_day_gaps(segments, day_start, day_end)

            remarks = []
            for segment in normalized_segments:
                if segment.label == "Off duty":
                    continue
                remarks.append(
                    {
                        "time": segment.start.strftime("%H:%M"),
                        "location": segment.location,
                        "note": segment.label,
                    }
                )

            totals = summarize_status_hours(normalized_segments)
            total_miles = round(sum(segment.meta.get("miles", 0.0) for segment in normalized_segments if segment.status == "driving"), 1)

            days.append(
                {
                    "day_index": len(days) + 1,
                    "date": current_date.isoformat(),
                    "activities": [serialize_activity(item) for item in normalized_segments],
                    "status_totals": totals,
                    "total_miles": total_miles,
                    "remarks": remarks,
                    "form": {
                        "carrier_name": DEFAULT_CARRIER,
                        "home_terminal": DEFAULT_HOME_TERMINAL,
                        "from": self.input.current_location_label,
                        "to": self.input.dropoff_location_label,
                        "shipping_document": "Assessment Demo Load",
                    },
                }
            )

            current_date += timedelta(days=1)

        return days

    def _build_summary(self, days: List[Dict]) -> Dict:
        fuel_stop_count = len([stop for stop in self.stops if stop.type in {"fuel", "fuel_break"}])
        break_count = len([stop for stop in self.stops if stop.type in {"break", "fuel_break"}])
        restart_count = len([stop for stop in self.stops if stop.type == "cycle_restart"])
        total_drive_hours = round(sum(a.duration_hours for a in self.activities if a.status == "driving"), 2)

        return {
            "distance_miles": round(self.total_route_miles, 1),
            "drive_hours": total_drive_hours,
            "trip_days": len(days),
            "fuel_stops": fuel_stop_count,
            "breaks": break_count,
            "cycle_restarts": restart_count,
            "final_cycle_used_estimate": round(self.cycle_used, 2),
        }

    def _approx_location_label(self) -> str:
        return f"Approx. route mile {int(round(self.route_miles_completed))}"

    def _interpolated_coordinate(self, miles_along_route: float) -> Optional[Tuple[float, float]]:
        if not self.route_coordinates:
            return None
        return interpolate_point(self.route_coordinates, self.route_cumulative_miles, miles_along_route)

    def _update_day_index(self) -> None:
        if not self.activities:
            self.current_day_index = 1
            return
        first_day = self.activities[0].start.date()
        last_time = self.current_time.date()
        self.current_day_index = (last_time - first_day).days + 1


def serialize_activity(activity: Activity) -> Dict:
    return {
        "status": activity.status,
        "start": activity.start.isoformat(),
        "end": activity.end.isoformat(),
        "label": activity.label,
        "location": activity.location,
        "duration_hours": activity.duration_hours,
        "coordinate": serialize_coordinate(activity.coordinate),
        "meta": activity.meta,
    }


def serialize_stop(stop: Stop) -> Dict:
    return {
        "type": stop.type,
        "start": stop.start.isoformat(),
        "end": stop.end.isoformat(),
        "label": stop.label,
        "location": stop.location,
        "duration_hours": round(stop.duration_hours, 2),
        "coordinate": serialize_coordinate(stop.coordinate),
        "day_index": stop.day_index,
        "meta": stop.meta,
    }


def serialize_coordinate(coordinate: Optional[Tuple[float, float]]) -> Optional[Dict]:
    if not coordinate:
        return None
    lat, lng = coordinate
    return {"lat": lat, "lng": lng}


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def split_activities_for_day(activities: List[Activity], day_start: datetime, day_end: datetime) -> List[Activity]:
    output: List[Activity] = []
    for activity in activities:
        if activity.end <= day_start or activity.start >= day_end:
            continue
        start = max(activity.start, day_start)
        end = min(activity.end, day_end)
        output.append(
            Activity(
                status=activity.status,
                start=start,
                end=end,
                label=activity.label,
                location=activity.location,
                coordinate=activity.coordinate,
                meta=dict(activity.meta),
            )
        )
    output.sort(key=lambda item: item.start)
    return output


def fill_day_gaps(activities: List[Activity], day_start: datetime, day_end: datetime) -> List[Activity]:
    if not activities:
        return [
            Activity(
                status="off_duty",
                start=day_start,
                end=day_end,
                label="Off duty",
                location="",
            )
        ]

    result: List[Activity] = []
    cursor = day_start

    for activity in activities:
        if activity.start > cursor:
            result.append(
                Activity(
                    status="off_duty",
                    start=cursor,
                    end=activity.start,
                    label="Off duty",
                    location="",
                )
            )
        result.append(activity)
        cursor = activity.end

    if cursor < day_end:
        result.append(
            Activity(
                status="off_duty",
                start=cursor,
                end=day_end,
                label="Off duty",
                location="",
            )
        )

    return result


def summarize_status_hours(activities: List[Activity]) -> Dict[str, float]:
    totals = {
        "off_duty": 0.0,
        "sleeper": 0.0,
        "driving": 0.0,
        "on_duty": 0.0,
    }
    for activity in activities:
        totals[activity.status] += activity.duration_hours
    for key, value in totals.items():
        totals[key] = round(value, 2)
    return totals


def build_cumulative_miles(coordinates: List[Tuple[float, float]]) -> List[float]:
    if not coordinates:
        return []

    cumulative = [0.0]
    for index in range(1, len(coordinates)):
        cumulative.append(cumulative[-1] + haversine_miles(coordinates[index - 1], coordinates[index]))
    return cumulative


def interpolate_point(
    coordinates: List[Tuple[float, float]],
    cumulative_miles: List[float],
    miles_along_route: float,
) -> Tuple[float, float]:
    if not coordinates:
        raise ValueError("Cannot interpolate without coordinates.")
    if miles_along_route <= 0:
        return coordinates[0]
    if miles_along_route >= cumulative_miles[-1]:
        return coordinates[-1]

    for index in range(1, len(cumulative_miles)):
        left = cumulative_miles[index - 1]
        right = cumulative_miles[index]
        if miles_along_route <= right:
            span = max(right - left, 1e-9)
            fraction = (miles_along_route - left) / span
            lat1, lng1 = coordinates[index - 1]
            lat2, lng2 = coordinates[index]
            lat = lat1 + (lat2 - lat1) * fraction
            lng = lng1 + (lng2 - lng1) * fraction
            return (lat, lng)
    return coordinates[-1]


def haversine_miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    sin_dlat = math.sin(dlat / 2.0)
    sin_dlon = math.sin(dlon / 2.0)
    h = sin_dlat ** 2 + math.cos(lat1) * math.cos(lat2) * sin_dlon ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(h)))
    earth_radius_miles = 3958.7613
    return earth_radius_miles * c
