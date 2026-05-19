"""Elyos API HTTP client with throttle and timeout retry."""

import asyncio
import logging
import os

import httpx
from langsmith import traceable

log = logging.getLogger(__name__)


def _retry_after(data: dict) -> float:
    try:
        return max(float(data.get("retry_after_seconds") or 30), 0) + 1
    except (TypeError, ValueError):
        return 31


async def _call_api(
    client: httpx.AsyncClient, base_url: str, endpoint: str,
    params: dict, api_key: str, endpoint_cfg: dict, max_throttle_retries: int,
) -> dict:
    """Make a GET request with timeout and throttle retry."""
    timeout = endpoint_cfg["timeout_s"]
    max_timeout = endpoint_cfg.get("max_timeout_retries", 0)

    throttle_attempts = 0
    timeout_attempts = 0

    while True:
        log.debug("API request: GET %s params=%s (throttle=%d/%d, timeout=%d/%d)",
                   endpoint, params, throttle_attempts, max_throttle_retries, timeout_attempts, max_timeout)
        try:
            resp = await client.get(
                f"{base_url}{endpoint}",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException:
            timeout_attempts += 1
            if timeout_attempts > max_timeout:
                log.warning("Timeout retries exhausted on %s", endpoint)
                return {"error": "request_timeout", "message": f"{endpoint} request timed out after {timeout_attempts} attempts"}
            log.warning("Timeout on %s, retrying (attempt %d/%d)", endpoint, timeout_attempts, max_timeout)
            print(f"\r  Timed out, retrying...", flush=True)
            await asyncio.sleep(1)
            continue
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

        throttle_attempts += 1
        wait = _retry_after(data)
        if throttle_attempts > max_throttle_retries:
            log.warning("Throttle retries exhausted on %s", endpoint)
            return {"error": "throttle_exhausted", "message": "Rate limit retries exhausted"}
        log.warning("Throttled on %s, retrying in %ds (attempt %d/%d)", endpoint, int(wait), throttle_attempts, max_throttle_retries)
        print(f"\r  Rate-limited, retrying in {int(wait)}s...", flush=True)
        await asyncio.sleep(wait)


def _endpoint_args(cfg: dict, endpoint_name: str) -> tuple[str, str, dict, int]:
    api_cfg = cfg["elyos_api"]
    ep_cfg = api_cfg["endpoints"][endpoint_name]
    max_throttle = api_cfg["rate_limit"]["max_throttle_retries"]
    return api_cfg["base_url"], os.environ[api_cfg["api_key_env"]], ep_cfg, max_throttle


@traceable(run_type="tool", name="elyos_weather_call")
async def get_weather(client: httpx.AsyncClient, cfg: dict, location: str) -> dict:
    base_url, api_key, ep_cfg, max_throttle = _endpoint_args(cfg, "weather")
    return await _call_api(client, base_url, ep_cfg["path"], {"location": location}, api_key, ep_cfg, max_throttle)


@traceable(run_type="tool", name="elyos_research_call")
async def research_topic(client: httpx.AsyncClient, cfg: dict, topic: str) -> dict:
    base_url, api_key, ep_cfg, max_throttle = _endpoint_args(cfg, "research")
    return await _call_api(client, base_url, ep_cfg["path"], {"topic": topic}, api_key, ep_cfg, max_throttle)
