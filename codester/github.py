"""Bounded, read-only GitHub activity queries."""

from collections.abc import Callable
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


def snapshot(
    config: dict,
    token: str,
    *,
    calendar: dict | None = None,
    history: dict | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict:
    request_headers = headers(token)
    api_url = config["api_url"].rstrip("/")
    browser_url = (config.get("browser_url") or "https://github.com").rstrip("/")
    now = datetime.now(UTC)
    calendar_start = (now - timedelta(days=181)).date().isoformat() + "T00:00:00Z"
    organization = config.get("organization", "")
    graph = (
        cached_calendar_graph(calendar)
        if calendar is not None
        else organization_calendar(api_url, request_headers, now)
        if organization
        else post_json(
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
    )
    if graph.get("errors"):
        raise IntegrationError("GitHub could not read contribution history. Check token access.")
    try:
        viewer = graph["data"]["viewer"]
        contribution_calendar = viewer["contributionsCollection"]["contributionCalendar"]
        login = viewer["login"]
        days = [day for week in contribution_calendar["weeks"] for day in week["contributionDays"]]
    except (KeyError, TypeError) as exc:
        raise IntegrationError("GitHub returned an unsupported contribution response.") from exc
    if not isinstance(login, str) or not isinstance(days, list):
        raise IntegrationError("GitHub returned an unsupported contribution response.")
    total = contribution_calendar.get("totalContributions")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise IntegrationError("GitHub returned an unsupported contribution calendar.")
    normalized_days = []
    for day in days[-182:]:
        if not isinstance(day, dict) or not isinstance(day.get("date"), str):
            raise IntegrationError("GitHub returned an unsupported contribution calendar.")
        count = day.get("contributionCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise IntegrationError("GitHub returned an unsupported contribution calendar.")
        normalized_days.append({"date": day["date"], "count": count})

    configured = config.get("repositories", [])
    repository_results_limited = False
    if organization:
        repositories = []
        page_size = 3 if calendar is not None else 100
        for page in range(1, 2 if calendar is not None else 11):
            batch = get_json(
                api_url + "/orgs/" + quote(organization, safe="") + "/repos",
                request_headers,
                {
                    "type": "all",
                    "sort": "pushed",
                    "direction": "desc",
                    "per_page": page_size,
                    "page": page,
                },
            )
            if not isinstance(batch, list):
                raise IntegrationError("GitHub returned an unsupported repository response.")
            # Enforce the owner boundary even if an upstream response is unexpected.
            for repository in batch:
                if (
                    not isinstance(repository, dict)
                    or not isinstance(repository.get("full_name"), str)
                    or repository["full_name"].split("/")[0].casefold() != organization.casefold()
                ):
                    raise IntegrationError(
                        "GitHub returned a repository outside the chosen organisation."
                    )
            repositories.extend(batch)
            if len(batch) < page_size:
                break
        else:
            repository_results_limited = True
    elif configured:
        repositories = [
            get_json(
                api_url + "/repos/" + quote(repository["repo"], safe="/"),
                request_headers,
            )
            for repository in configured[:3]
        ]
    else:
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
    commits_start = (
        spark_start.date().isoformat() + "T00:00:00Z" if calendar is not None else calendar_start
    )
    commit_counts_by_date: dict[str, int] = {}
    commit_results_limited = False
    repos = []
    for repository in repositories:
        if checkpoint is not None:
            checkpoint()
        if not isinstance(repository, dict) or not isinstance(repository.get("full_name"), str):
            raise IntegrationError("GitHub returned an unsupported repository response.")
        full_name = repository["full_name"]
        daily, limited = repository_days(
            api_url, request_headers, repository, login, commits_start, now, history
        )
        commit_results_limited |= limited
        counts = [0] * 14
        for committed_date, count in daily.items():
            commit_counts_by_date[committed_date] = (
                commit_counts_by_date.get(committed_date, 0) + count
            )
            index = (datetime.fromisoformat(committed_date).date() - spark_start.date()).days
            if 0 <= index < len(counts):
                counts[index] += count
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
        if checkpoint is not None:
            checkpoint()
    calendar_source = calendar["calendar_source"] if calendar is not None else "github"
    if calendar is None and (organization or (total == 0 and any(commit_counts_by_date.values()))):
        normalized_days = [
            {"date": day["date"], "count": commit_counts_by_date.get(day["date"], 0)}
            for day in normalized_days
        ]
        total = sum(day["count"] for day in normalized_days)
        calendar_source = "repository_commits"
    return {
        "login": login,
        "total": total,
        "days": normalized_days,
        "calendar_source": calendar_source,
        "calendar_limited": calendar["calendar_limited"]
        if calendar is not None
        else (
            calendar_source == "repository_commits"
            and (commit_results_limited or repository_results_limited)
        ),
        "calendar_repository_count": calendar["calendar_repository_count"]
        if calendar is not None
        else len(repos),
        "calendar_updated_at": calendar["calendar_updated_at"]
        if calendar is not None
        else now.timestamp(),
        "repositories_updated_at": now.timestamp(),
        "organization": organization,
        "repositories": repos[:3],
        "url": browser_url + "/" + quote(login, safe=""),
    }


def repository_days(
    api_url: str,
    request_headers: dict,
    repository: dict,
    login: str,
    since: str,
    now: datetime,
    history: dict | None,
) -> tuple[dict[str, int], bool]:
    """Retain old daily counts and replace the overlapping recent window atomically."""
    name = repository["full_name"]
    previous = history.get(name) if history is not None else None
    floor = since[:10]
    full_refresh = (
        previous is None or now.timestamp() - previous.get("full_updated_at", 0) >= 30 * 86400
    )
    if not full_refresh:
        kept = {
            day: count
            for day, count in previous["days"].items()
            if floor <= day <= now.date().isoformat()
        }
        if repository.get("pushed_at") is not None and repository["pushed_at"] == previous.get(
            "pushed_at"
        ):
            return kept, previous["limited"]
        # Include a longer gap after downtime, with a one-day overlap at the boundary.
        last_read = datetime.fromtimestamp(previous["updated_at"], UTC) - timedelta(days=1)
        since = (
            max(floor, min(now - timedelta(days=6), last_read).date().isoformat()) + "T00:00:00Z"
        )
    else:
        kept = {}
    recent: dict[str, int] = {}
    limited = False
    for page in range(1, 4):
        batch = get_json(
            api_url + "/repos/" + quote(name, safe="/") + "/commits",
            request_headers,
            {"author": login, "since": since, "per_page": 100, "page": page},
            allow_empty_repository=True,
        )
        if not isinstance(batch, list):
            raise IntegrationError("GitHub returned an unsupported commit response.")
        for commit in batch:
            try:
                day = (
                    datetime.fromisoformat(
                        commit["commit"]["author"]["date"].replace("Z", "+00:00")
                    )
                    .astimezone(UTC)
                    .date()
                    .isoformat()
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if since[:10] <= day <= now.date().isoformat():
                recent[day] = recent.get(day, 0) + 1
        if len(batch) < 100:
            break
    else:
        limited = True
    # Replacement, rather than addition, avoids double-counting overlapping reads.
    days = {day: count for day, count in kept.items() if day < since[:10]}
    days.update(recent)
    limited = limited or (not full_refresh and previous["limited"])
    if history is not None:
        history[name] = {
            "days": days,
            "updated_at": now.timestamp(),
            "pushed_at": repository.get("pushed_at"),
            "full_updated_at": now.timestamp() if full_refresh else previous["full_updated_at"],
            "limited": limited,
        }
    return days, limited


def empty_calendar(config: dict, token: str) -> dict:
    """Authenticate for quick repository charts without waiting for historical queries."""
    viewer = get_json(config["api_url"].rstrip("/") + "/user", headers(token))
    if not isinstance(viewer, dict) or not isinstance(viewer.get("login"), str):
        raise IntegrationError("GitHub returned an unsupported user response.")
    return {
        "login": viewer["login"],
        "total": 0,
        "days": [],
        "calendar_source": "repository_commits" if config.get("organization") else "github",
        "calendar_limited": False,
        "calendar_repository_count": 0,
        "calendar_updated_at": None,
    }


def cached_calendar_graph(calendar: dict) -> dict:
    """Reuse the calendar while querying only recent repository activity."""
    return {
        "data": {
            "viewer": {
                "login": calendar["login"],
                "contributionsCollection": {
                    "contributionCalendar": {
                        "totalContributions": calendar["total"],
                        "weeks": [
                            {
                                "contributionDays": [
                                    {"date": day["date"], "contributionCount": day["count"]}
                                    for day in calendar["days"]
                                ]
                            }
                        ],
                    }
                },
            }
        }
    }


def organization_calendar(api_url: str, request_headers: dict, now: datetime) -> dict:
    """Start a commit-only calendar without fetching account-wide contributions."""
    viewer = get_json(api_url + "/user", request_headers)
    if not isinstance(viewer, dict) or not isinstance(viewer.get("login"), str):
        raise IntegrationError("GitHub returned an unsupported user response.")
    return {
        "data": {
            "viewer": {
                "login": viewer["login"],
                "contributionsCollection": {
                    "contributionCalendar": {
                        "totalContributions": 0,
                        "weeks": [
                            {
                                "contributionDays": [
                                    {
                                        "date": (now - timedelta(days=offset)).date().isoformat(),
                                        "contributionCount": 0,
                                    }
                                    for offset in range(181, -1, -1)
                                ]
                            }
                        ],
                    }
                },
            }
        }
    }
