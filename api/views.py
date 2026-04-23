from datetime import datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import TripPlanRequestSerializer
from .services.geocoding import GeocodingError, geocode
from .services.routing import RoutingError, get_route
from .services.hos import HOSPlanner, PlannerInput


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class TripPlanView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = TripPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            current = geocode(data["current_location"])
            pickup = geocode(data["pickup_location"])
            dropoff = geocode(data["dropoff_location"])

            route = get_route(
                points=[current, pickup, dropoff],
                names=[current.display_name, pickup.display_name, dropoff.display_name],
            )

            planner = HOSPlanner(
                PlannerInput(
                    current_location_label=current.display_name,
                    pickup_location_label=pickup.display_name,
                    dropoff_location_label=dropoff.display_name,
                    route_coordinates=route.coordinates,
                    leg_distances_miles=[leg.distance_miles for leg in route.legs],
                    leg_durations_hours=[leg.duration_hours for leg in route.legs],
                    current_cycle_used=data["current_cycle_used"],
                    start_time=datetime.utcnow().replace(second=0, microsecond=0),
                    current_coordinate=(current.lat, current.lon),
                    pickup_coordinate=(pickup.lat, pickup.lon),
                    dropoff_coordinate=(dropoff.lat, dropoff.lon),
                )
            )
            payload = planner.plan()

            payload["input"] = {
                "current_location": current.display_name,
                "pickup_location": pickup.display_name,
                "dropoff_location": dropoff.display_name,
                "current_cycle_used": data["current_cycle_used"],
            }

            return Response(payload, status=status.HTTP_200_OK)

        except (GeocodingError, RoutingError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {"detail": f"Unexpected planner error: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
