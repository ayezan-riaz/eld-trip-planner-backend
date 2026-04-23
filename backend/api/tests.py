from datetime import datetime
from django.test import SimpleTestCase

from .services.hos import HOSPlanner, PlannerInput


class HOSPlannerTests(SimpleTestCase):
    def test_inserts_break_for_long_drive(self):
        planner = HOSPlanner(
            PlannerInput(
                current_location_label="A",
                pickup_location_label="B",
                dropoff_location_label="C",
                route_coordinates=[(32.0, -96.0), (33.0, -95.0), (34.0, -84.0)],
                leg_distances_miles=[500.0, 300.0],
                leg_durations_hours=[9.0, 5.0],
                current_cycle_used=10.0,
                start_time=datetime(2026, 1, 1, 6, 0),
                current_coordinate=(32.0, -96.0),
                pickup_coordinate=(33.0, -95.0),
                dropoff_coordinate=(34.0, -84.0),
            )
        )
        payload = planner.plan()
        stop_types = [stop["type"] for stop in payload["stops"]]
        self.assertIn("break", stop_types)

    def test_inserts_cycle_restart_when_cycle_is_exhausted(self):
        planner = HOSPlanner(
            PlannerInput(
                current_location_label="A",
                pickup_location_label="B",
                dropoff_location_label="C",
                route_coordinates=[(32.0, -96.0), (33.0, -95.0), (34.0, -84.0)],
                leg_distances_miles=[200.0, 200.0],
                leg_durations_hours=[4.0, 4.0],
                current_cycle_used=69.5,
                start_time=datetime(2026, 1, 1, 6, 0),
                current_coordinate=(32.0, -96.0),
                pickup_coordinate=(33.0, -95.0),
                dropoff_coordinate=(34.0, -84.0),
            )
        )
        payload = planner.plan()
        stop_types = [stop["type"] for stop in payload["stops"]]
        self.assertIn("cycle_restart", stop_types)

    def test_generates_daily_logs(self):
        planner = HOSPlanner(
            PlannerInput(
                current_location_label="A",
                pickup_location_label="B",
                dropoff_location_label="C",
                route_coordinates=[(32.0, -96.0), (33.0, -95.0), (34.0, -84.0)],
                leg_distances_miles=[100.0, 100.0],
                leg_durations_hours=[2.0, 2.0],
                current_cycle_used=5.0,
                start_time=datetime(2026, 1, 1, 6, 0),
                current_coordinate=(32.0, -96.0),
                pickup_coordinate=(33.0, -95.0),
                dropoff_coordinate=(34.0, -84.0),
            )
        )
        payload = planner.plan()
        self.assertGreaterEqual(len(payload["days"]), 1)
        self.assertIn("status_totals", payload["days"][0])
