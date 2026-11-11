import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.research_crossref import CrossrefResearchProvider, publication_date
from app.agents.research_web import RetrievalError, SafeTransport, WebConfig


def config() -> WebConfig:
    return WebConfig(
        source="crossref",
        user_agent="JACK/0.1 (https://github.com/mattiagiuliani/JACK)",
    )


class FakeCrossref:
    def __init__(self, abstract: str = "<jats:p>Untrusted assertion.</jats:p>") -> None:
        self.urls: list[str] = []
        self.abstract = abstract

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if url.endswith("robots.txt"):
            return b"User-agent: *\nAllow: /"
        if "/works?" in url:
            message = {"items": [{"DOI": "10.1234/TEST"}, {"DOI": "10.1234/test"}]}
        else:
            message = {
                "DOI": "10.1234/test",
                "title": ["Title"],
                "abstract": self.abstract,
                "published": {"date-parts": [[2024]]},
            }
        return json.dumps({"status": "ok", "message": message}).encode()


def test_search_content_dedup_dates() -> None:
    transport = FakeCrossref()
    report = CrossrefResearchProvider(config(), transport).research("market")
    assert len(report.evidence) == 1
    evidence = report.evidence[0]
    assert evidence.excerpt == evidence.statement == "Untrusted assertion."
    assert evidence.source_publication_date == "2024"
    assert evidence.source_modified_at is None
    assert evidence.source_uri == "https://doi.org/10.1234/TEST"
    assert evidence.retrieved_at is not None
    assert len(transport.urls) == 3
    assert report.hypotheses == ()


def test_title_fallback_is_explicit() -> None:
    report = CrossrefResearchProvider(config(), FakeCrossref("")).research("market")
    assert report.evidence[0].excerpt == "Title"
    assert any("title only" in item for item in report.limitations)


@pytest.mark.parametrize(
    "parts,expected",
    [
        ([2024], "2024"),
        ([2024, 2], "2024-02"),
        ([2024, 2, 29], "2024-02-29"),
        ([], None),
    ],
)
def test_date_precision(parts: list[int], expected: str | None) -> None:
    assert publication_date({"published": {"date-parts": [parts]}}) == expected


def test_robots_404_allowed_without_bypassing_403() -> None:
    connection = MagicMock()
    response = connection.getresponse.return_value
    with (
        patch(
            "socket.getaddrinfo", return_value=[(2, 1, 6, "", ("208.80.154.224", 443))]
        ),
        patch("socket.create_connection"),
        patch("ssl.create_default_context"),
        patch("http.client.HTTPSConnection", return_value=connection),
        patch("time.sleep"),
    ):
        response.status = 404
        assert b"Allow" in SafeTransport(config()).get(
            "https://api.crossref.org/robots.txt"
        )
        response.status = 403
        with pytest.raises(RetrievalError):
            SafeTransport(config()).get("https://api.crossref.org/robots.txt")


def test_factory_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.research_web import configured_research_provider
    from app.config import get_settings

    monkeypatch.setenv("RESEARCH_PROVIDER", "crossref")
    monkeypatch.setenv("RESEARCH_USER_AGENT", config().user_agent)
    get_settings.cache_clear()
    try:
        assert isinstance(configured_research_provider(), CrossrefResearchProvider)
    finally:
        get_settings.cache_clear()
