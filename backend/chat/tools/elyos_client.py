import asyncio
import logging
import os

import httpx
from langsmith import traceable

log = logging.getLogger(__name__)

MAX_THROTTLE_RETRIES: int = 5


async def _call_api(
    client: httpx.AsyncClient, base_url: str, endpoint: str, params: dict, api_key: str, timeout: float,
) -> dict:
    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        log.debug("API request: GET %s params=%s (attempt %d)", endpoint, params, attempt + 1)
        try:
            resp = await client.get(
                f"{base_url}{endpoint}",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=timeout,
            )
        except httpx.TimeoutException:
            log.warning("Timeout on %s after %.0fs", endpoint, timeout)
            return {"error": "request_timeout", "message": f"{endpoint} request timed out"}
        except httpx.HTTPError as exc:
            log.warning("HTTP error on %s: %s", endpoint, exc)
            return {"error": "http_error", "message": str(exc)}

        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            return {"error": f"http_{resp.status_code}", "message": body}

        try:
            data = resp.json()
        except Exception:
            return {"error": "invalid_json", "message": f"{endpoint} returned non-JSON body"}

        if not (isinstance(data, dict) and data.get("status") == "throttled"):
            return data

        wait = data.get("retry_after_seconds", 30) + 1
        if attempt >= MAX_THROTTLE_RETRIES:
            log.warning("Throttle retries exhausted on %s", endpoint)
            return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}
        log.warning("Throttled on %s, retrying in %ds (attempt %d/%d)", endpoint, wait, attempt + 1, MAX_THROTTLE_RETRIES)
        print(f"\r  Rate-limited, retrying in {wait}s...", flush=True)
        await asyncio.sleep(wait)

    return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}


@traceable(run_type="tool", name="elyos_weather_call")
async def get_weather(client: httpx.AsyncClient, cfg: dict, location: str) -> dict:
    base_url = cfg["elyos_api"]["base_url"]
    api_key = os.environ[cfg["elyos_api"]["api_key_env"]]
    return await _call_api(client, base_url, "/weather", {"location": location}, api_key, timeout=15.0)


@traceable(run_type="tool", name="elyos_research_call")
async def research_topic(client: httpx.AsyncClient, cfg: dict, topic: str) -> dict:
    base_url = cfg["elyos_api"]["base_url"]
    api_key = os.environ[cfg["elyos_api"]["api_key_env"]]
    return await _call_api(client, base_url, "/research", {"topic": topic}, api_key, timeout=20.0)
