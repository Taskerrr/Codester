import copy
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from codester.app import create_app
from codester.store import DEFAULTS, ConfigurationError, Store, validate
from codester.transport import IntegrationError
from codester.weather import Weather, rows_from_forecast

NOW = 1800000000 // 3600 * 3600 + 900


def forecast():
    return {
        "properties": {
            "timeseries": [
                {
                    "time": datetime.fromtimestamp(
                        NOW // 3600 * 3600 + hour * 3600, UTC
                    ).isoformat(),
                    "data": {
                        "instant": {"details": {"air_temperature": 14 + hour}},
                        "next_1_hours": {"summary": {"symbol_code": "partlycloudy_day"}},
                    },
                }
                for hour in range(24)
            ]
        }
    }


@pytest.fixture
def weather(monkeypatch):
    settings = copy.deepcopy(DEFAULTS)
    settings["demo"] = False
    settings["weather"] = {
        "enabled": True,
        "location": "Bristol, UK",
        "latitude": 51.454,
        "longitude": -2.588,
        "units": "celsius",
    }
    service = Weather(SimpleNamespace(read=lambda: settings))
    monkeypatch.setattr("codester.weather.time.time", lambda: NOW)
    request = Mock(
        return_value=(forecast(), {"last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"}, 200)
    )
    monkeypatch.setattr("codester.weather.request_json", request)
    return service, settings, request


def test_current_and_next_six_hours(weather):
    service, _, request = weather
    data = service.read()
    assert data["state"] == "ready"
    assert data["current"]["temperature"] == 14
    assert len(data["hours"]) == 6
    assert all(row["time"] > NOW for row in data["hours"])
    assert request.call_args.args[1] == {"lat": "51.454", "lon": "-2.588"}


def test_cache_and_conditional_request(weather):
    service, _, request = weather
    service.read()
    service.read()
    assert request.call_count == 1
    service.next_fetch = 0
    request.return_value = ({}, {}, 304)
    assert service.read()["state"] == "ready"
    assert "If-Modified-Since" in request.call_args.args[2]


def test_failure_retains_same_location_and_backs_off(weather):
    service, _, request = weather
    service.read()
    service.next_fetch = 0
    request.side_effect = IntegrationError("Offline")
    data = service.read()
    assert data["state"] == "stale"
    assert data["current"]["temperature"] == 14
    service.read()
    assert request.call_count == 2


def test_changed_location_never_displays_previous_weather(weather):
    service, settings, request = weather
    service.read()
    settings["weather"].update(location="London", latitude=51.507, longitude=-0.128)
    request.side_effect = IntegrationError("Offline")
    data = service.read()
    assert data["state"] == "unavailable"
    assert "current" not in data
    assert data["location"] == "London"


@pytest.mark.parametrize("mode", ["demo", "disabled"])
def test_no_automatic_requests_in_demo_or_disabled_mode(weather, mode):
    service, settings, request = weather
    if mode == "demo":
        settings["demo"] = True
    else:
        settings["weather"]["enabled"] = False
    assert service.read()["state"] == mode
    request.assert_not_called()


def test_old_cache_is_not_current(weather, monkeypatch):
    service, _, _ = weather
    service.read()
    monkeypatch.setattr("codester.weather.time.time", lambda: NOW + 22000)
    assert service.read()["state"] == "unavailable"


def test_units_change_does_not_fetch_again(weather):
    service, settings, request = weather
    service.read()
    settings["weather"]["units"] = "fahrenheit"
    assert service.read()["units"] == "fahrenheit"
    assert request.call_count == 1


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"properties": {"timeseries": []}},
        {"properties": {"timeseries": [{"time": "bad"}]}},
    ],
)
def test_malformed_forecasts_are_safe(payload):
    with pytest.raises(IntegrationError):
        rows_from_forecast(payload)


def test_null_temperature_is_not_zero():
    payload = forecast()
    payload["properties"]["timeseries"][0]["data"]["instant"]["details"]["air_temperature"] = None
    with pytest.raises(IntegrationError):
        rows_from_forecast(payload)


def test_search_is_cached_and_throttled(weather):
    service, _, request = weather
    request.return_value = (
        {
            "features": [
                {
                    "geometry": {"coordinates": [-2.588123, 51.454123]},
                    "properties": {"name": "Bristol", "country": "UK"},
                }
            ]
        },
        {},
        200,
    )
    result = service.search("Bristol")
    assert result == [{"location": "Bristol, UK", "latitude": 51.454, "longitude": -2.588}]
    assert service.search("BRISTOL") == result
    assert request.call_count == 1
    with pytest.raises(ConfigurationError, match="wait"):
        service.search("London")


def test_uk_suffix_is_a_country_filter(weather):
    service, _, request = weather
    request.return_value = ({"features": []}, {}, 200)
    service.search("London, UK")
    assert request.call_args.args[1]["countrycode"] == "GB"
    assert request.call_args.args[1]["q"] == "London"


def test_provider_expiry_is_respected(weather, monkeypatch):
    service, _, request = weather
    monkeypatch.setattr("codester.weather.time.monotonic", lambda: 100)
    expires = datetime.fromtimestamp(NOW + 8000, UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    request.return_value = (forecast(), {"expires": expires}, 200)
    service.read()
    assert service.next_fetch == 8100


def test_weather_units_rejects_non_scalar_values():
    settings = copy.deepcopy(DEFAULTS)
    settings["weather"]["units"] = []
    with pytest.raises(ConfigurationError):
        validate(settings)


@pytest.mark.parametrize("query", [None, "", "a", "x" * 101, "London\nUK"])
def test_invalid_search_never_requests(weather, query):
    service, _, request = weather
    with pytest.raises(ConfigurationError):
        service.search(query)
    request.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", True),
        ("latitude", float("nan")),
        ("latitude", 91),
        ("longitude", -181),
        ("longitude", "1"),
        ("units", "kelvin"),
        ("enabled", "true"),
        ("location", "\n"),
    ],
)
def test_settings_validation(field, value):
    settings = copy.deepcopy(DEFAULTS)
    settings["weather"][field] = value
    with pytest.raises(ConfigurationError):
        validate(settings)


def test_weather_requires_location_when_enabled():
    settings = copy.deepcopy(DEFAULTS)
    settings["weather"]["enabled"] = True
    with pytest.raises(ConfigurationError, match="town"):
        validate(settings)


def test_weather_saved_without_changing_other_settings(tmp_path):
    store = Store(tmp_path)
    before = store.read()
    config = copy.deepcopy(before)
    config["weather"] = {
        "enabled": True,
        "location": "Bristol",
        "latitude": 51.45412,
        "longitude": -2.58812,
        "units": "fahrenheit",
    }
    store.save(config)
    after = Store(tmp_path).read()
    assert after["weather"]["latitude"] == 51.454
    assert after["weather"]["units"] == "fahrenheit"
    assert {k: v for k, v in after.items() if k != "weather"} == {
        k: v for k, v in before.items() if k != "weather"
    }


def test_weather_api_and_search_csrf(tmp_path, monkeypatch):
    client = create_app(tmp_path, start_poller=False).test_client()
    assert client.get("/api/weather").json["state"] == "disabled"
    assert client.post("/api/weather/locations", json={"query": "Bristol"}).status_code == 403
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text)[1]
    monkeypatch.setattr(Weather, "search", lambda self, query: [])
    assert client.post(
        "/api/weather/locations", json={"query": "Bristol"}, headers={"X-Codester-CSRF": token}
    ).json == {"locations": []}
