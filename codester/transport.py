"""Bounded network reads. Upstream errors never echo credentials or response bodies."""

import json
import time

import httpx


class IntegrationError(Exception):
    """An actionable, safe-to-display integration failure."""


def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    deadline = time.monotonic() + 15
    try:
        with httpx.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=8,
            follow_redirects=False,
            trust_env=False,
        ) as response:
            if response.status_code in (401, 403):
                raise IntegrationError("Access denied. Check the saved credentials and read permissions.")
            if response.status_code in (404, 400, 422):
                raise IntegrationError(
                    "API query not supported. Check the base URL and server version."
                )
            if response.status_code == 429:
                raise IntegrationError("Service rate limit reached. Retrying with backoff.")
            if response.status_code != 200:
                raise IntegrationError(
                    f"Service returned HTTP {response.status_code}. Check the connection."
                )
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000 or time.monotonic() > deadline:
                    raise IntegrationError(
                        "Response exceeded the size or time limit. Narrow the query."
                    )
            data = json.loads(content)
            if not isinstance(data, dict):
                raise IntegrationError("Unexpected API response. Check the server version.")
            return data
    except httpx.TimeoutException as exc:
        raise IntegrationError("Service timed out. Check the server and SSH tunnel.") from exc
    except httpx.RequestError as exc:
        raise IntegrationError(
            "Cannot reach service. Check the SSH tunnel; Docker needs a host-reachable URL."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrationError(
            "Expected JSON. Check the API URL or an intervening login page."
        ) from exc


def get_json(url: str, headers: dict | None = None, params: dict | None = None) -> object:
    deadline = time.monotonic() + 15
    try:
        with httpx.stream(
            "GET",
            url,
            headers=headers,
            params=params,
            timeout=8,
            follow_redirects=False,
            trust_env=False,
        ) as response:
            if response.status_code in (401, 403):
                raise IntegrationError("GitHub access denied. Check the token and repository access.")
            if response.status_code == 404:
                raise IntegrationError("GitHub endpoint not found. Check the API base URL.")
            if response.status_code == 429:
                raise IntegrationError("GitHub rate limit reached. Retrying with backoff.")
            if response.status_code != 200:
                raise IntegrationError(
                    f"Service returned HTTP {response.status_code}. Check the connection."
                )
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000 or time.monotonic() > deadline:
                    raise IntegrationError("Response exceeded the size or time limit.")
            return json.loads(content)
    except httpx.TimeoutException as exc:
        raise IntegrationError("Service timed out. Check the network connection.") from exc
    except httpx.RequestError as exc:
        raise IntegrationError("Cannot reach GitHub. Check the network connection.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrationError("GitHub returned an unexpected response.") from exc
