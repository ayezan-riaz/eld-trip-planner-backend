from rest_framework import serializers


class TripPlanRequestSerializer(serializers.Serializer):
    current_location = serializers.CharField(max_length=255)
    pickup_location = serializers.CharField(max_length=255)
    dropoff_location = serializers.CharField(max_length=255)
    current_cycle_used = serializers.FloatField(min_value=0, max_value=70)

    def validate(self, attrs):
        if attrs["current_location"].strip().lower() == attrs["pickup_location"].strip().lower() == attrs["dropoff_location"].strip().lower():
            raise serializers.ValidationError("Current, pickup, and dropoff locations should not all be identical.")
        return attrs
