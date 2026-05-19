from backend.chat.models import NormalisedWeather, WeatherObservation


def _parse_observation(raw: dict) -> WeatherObservation:
    return WeatherObservation(temp_c=raw["temperature_c"], condition=raw["condition"], humidity=raw["humidity"])


def normalise_weather(data: dict, requested_location: str) -> NormalisedWeather | dict:
    if "error" in data:
        return data

    returned_location = data.get("location", requested_location)

    if "temperature_c" in data:
        observations = [_parse_observation(data)]
    elif "conditions" in data:
        observations = [_parse_observation(o) for o in data["conditions"]]
    else:
        return {"error": "unknown_schema", "message": f"Unrecognised weather shape: {list(data.keys())}"}

    return NormalisedWeather(
        requested_location=requested_location,
        returned_location=returned_location,
        observations=observations,
        note=data.get("note"),
    )
