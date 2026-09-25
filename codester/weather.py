"""Opt-in weather, fixed public endpoints, bounded reads and shared hourly caching."""

import json
import math
import random
import re
import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from codester.store import ConfigurationError, Store
from codester.transport import IntegrationError

USER_AGENT = "Codester/0.1 (https://github.com/Taskerrr/Codester)"
FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
SEARCH_URL = "https://photon.komoot.io/api/"


def request_json(url: str, params: dict, headers: dict) -> tuple[object, dict, int]:
    deadline = time.monotonic() + 12
    try:
        with httpx.stream(
            "GET",
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, **headers},
            timeout=8,
            follow_redirects=True,
            trust_env=False,
        ) as response:
            if response.status_code == 304:
                return {}, dict(response.headers), 304
            if response.status_code not in {200, 203}:
                raise IntegrationError("Weather provider unavailable. Retrying later.")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 1_000_000 or time.monotonic() > deadline:
                    raise IntegrationError("Weather response exceeded the size or time limit.")
            return json.loads(content), dict(response.headers), response.status_code
    except (httpx.HTTPError, ValueError) as error:
        raise IntegrationError("Could not read weather. Check your internet connection.") from error


def rows_from_forecast(payload: object) -> list[dict]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("Missing forecast")
        series = payload["properties"]["timeseries"]
        if not isinstance(series, list):
            raise ValueError("Missing forecast")
        rows = []
        for item in series[:200]:
            stamp = datetime.fromisoformat(item["time"])
            if stamp.tzinfo is None:
                raise ValueError("Missing timezone")
            temperature = item["data"]["instant"]["details"]["air_temperature"]
            if type(temperature) not in (int, float) or not math.isfinite(temperature):
                raise ValueError("Invalid temperature")
            symbol = (
                item["data"]
                .get("next_1_hours", {})
                .get("summary", {})
                .get("symbol_code", "unknown")
            )
            if not isinstance(symbol, str) or not re.fullmatch(r"[a-z_]{1,60}", symbol):
                symbol = "unknown"
            rows.append(
                {"time": int(stamp.timestamp()), "temperature": temperature, "symbol": symbol}
            )
        if not rows:
            raise ValueError("Empty forecast")
        return sorted(rows, key=lambda row: row["time"])
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as error:
        raise IntegrationError("Weather provider returned an incomplete forecast.") from error


class Weather:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.lock = threading.Lock()
        self.signature: tuple | None = None
        self.rows: list[dict] = []
        self.next_fetch: float = 0
        self.fetched: float = 0
        self.modified: str = ""
        self.problem: str = ""
        self.search_lock = threading.Lock()
        self.search_next: float = 0
        self.search_cache: dict[str, list[dict]] = {}

    def search(self, query: object) -> list[dict]:
        if (
            not isinstance(query, str)
            or not 2 <= len(query.strip()) <= 100
            or any(ord(c) < 32 for c in query)
        ):
            raise ConfigurationError("Enter a town or city (2 to 100 characters).")
        query = query.strip()
        with self.search_lock:
            if query.casefold() in self.search_cache:
                return self.search_cache[query.casefold()]
            if time.monotonic() < self.search_next:
                raise ConfigurationError("Please wait a moment before searching again.")
            self.search_next = time.monotonic() + 2
            params = {"q": query, "limit": 5, "lang": "en", "layer": ["city", "locality"]}
            country = re.fullmatch(r"(.+),\s*([A-Za-z]{2})", query)
            if country is not None:
                params["q"] = country[1].strip()
                params["countrycode"] = "GB" if country[2].upper() == "UK" else country[2].upper()
            payload, _, _ = request_json(SEARCH_URL, params, {})
            try:
                if not isinstance(payload, dict):
                    raise ValueError("Invalid search response")
                results = []
                for item in payload["features"][:5]:
                    lon, lat = item["geometry"]["coordinates"]
                    if any(
                        type(value) not in (int, float) or not math.isfinite(value)
                        for value in (lat, lon)
                    ) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    props = item["properties"]
                    parts = [props.get(key) for key in ("name", "state", "country")]
                    label = ", ".join(
                        dict.fromkeys(part for part in parts if isinstance(part, str) and part)
                    )[:200]
                    if label:
                        results.append(
                            {
                                "location": label,
                                "latitude": round(lat, 3),
                                "longitude": round(lon, 3),
                            }
                        )
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise IntegrationError("Town search is unavailable. Try again later.") from error
            if len(self.search_cache) >= 30:
                self.search_cache.pop(next(iter(self.search_cache)))
            self.search_cache[query.casefold()] = results
            return results

    def read(self) -> dict:
        with self.lock:
            settings = self.store.read()
            config = settings["weather"]
            base = {"location": config["location"], "units": config["units"], "hours": []}
            if not config["enabled"]:
                return {**base, "state": "disabled"}
            if settings["demo"]:
                now = int(time.time()) // 3600 * 3600
                sample = [
                    {
                        "time": now + hour * 3600,
                        "temperature": 16 + hour % 3,
                        "symbol": "partlycloudy_day",
                    }
                    for hour in range(7)
                ]
                return {
                    **base,
                    "state": "demo",
                    "current": sample[0],
                    "hours": sample[1:],
                    "updated": now,
                }
            signature = (config["latitude"], config["longitude"])
            if signature != self.signature:
                self.signature = signature
                self.rows = []
                self.modified = ""
                self.next_fetch = 0
                self.fetched = 0
                self.problem = ""
            if time.monotonic() >= self.next_fetch:
                self.next_fetch = time.monotonic() + 900
                try:
                    payload, headers, status = request_json(
                        FORECAST_URL,
                        {"lat": f"{signature[0]:.3f}", "lon": f"{signature[1]:.3f}"},
                        {"If-Modified-Since": self.modified} if self.modified else {},
                    )
                    if status != 304:
                        rows = rows_from_forecast(payload)
                        self.rows = rows
                        self.modified = headers.get("last-modified", "")
                    if not self.rows:
                        raise IntegrationError("Weather provider returned no forecast.")
                    self.fetched = time.time()
                    self.problem = (
                        "Weather provider version is deprecated." if status == 203 else ""
                    )
                    delay = 3600 + random.uniform(0, 120)
                    if headers.get("expires"):
                        try:
                            delay = max(
                                delay,
                                parsedate_to_datetime(headers["expires"]).timestamp() - time.time(),
                            )
                        except (ValueError, TypeError, OverflowError):
                            # A malformed optional header does not invalidate the forecast.
                            pass
                    self.next_fetch = time.monotonic() + delay
                except IntegrationError as error:
                    self.problem = str(error)
            now = time.time()
            past = [row for row in self.rows if now - 5400 <= row["time"] <= now]
            if not past or now - self.fetched > 21600:
                return {
                    **base,
                    "state": "unavailable",
                    "message": self.problem or "Current weather is unavailable.",
                }
            return {
                **base,
                "state": "stale" if self.problem or now - self.fetched > 7200 else "ready",
                "current": past[-1],
                "hours": [row for row in self.rows if now < row["time"] <= now + 21600][:6],
                "updated": self.fetched,
                "message": self.problem,
            }
