from typing import Literal

from pydantic import BaseModel


class WeatherObservation(BaseModel):
    temp_c: float
    condition: str
    humidity: int | float


class NormalisedWeather(BaseModel):
    requested_location: str
    returned_location: str
    observations: list[WeatherObservation]
    note: str | None = None


class ResearchResult(BaseModel):
    kind: Literal["fresh", "cached", "truncated", "timeout"]
    topic: str = ""
    summary: str = ""
    sources: list = []
    cache_age_seconds: int | None = None
    stale_warning: str | None = None
    processed_topic: str | None = None
    original_topic_length: int | None = None
    message: str | None = None
