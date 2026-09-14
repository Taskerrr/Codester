"""Bounded, read-only GitHub activity queries."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from codester.transport import IntegrationError, get_json, post_json


def headers(token: str) -> dict[str, str]:
    if not token:
        raise IntegrationError("Add a GitHub personal access token in settings.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def graphql_url(api_url: str) -> str:
    if api_url.rstrip("/").endswith("/api/v3"):
        return api_url.rstrip("/")[:-3] + "graphql"
    return api_url.rstrip("/") + "/graphql"


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def snapshot(config: dict, token: str) -> dict:
    request_headers = headers(token)
    api_url = config["api_url"].rstrip("/")
    browser_url = (config.get("browser_url") or "https://github.com").rstrip("/")
    now = datetime.now(UTC)
    calendar_start = (now - timedelta(days=83)).date().isoformat() + "T00:00:00Z"
    graph = post_json(
        graphql_url(api_url),
        {
            "query": """
              query CodesterActivity($from: DateTime!, $to: DateTime!) {
                viewer {
                  login
                  contributionsCollection(from: $from, to: $to) {
                    contributionCalendar {
                      totalContributions
                      weeks { contributionDays { date contributionCount } }
                    }
                  }
                }
              }
            """,
            "variables": {"from": calendar_start, "to": now.isoformat()},
        },
        request_headers,
    )
    if graph.get("errors"):
        raise IntegrationError("GitHub could not read contribution history. Check token access.")
    try:
        viewer = graph["data"]["viewer"]
        calendar = viewer["contributionsCollection"]["contributionCalendar"]
        login = viewer["login"]
        days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    except (KeyError, TypeError) as exc:
        raise IntegrationError("GitHub returned an unsupported contribution response.") from exc
    if not isinstance(login, str) or not isinstance(days, list):
        raise IntegrationError("GitHub returned an unsupported contribution response.")
    total = calendar.get("totalContributions")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise IntegrationError("GitHub returned an unsupported contribution calendar.")
    normalized_days = []
    for day in days[-84:]:
        if not isinstance(day, dict) or not isinstance(day.get("date"), str):
            raise IntegrationError("GitHub returned an unsupported contribution calendar.")
        count = day.get("contributionCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise IntegrationError("GitHub returned an unsupported contribution calendar.")
        normalized_days.append({"date": day["date"], "count": count})

    repositories = get_json(
        api_url + "/user/repos",
        request_headers,
        {
            "sort": "pushed",
            "direction": "desc",
            "per_page": 3,
            "affiliation": "owner,collaborator,organization_member",
        },
    )
    if not isinstance(repositories, list):
        raise IntegrationError("GitHub returned an unsupported repository response.")
    spark_start = now - timedelta(days=13)
    repos = []
    for repository in repositories[:3]:
        if not isinstance(repository, dict) or not isinstance(repository.get("full_name"), str):
            raise IntegrationError("GitHub returned an unsupported repository response.")
        full_name = repository["full_name"]
        commits = get_json(
            api_url + "/repos/" + quote(full_name, safe="/") + "/commits",
            request_headers,
            {"author": login, "since": spark_start.isoformat(), "per_page": 100},
        )
        if not isinstance(commits, list):
            raise IntegrationError("GitHub returned an unsupported commit response.")
        counts = [0] * 14
        for commit in commits:
            try:
                committed = datetime.fromisoformat(
                    commit["commit"]["author"]["date"].replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            index = (committed.date() - spark_start.date()).days
            if 0 <= index < len(counts):
                counts[index] += 1
        repos.append(
            {
                "name": full_name,
                "description": str(repository.get("description") or "")[:160],
                "private": bool(repository.get("private")),
                "pushed_at": timestamp(repository.get("pushed_at")),
                "commits": counts,
                "url": browser_url + "/" + quote(full_name, safe="/"),
            }
        )
    return {
        "login": login,
        "total": total,
        "days": normalized_days,
        "repositories": repos,
        "url": browser_url + "/" + quote(login, safe=""),
    }
