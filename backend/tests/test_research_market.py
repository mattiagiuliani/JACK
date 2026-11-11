import json
from unittest.mock import patch

import pytest

from app.agents.research import ResearchReport
from app.agents.research_market import (
    CommercialResearchProvider,
    MarketSource,
    PageConfig,
    PublicPageAdapter,
    configured_market_provider,
)
from app.agents.research_web import ProviderBusy, RetrievalError, SafeTransport
from app.config import Settings


def source(**changes: object) -> MarketSource:
    return MarketSource.model_validate(
        {
            "topic": "billing",
            "category": "public_price",
            "url": "https://example.com/pricing",
            "title": "Example pricing",
            "quote": "Plan costs USD 10 per month",
            "terms_url": "https://example.com/terms",
            "review_note": "Synthetic offline test only",
            "terms_reviewed": True,
            "privacy_reviewed": True,
            **changes,
        }
    )


class Fake:
    def __init__(
        self,
        body: bytes = b"<p>Plan costs USD 10 per month</p>",
        robots: bytes = b"User-agent: *\nAllow: /",
        busy: bool = False,
    ) -> None:
        self.body = body
        self.robots = robots
        self.busy = busy
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if self.busy:
            raise ProviderBusy("busy")
        return self.robots if url.endswith("robots.txt") else self.body


def adapter(item: MarketSource, fake: Fake) -> PublicPageAdapter:
    return PublicPageAdapter(
        PageConfig(page_url=item.url, user_agent="JACK test contact example.com"), fake
    )


def test_exact_quote_provenance_and_contract() -> None:
    item = source()
    fake = Fake()
    provider = CommercialResearchProvider(
        (item, item), (adapter(item, fake), adapter(item, fake))
    )
    report = provider.research("billing")
    assert len(report.evidence) == 1
    evidence = report.evidence[0]
    assert evidence.id.startswith("public_price:")
    assert evidence.statement == item.quote == evidence.excerpt
    assert evidence.source_uri == evidence.retrieval_uri == item.url
    assert evidence.retrieved_at is not None
    assert report.hypotheses == ()
    assert ResearchReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "robots",
    [
        b"User-agent: *\nDisallow: /",
        b"User-agent: *\nCrawl-delay: 5",
        b"User-agent: *\nRequest-rate: 1/10",
        b"User-agent: *\nDisallow: /*private$",
        b"\xff",
    ],
)
def test_robots_fail_closed(robots: bytes) -> None:
    item = source()
    fake = Fake(robots=robots)
    report = CommercialResearchProvider((item,), (adapter(item, fake),)).research(
        "billing"
    )
    assert not report.evidence
    assert len(fake.urls) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"changed",
        b"<script>Plan costs USD 10 per month</script>",
        b"\xff",
        b"x" * 1_000_001,
    ],
)
def test_missing_hidden_invalid_or_oversized_quote(body: bytes) -> None:
    item = source()
    report = CommercialResearchProvider((item,), (adapter(item, Fake(body)),)).research(
        "billing"
    )
    assert not report.evidence


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1/a",
        "https://localhost/a",
        "https://example.com:444/a",
        "https://a:b@example.com/a",
        "https://example.com/a?key=secret",
        "https://example.com/a#x",
        "https://[::1]/a",
    ],
)
def test_unsafe_sources_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        source(url=url)


def test_review_and_privacy_required() -> None:
    for changes in (
        {"terms_reviewed": False},
        {"privacy_reviewed": False},
        {"quote": "Email person@example.com"},
    ):
        with pytest.raises(ValueError):
            source(**changes)


def test_no_topic_match_no_network_and_backpressure_stops() -> None:
    item = source()
    fake = Fake(busy=True)
    provider = CommercialResearchProvider(
        (item, item), (adapter(item, fake), adapter(item, fake))
    )
    assert not provider.research("other").evidence
    assert fake.urls == []
    assert not provider.research("billing").evidence
    assert len(fake.urls) == 1


def test_factory_budget_and_shared_rate_limiter() -> None:
    items = [
        source().model_dump(),
        source(url="https://example.com/product").model_dump(),
    ]
    settings = Settings(
        market_sources_json=json.dumps(items),
        research_user_agent="JACK contact example.com",
    )
    provider = configured_market_provider(settings)
    assert provider.adapters[0].transport is provider.adapters[1].transport
    assert provider.adapters[0].config.retries == 0
    with pytest.raises(ValueError):
        configured_market_provider(
            settings.model_copy(update={"research_max_results": 1})
        )
    assert Settings().research_provider == "controlled"


def test_transport_blocks_redirect_destinations_and_private_dns() -> None:
    config = PageConfig(page_url=source().url, user_agent="JACK contact example.com")
    transport = SafeTransport(config, frozenset((source().url,)))
    with patch("socket.getaddrinfo") as dns:
        with pytest.raises(RetrievalError):
            transport.get("https://example.com/other")
        dns.assert_not_called()
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]),
        patch("socket.create_connection") as connect,
    ):
        with pytest.raises(RetrievalError, match="Non-public"):
            transport.get(source().url)
        connect.assert_not_called()


@pytest.mark.parametrize(
    "category", ["customer_problem", "competitor", "public_price", "demand_signal"]
)
def test_each_category_remains_an_observation(category: str) -> None:
    item = source(category=category)
    report = CommercialResearchProvider((item,), (adapter(item, Fake()),)).research(
        "billing"
    )
    assert report.evidence[0].id.startswith(category + ":")
    assert not report.hypotheses
    assert any(item.terms_url in limitation for limitation in report.limitations)


def test_configured_agent_factory_keeps_existing_boundary() -> None:
    from app.agents.research_web import configured_research_provider

    settings = Settings(research_provider="commercial", market_sources_json="[]")
    with patch("app.config.get_settings", return_value=settings):
        provider = configured_research_provider()
    assert isinstance(provider, CommercialResearchProvider)
    report = provider.research("billing")
    assert not report.evidence
    assert (
        len([line for line in report.limitations if line.startswith("No usable")]) == 4
    )
