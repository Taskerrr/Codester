import copy
from datetime import UTC, datetime

import httpx
import pytest

from codester import github
from codester.store import DEFAULTS, ConfigurationError, validate
from codester.transport import IntegrationError, get_json


def test_organization_paginates_and_counts_beyond_three_repositories(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        path = request.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "jack"})
        if path == "/orgs/TMPlant/repos":
            page = int(request.url.params["page"])
            indices = range(100) if page == 1 else [100]
            return httpx.Response(200, json=[{"full_name": f"TMPlant/repo{i}"} for i in indices])
        assert path.startswith("/repos/TMPlant/")
        assert request.url.params["author"] == "jack"
        if path == "/repos/TMPlant/repo0/commits":
            return httpx.Response(409, json={"message": "Git Repository is empty."})
        return httpx.Response(
            200, json=[{"commit": {"author": {"date": datetime.now(UTC).isoformat()}}}]
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(
            httpx, "stream", lambda *args, trust_env=False, **kwargs: client.stream(*args, **kwargs)
        )
        result = github.snapshot(
            {"api_url": "https://api.github.com", "organization": "TMPlant"}, "secret"
        )
    assert result["calendar_repository_count"] == 101
    assert result["total"] == 100
    assert result["calendar_source"] == "repository_commits"
    assert result["calendar_limited"] is False
    assert len(result["repositories"]) == 3
    assert result["repositories"][0]["commits"] == [0] * 14
    assert all(request.method == "GET" for request in calls)


@pytest.mark.parametrize(
    "status,message,allowed",
    [
        (409, "Other conflict secret", True),
        (409, "Git Repository is empty.", False),
        (403, "secret", True),
    ],
)
def test_empty_repository_exception_does_not_hide_other_errors(
    monkeypatch, status, message, allowed
):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"message": message})
        )
    ) as client:
        monkeypatch.setattr(
            httpx, "stream", lambda *args, trust_env=False, **kwargs: client.stream(*args, **kwargs)
        )
        with pytest.raises(IntegrationError) as error:
            get_json(
                "https://api.github.com/repos/org/repo/commits", allow_empty_repository=allowed
            )
    assert "secret" not in str(error.value)


def test_organization_rejects_personal_repository(monkeypatch):
    def get(url, *args, **kwargs):
        if url.endswith("/user"):
            return {"login": "jack"}
        return [{"full_name": "jack/personal"}]

    monkeypatch.setattr(github, "get_json", get)
    with pytest.raises(IntegrationError, match="outside the chosen organisation"):
        github.snapshot({"api_url": "https://api.github.com", "organization": "TMPlant"}, "secret")


def test_organization_setting_is_optional_and_validated():
    config = copy.deepcopy(DEFAULTS)
    assert validate(config)["github"]["organization"] == ""
    config["github"]["organization"] = " TMPlant "
    assert validate(config)["github"]["organization"] == "TMPlant"
    config["github"]["organization"] = "https://github.com/TMPlant"
    with pytest.raises(ConfigurationError, match="organisation name"):
        validate(config)


def test_recent_refresh_preserves_calendar_and_reads_only_three_repos(monkeypatch):
    today = datetime.now(UTC).date().isoformat()
    calendar = {
        "login": "jack",
        "total": 400,
        "days": [{"date": today, "count": 4}],
        "calendar_source": "repository_commits",
        "calendar_limited": True,
        "calendar_repository_count": 101,
        "calendar_updated_at": 123,
    }
    calls = []

    def get(url, headers, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith("/orgs/TMPlant/repos"):
            assert params["per_page"] == 3
            assert params["page"] == 1
            return [{"full_name": f"TMPlant/repo{i}"} for i in range(3)]
        assert "/commits" in url
        since = datetime.fromisoformat(params["since"].replace("Z", "+00:00"))
        assert (datetime.now(UTC) - since).days == 13
        return [{"commit": {"author": {"date": today + "T00:00:00Z"}}}]

    def unexpected(*args, **kwargs):
        raise AssertionError("Recent refresh must not fetch the contribution calendar")

    monkeypatch.setattr(github, "get_json", get)
    monkeypatch.setattr(github, "post_json", unexpected)
    result = github.snapshot(
        {"api_url": "https://api.github.com", "organization": "TMPlant"},
        "secret",
        calendar=calendar,
    )
    for field in (
        "total",
        "days",
        "calendar_limited",
        "calendar_repository_count",
        "calendar_updated_at",
    ):
        assert result[field] == calendar[field]
    assert len(calls) == 4
    assert all(sum(repo["commits"]) == 1 for repo in result["repositories"])
