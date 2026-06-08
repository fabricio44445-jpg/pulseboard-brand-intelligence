"""Live data collectors for Pulseboard.

The collectors intentionally return plain dictionaries so Streamlit can cache
their output without custom serializers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from typing import Any, Iterable
from urllib.parse import quote, urlparse, urlunparse

import feedparser
import requests
from textblob import TextBlob


USER_AGENT = (
    "Mozilla/5.0 (compatible; Pulseboard/1.0; "
    "+https://github.com/pulseboard-app)"
)
REQUEST_TIMEOUT = 15

SOURCE_ICONS = {
    "Google News": "📰",
    "Reddit": "🟠",
    "YouTube": "▶️",
    "Blogs": "✍️",
}

PUBLICATION_FEEDS = {
    "ComputerBase": "https://www.computerbase.de/rss/news.xml",
    "Les Numériques": "https://www.lesnumeriques.com/rss.xml",
}


def clean_text(value: Any) -> str:
    """Strip markup and normalize whitespace from external text."""
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(value: str) -> str:
    """Remove fragments and common tracking parameters for deduplication."""
    try:
        parsed = urlparse(value)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
    except ValueError:
        return value


def parse_datetime(entry: dict[str, Any]) -> datetime:
    """Return a timezone-aware UTC datetime for a feed entry."""
    struct_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct_time:
        return datetime(*struct_time[:6], tzinfo=timezone.utc)

    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc)


def sentiment_for(text: str) -> tuple[str, float]:
    """Classify title/summary sentiment using TextBlob polarity."""
    score = round(float(TextBlob(text).sentiment.polarity), 3)
    if score > 0.15:
        return "Positive", score
    if score < -0.15:
        return "Negative", score
    return "Neutral", score


def entry_to_mention(
    entry: dict[str, Any],
    *,
    brand: str,
    source: str,
    publisher: str,
) -> dict[str, Any] | None:
    title = clean_text(entry.get("title"))
    link = canonical_url(str(entry.get("link") or ""))
    if not title or not link:
        return None

    summary = clean_text(entry.get("summary") or entry.get("description"))
    sentiment, score = sentiment_for(f"{title}. {summary[:500]}")
    return {
        "brand": brand,
        "source": source,
        "publisher": publisher,
        "title": title,
        "summary": summary[:700],
        "author": clean_text(entry.get("author") or publisher),
        "link": link,
        "published_at": parse_datetime(entry),
        "sentiment": sentiment,
        "sentiment_score": score,
    }


def fetch_feed(
    url: str,
    *,
    brand: str,
    source: str,
    publisher: str,
    require_match: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(clean_text(parsed.bozo_exception))

        mentions: list[dict[str, Any]] = []
        needle = brand.casefold()
        for entry in parsed.entries[:100]:
            searchable = clean_text(
                f"{entry.get('title', '')} {entry.get('summary', '')}"
            ).casefold()
            if require_match and needle not in searchable:
                continue
            mention = entry_to_mention(
                entry,
                brand=brand,
                source=source,
                publisher=publisher,
            )
            if mention:
                mentions.append(mention)
        return mentions, None
    except (requests.RequestException, ValueError) as exc:
        return [], clean_text(exc)


def fetch_google_news(brand: str) -> tuple[list[dict[str, Any]], str | None]:
    query = quote(f'"{brand}" when:30d')
    return fetch_feed(
        f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
        brand=brand,
        source="Google News",
        publisher="Google News",
    )


def fetch_reddit(brand: str) -> tuple[list[dict[str, Any]], str | None]:
    query = quote(brand)
    return fetch_feed(
        f"https://www.reddit.com/search.rss?q={query}&sort=new&t=month",
        brand=brand,
        source="Reddit",
        publisher="Reddit",
    )


def fetch_wordpress(brand: str) -> tuple[list[dict[str, Any]], str | None]:
    slug = re.sub(r"[^a-z0-9]+", "-", brand.casefold()).strip("-")
    return fetch_feed(
        f"https://wordpress.com/tag/{slug}/feed/",
        brand=brand,
        source="Blogs",
        publisher="WordPress",
    )


def fetch_publication_feeds(brand: str) -> tuple[list[dict[str, Any]], list[str]]:
    mentions: list[dict[str, Any]] = []
    errors: list[str] = []
    for publisher, url in PUBLICATION_FEEDS.items():
        rows, error = fetch_feed(
            url,
            brand=brand,
            source="Blogs",
            publisher=publisher,
            require_match=True,
        )
        mentions.extend(rows)
        if error:
            errors.append(f"{publisher}: {error}")
    return mentions, errors


def fetch_youtube(
    brand: str,
    api_key: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if not api_key:
        return [], "YouTube API key not configured"

    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": api_key,
                "q": brand,
                "part": "snippet",
                "type": "video",
                "order": "date",
                "maxResults": 50,
                "publishedAfter": (
                    datetime.now(timezone.utc) - timedelta(days=30)
                ).isoformat().replace("+00:00", "Z"),
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        mentions: list[dict[str, Any]] = []
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if not video_id:
                continue
            title = clean_text(snippet.get("title"))
            summary = clean_text(snippet.get("description"))
            sentiment, score = sentiment_for(f"{title}. {summary}")
            published = str(snippet.get("publishedAt") or "")
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published_at = datetime.now(timezone.utc)
            mentions.append(
                {
                    "brand": brand,
                    "source": "YouTube",
                    "publisher": clean_text(snippet.get("channelTitle") or "YouTube"),
                    "title": title,
                    "summary": summary[:700],
                    "author": clean_text(snippet.get("channelTitle") or "Creator"),
                    "link": f"https://www.youtube.com/watch?v={video_id}",
                    "published_at": published_at.astimezone(timezone.utc),
                    "sentiment": sentiment,
                    "sentiment_score": score,
                }
            )
        return mentions, None
    except (requests.RequestException, ValueError) as exc:
        message = clean_text(exc)
        try:
            detail = response.json().get("error", {}).get("message")
            if detail:
                message = clean_text(detail)
        except (ValueError, UnboundLocalError):
            pass
        return [], message


def deduplicate(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["link"] or f"{row['source']}:{row['title'].casefold()}"
        existing = unique.get(key)
        if existing is None or row["published_at"] > existing["published_at"]:
            unique[key] = row
    return sorted(unique.values(), key=lambda row: row["published_at"], reverse=True)


def collect_mentions(
    brands: list[str],
    sources: list[str],
    youtube_api_key: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect selected sources and return mentions plus per-source status."""
    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    for brand in brands:
        collectors = []
        if "Google News" in sources:
            collectors.append(("Google News", lambda: fetch_google_news(brand)))
        if "Reddit" in sources:
            collectors.append(("Reddit", lambda: fetch_reddit(brand)))
        if "Blogs" in sources:
            collectors.append(("WordPress", lambda: fetch_wordpress(brand)))
        if "YouTube" in sources:
            collectors.append(
                ("YouTube", lambda: fetch_youtube(brand, youtube_api_key))
            )

        for source_name, collector in collectors:
            collected, error = collector()
            rows.extend(collected)
            statuses.append(
                {
                    "brand": brand,
                    "source": source_name,
                    "count": len(collected),
                    "ok": error is None,
                    "message": error or "Connected",
                }
            )

        if "Blogs" in sources:
            collected, errors = fetch_publication_feeds(brand)
            rows.extend(collected)
            statuses.append(
                {
                    "brand": brand,
                    "source": "Publication feeds",
                    "count": len(collected),
                    "ok": not errors,
                    "message": "; ".join(errors) if errors else "Connected",
                }
            )

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = (row for row in rows if row["published_at"] >= cutoff)
    return deduplicate(recent), statuses
