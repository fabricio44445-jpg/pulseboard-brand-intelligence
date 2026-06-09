"""Live data collectors for ReoNeura.

The collectors intentionally return plain dictionaries so Streamlit can cache
their output without custom serializers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
import re
from typing import Any, Iterable
from urllib.parse import quote, urlparse, urlunparse

import feedparser
import requests
from textblob import TextBlob


USER_AGENT = (
    "Mozilla/5.0 (compatible; ReoNeura/1.0; "
    "+https://github.com/fabricio44445-jpg/pulseboard-brand-intelligence)"
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

POSITIVE_PHRASES = {
    "best ever": 2.5,
    "best-ever": 2.5,
    "bargain price": 2.2,
    "great value": 2.2,
    "works well": 2.0,
    "working perfectly": 2.5,
    "finally got": 1.5,
    "highly recommend": 2.5,
    "no subscription": 1.8,
    "without a subscription": 1.8,
    "local storage": 0.8,
    "privacy focus": 1.4,
    "strong privacy": 1.5,
    "market leadership": 1.5,
    "half off": 2.0,
    "price drop": 1.5,
    "save $": 1.8,
    "$ off": 1.8,
    "solved": 2.0,
    "fixed": 2.0,
    "improves": 1.4,
    "improved": 1.4,
    "upgrade": 0.8,
    "pro-level": 1.5,
    "outperformance": 1.5,
}

NEGATIVE_PHRASES = {
    "does not work": -2.8,
    "doesn't work": -2.8,
    "not working": -2.8,
    "will not": -2.0,
    "won't": -2.0,
    "cannot connect": -2.5,
    "can't connect": -2.5,
    "cannot set up": -2.5,
    "can't set up": -2.5,
    "unable to": -2.2,
    "keeps failing": -2.8,
    "stopped working": -3.0,
    "too expensive": -1.8,
    "hate": -2.0,
    "poor quality": -2.5,
    "unusable": -2.8,
    "overheat": -2.2,
    "delayed alert": -2.0,
    "false alert": -1.8,
    "subscription price": -1.2,
    "price increase": -1.6,
    "trade down": -1.0,
    "stock is down": -1.8,
    "never comment": -1.6,
    "loud popping": -1.8,
}

POSITIVE_WORDS = {
    "amazing", "bargain", "best", "better", "excellent", "fast", "favorite",
    "great", "impressive", "love", "perfect", "reliable", "recommend",
    "smooth", "strong", "success", "successful", "useful", "value",
}

NEGATIVE_WORDS = {
    "bad", "broken", "bug", "bugs", "complaint", "difficult", "disappointed",
    "debacle", "disconnect", "error", "expensive", "fail", "failed", "fails",
    "failing", "failure",
    "frustrating", "hate", "issue", "issues", "overheating", "poor", "problem",
    "problems", "slow", "stopped", "unreliable", "unusable", "worse", "worst",
}

SOLUTION_PHRASES = {
    "end security blind spots",
    "eliminate blind spots",
    "prevent break-ins",
    "fix the issue",
    "fixes the issue",
    "solve the problem",
    "solves the problem",
}

ARLO_DOMAIN_TERMS = {
    "camera", "cameras", "security", "doorbell", "wifi", "wi-fi",
    "subscription", "motion", "alert", "base station",
    "stock", "shares", "earnings", "nasdaq", "nyse", "company", "technologies",
    "privacy", "service plan", "outdoor", "indoor",
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


def mention_id(brand: str, link: str, title: str) -> str:
    """Create a stable identifier used by persistent archives."""
    raw = f"{brand.casefold()}|{canonical_url(link)}|{title.casefold()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def brand_is_relevant(brand: str, text: str) -> bool:
    """Require the complete brand phrase rather than loose substring matches."""
    phrase = re.escape(brand.strip())
    if not re.search(rf"(?<!\w){phrase}(?!\w)", text, flags=re.IGNORECASE):
        return False
    if brand.casefold() == "arlo":
        normalized = text.casefold()
        return any(term in normalized for term in ARLO_DOMAIN_TERMS)
    return True


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


def _signal_score(text: str) -> tuple[float, list[str], list[str]]:
    normalized = text.casefold().replace("’", "'")
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    score = 0.0

    for phrase, weight in POSITIVE_PHRASES.items():
        if phrase in normalized:
            score += weight
            positive_hits.append(phrase)
    for phrase, weight in NEGATIVE_PHRASES.items():
        if phrase in normalized:
            score += weight
            negative_hits.append(phrase)
    for phrase in SOLUTION_PHRASES:
        if phrase in normalized:
            score += 2.2
            positive_hits.append(phrase)
    if re.search(r"\$\s?\d+(?:\.\d+)?\s+off\b", normalized):
        score += 1.8
        positive_hits.append("cash discount")
    if re.search(r"\b\d{1,2}%\s+off\b", normalized):
        score += 1.8
        positive_hits.append("percentage discount")

    words = re.findall(r"[a-z][a-z'-]+", normalized)
    for index, word in enumerate(words):
        previous = words[max(0, index - 2) : index]
        negated = any(token in {"not", "never", "no", "hardly"} for token in previous)
        if word in POSITIVE_WORDS:
            score += -1.0 if negated else 1.0
            (negative_hits if negated else positive_hits).append(
                f"{'not ' if negated else ''}{word}"
            )
        elif word in NEGATIVE_WORDS:
            score += 1.0 if negated else -1.0
            (positive_hits if negated else negative_hits).append(
                f"{'not ' if negated else ''}{word}"
            )
    return score, positive_hits, negative_hits


def sentiment_for(
    title: str,
    summary: str = "",
) -> tuple[str, float, str, str]:
    """Return brand sentiment, normalized score, confidence, and explanation."""
    normalized_title = title.casefold().replace("’", "'")
    title_score, title_positive, title_negative = _signal_score(title)
    summary_score, summary_positive, summary_negative = _signal_score(summary[:700])

    explicit_score = title_score + (summary_score * 0.35)
    positive_hits = title_positive + summary_positive[:3]
    negative_hits = title_negative + summary_negative[:3]
    signal_count = len(positive_hits) + len(negative_hits)
    strong_positive = (
        any(phrase in normalized_title for phrase in POSITIVE_PHRASES)
        or any(phrase in normalized_title for phrase in SOLUTION_PHRASES)
        or bool(re.search(r"\$\s?\d+(?:\.\d+)?\s+off\b", normalized_title))
        or bool(re.search(r"\b\d{1,2}%\s+off\b", normalized_title))
    )

    if signal_count == 0:
        return "Neutral", 0.0, "Low", "No clear praise or complaint language"

    # TextBlob is retained only as a small tie-breaker, not the main classifier.
    blob_score = float(TextBlob(f"{title}. {summary[:350]}").sentiment.polarity)
    combined = explicit_score + (blob_score * 0.2)
    normalized_score = round(max(-1.0, min(1.0, combined / 3.0)), 3)

    if (
        combined > 0
        and not strong_positive
        and (
            "?" in title
            or normalized_title.startswith("best ")
            or normalized_title.startswith("looking for ")
            or "recommendations" in normalized_title
        )
    ):
        return "Neutral", normalized_score, "Low", "Question or recommendation request"
    if positive_hits and negative_hits and abs(combined) < 1.4:
        return "Neutral", normalized_score, "Medium", "Mixed positive and negative signals"
    if combined >= 0.75:
        reason = f"Positive signal: {positive_hits[0]}"
        confidence = "High" if combined >= 2.0 or signal_count >= 3 else "Medium"
        return "Positive", normalized_score, confidence, reason
    if combined <= -0.75:
        reason = f"Negative signal: {negative_hits[0]}"
        confidence = "High" if combined <= -2.0 or signal_count >= 3 else "Medium"
        return "Negative", normalized_score, confidence, reason
    return "Neutral", normalized_score, "Low", "Weak or ambiguous opinion signals"


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
    sentiment, score, confidence, reason = sentiment_for(title, summary)
    collected_at = datetime.now(timezone.utc)
    return {
        "id": mention_id(brand, link, title),
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
        "sentiment_confidence": confidence,
        "sentiment_reason": reason,
        "collected_at": collected_at,
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
        for entry in parsed.entries[:100]:
            searchable = clean_text(
                f"{entry.get('title', '')} {entry.get('summary', '')}"
            )
            if require_match and not brand_is_relevant(brand, searchable):
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
        require_match=True,
    )


def fetch_reddit(brand: str) -> tuple[list[dict[str, Any]], str | None]:
    query = quote(brand)
    return fetch_feed(
        f"https://www.reddit.com/search.rss?q={query}&sort=new&t=month",
        brand=brand,
        source="Reddit",
        publisher="Reddit",
        require_match=True,
    )


def fetch_wordpress(brand: str) -> tuple[list[dict[str, Any]], str | None]:
    slug = re.sub(r"[^a-z0-9]+", "-", brand.casefold()).strip("-")
    return fetch_feed(
        f"https://wordpress.com/tag/{slug}/feed/",
        brand=brand,
        source="Blogs",
        publisher="WordPress",
        require_match=True,
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
            sentiment, score, confidence, reason = sentiment_for(title, summary)
            published = str(snippet.get("publishedAt") or "")
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published_at = datetime.now(timezone.utc)
            mentions.append(
                {
                    "id": mention_id(
                        brand,
                        f"https://www.youtube.com/watch?v={video_id}",
                        title,
                    ),
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
                    "sentiment_confidence": confidence,
                    "sentiment_reason": reason,
                    "collected_at": datetime.now(timezone.utc),
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
