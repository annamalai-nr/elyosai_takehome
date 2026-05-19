"""/weather response normalisation (Shape A flat, Shape B multi-observation)."""

import logging

from backend.chat.models import NormalisedWeather, WeatherObservation

log = logging.getLogger(__name__)


def _parse_observation(raw: dict) -> WeatherObservation:
    return WeatherObservation(temp_c=raw["temperature_c"], condition=raw["condition"], humidity=raw["humidity"])


def normalise_weather(data: dict, requested_location: str) -> NormalisedWeather | dict:
    """Normalise a /weather response into NormalisedWeather, or pass through error dicts."""
    if "error" in data:
        return data

    returned_location = data.get("location", requested_location)

    if "temperature_c" in data:
        observations = [_parse_observation(data)]
    elif "conditions" in data:
        observations = [_parse_observation(o) for o in data["conditions"]]
    else:
        log.warning("Unknown weather schema for %s: keys=%s", requested_location, list(data.keys()))
        return {"error": "unknown_schema", "message": f"Unrecognised weather shape: {list(data.keys())}"}

    if requested_location != returned_location:
        log.info("Weather location mismatch: requested=%s returned=%s", requested_location, returned_location)

    return NormalisedWeather(
        requested_location=requested_location,
        returned_location=returned_location,
        observations=observations,
        note=data.get("note"),
    )
