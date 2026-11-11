"""Curated public-page observations; remote text never becomes instructions."""

import hashlib
import ipaddress
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pydantic import Field, TypeAdapter, model_validator

from app.agents.research import (
    Evidence,
    ResearchModel,
    ResearchProvider,
    ResearchReport,
    Text,
)
from app.agents.research_web import (
    ProviderBusy,
    RetrievalError,
    SafeTransport,
    Transport,
    WebConfig,
)
from app.config import Settings


def public_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.port not in (None, 443)
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", parts.hostname)
    ):
        raise ValueError("Only public HTTPS URLs without credentials/query/fragment")
    host = parts.hostname
    if host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
        raise ValueError("Local hosts forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Non-public address forbidden")
    return value


class MarketSource(ResearchModel):
    topic: Text
    category: Literal["customer_problem", "competitor", "public_price", "demand_signal"]
    url: Text
    title: Text
    quote: str = Field(min_length=1, max_length=160)
    terms_url: Text
    review_note: Text
    terms_reviewed: Literal[True]
    privacy_reviewed: Literal[True]

    @model_validator(mode="after")
    def validate_policy(self) -> "MarketSource":
        public_url(self.url)
        public_url(self.terms_url)
        if re.search(
            r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\b\d[\d ()+-]{7,}\d\b", self.quote
        ):
            raise ValueError("Potential personal contact details in quote")
        if not self.quote.strip():
            raise ValueError("Empty quote")
        return self


class PageConfig(WebConfig):
    page_url: str

    @property
    def origin(self) -> str:
        public_url(self.page_url)
        parts = urlsplit(self.page_url)
        return f"https://{parts.netloc}"


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


class PublicPageAdapter:
    """Two bounded GETs, no link following, login, discovery or paid services."""

    def __init__(self, config: PageConfig, transport: Transport | None = None) -> None:
        self.config = config
        self.transport = transport or SafeTransport(
            config, frozenset((config.origin + "/robots.txt", config.page_url))
        )

    def collect(self, source: MarketSource) -> Evidence:
        if source.url != self.config.page_url:
            raise ValueError("Adapter URL mismatch")
        robots = RobotFileParser()
        robots_raw = self.transport.get(self.config.origin + "/robots.txt")
        if len(robots_raw) > self.config.max_bytes:
            raise RetrievalError("Robots response size limit exceeded")
        robots_text = robots_raw.decode("utf-8")
        # urllib.robotparser lacks REP wildcard/end-anchor support. Fail closed
        # instead of silently treating a restrictive unsupported rule as allowed.
        for line in robots_text.splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() in ("allow", "disallow") and any(
                token in value.split("#")[0] for token in ("*", "$")
            ):
                raise RetrievalError("Unsupported robots rule; collection blocked")
        robots.parse(robots_text.splitlines())
        agent = self.config.user_agent
        delay = robots.crawl_delay(agent)
        rate = robots.request_rate(agent)
        if (
            not robots.can_fetch(agent, source.url)
            or (delay and float(delay) > self.config.interval)
            or (
                rate
                and float(rate.seconds) / float(rate.requests) > self.config.interval
            )
        ):
            raise RetrievalError("Robots policy blocks collection")
        raw = self.transport.get(source.url)
        if len(raw) > self.config.max_bytes:
            raise RetrievalError("Response size limit exceeded")
        parser = VisibleText()
        parser.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(parser.parts).split())
        if source.quote not in text:
            raise RetrievalError("Reviewed quote absent from retrieved page")
        digest = hashlib.sha256((source.url + source.quote).encode()).hexdigest()[:16]
        return Evidence(
            id=f"{source.category}:{digest}",
            statement=source.quote,
            excerpt=source.quote,
            source_uri=source.url,
            retrieval_uri=source.url,
            source_title=source.title,
            kind="external",
            retrieved_at=datetime.now(UTC),
        )


class CommercialResearchProvider(ResearchProvider):
    def __init__(
        self, sources: tuple[MarketSource, ...], adapters: tuple[PublicPageAdapter, ...]
    ) -> None:
        if len(sources) > 5 or len(sources) != len(adapters):
            raise ValueError("At most five sources with one adapter each")
        self.sources = sources
        self.adapters = adapters

    def research(self, topic: str) -> ResearchReport:
        if not topic.strip() or len(topic) > 500:
            raise ValueError("Research topic must contain 1 to 500 characters")
        evidence: dict[str, Evidence] = {}
        limitations = [
            "Curated public pages only; category is reviewer-assigned, not a "
            "verified conclusion.",
            "Quotes are untrusted source assertions, never instructions. No "
            "hypotheses generated.",
            "Customer problems and demand signals are anecdotal; no prevalence, "
            "willingness to pay or market size inferred.",
            "Public prices may omit taxes, region, billing period and conditions; "
            "verify at source before use.",
            "Terms/privacy review is an operator attestation, not automated legal "
            "verification. Retain source attribution; limited excerpts only.",
        ]
        for index, (source, adapter) in enumerate(
            zip(self.sources, self.adapters, strict=True)
        ):
            if source.topic != topic:
                continue
            try:
                item = adapter.collect(source)
                evidence[item.id] = item
                limitations.append(
                    f"Review provenance for {item.id}: terms {source.terms_url}; "
                    "terms/privacy attested in source configuration."
                )
            except ProviderBusy:
                limitations.append(
                    "Provider backpressure: remaining collection stopped."
                )
                break
            except (RetrievalError, UnicodeError, ValueError):
                limitations.append(
                    f"Source {index + 1}: blocked, unavailable or quote changed; "
                    "no observation emitted."
                )
        categories = {item.id.split(":")[0] for item in evidence.values()}
        for category in (
            "customer_problem",
            "competitor",
            "public_price",
            "demand_signal",
        ):
            if category not in categories:
                limitations.append(
                    f"No usable {category} observation; absence is not market evidence."
                )
        return ResearchReport(
            topic=topic,
            provider="commercial-public-pages-v1",
            mode="external",
            evidence=tuple(evidence.values()),
            limitations=tuple(limitations),
        )


def configured_market_provider(settings: Settings) -> CommercialResearchProvider:
    sources = TypeAdapter(tuple[MarketSource, ...]).validate_json(
        settings.market_sources_json
    )
    if len(sources) > settings.research_max_results:
        raise ValueError("Source count exceeds configured result budget")
    transports: dict[str, SafeTransport] = {}
    adapters: list[PublicPageAdapter] = []
    for source in sources:
        config = PageConfig(
            page_url=source.url,
            user_agent=settings.research_user_agent,
            timeout=settings.research_timeout,
            interval=settings.research_interval,
            retries=0,
            max_bytes=64_000,
        )
        if config.origin not in transports:
            urls = frozenset(
                item.url
                for item in sources
                if urlsplit(item.url).netloc == urlsplit(source.url).netloc
            ) | frozenset((config.origin + "/robots.txt",))
            transports[config.origin] = SafeTransport(config, urls)
        adapters.append(PublicPageAdapter(config, transports[config.origin]))
    return CommercialResearchProvider(sources, tuple(adapters))
