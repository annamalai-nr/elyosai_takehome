import asyncio
import logging

import httpx
from langsmith import traceable

log = logging.getLogger(__name__)

MAX_THROTTLE_RETRIES: int = 5


@traceable(run_type="tool", name="elyos_api_call")
async def call_api(
    client: httpx.AsyncClient, base_url: str, endpoint: str, params: dict, api_key: str,
) -> dict:
    timeout = 20.0 if endpoint == "/research" else 15.0

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
        await asyncio.sleep(wait)

    return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}
