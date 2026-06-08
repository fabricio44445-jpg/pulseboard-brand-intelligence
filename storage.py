"""Optional persistent mention archive backed by Supabase REST."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests


REQUEST_TIMEOUT = 20


def configured(url: str | None, key: str | None) -> bool:
    return bool(url and key)


def _headers(key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    collected_at = row.get("collected_at", row["published_at"])
    return {
        "id": row["id"],
        "brand": row["brand"],
        "source": row["source"],
        "publisher": row["publisher"],
        "title": row["title"],
        "summary": row["summary"],
        "author": row["author"],
        "link": row["link"],
        "published_at": row["published_at"].astimezone(timezone.utc).isoformat(),
        "sentiment": row["sentiment"],
        "sentiment_score": row["sentiment_score"],
        "collected_at": collected_at.astimezone(timezone.utc).isoformat(),
    }


def _deserialize(row: dict[str, Any]) -> dict[str, Any]:
    parsed = dict(row)
    for field in ("published_at", "collected_at"):
        value = str(parsed[field])
        parsed[field] = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    parsed["sentiment_score"] = float(parsed["sentiment_score"])
    return parsed


def upsert_mentions(
    url: str,
    key: str,
    rows: list[dict[str, Any]],
) -> tuple[int, str | None]:
    if not rows:
        return 0, None

    endpoint = f"{url.rstrip('/')}/rest/v1/mentions?on_conflict=id"
    try:
        response = requests.post(
            endpoint,
            headers=_headers(
                key,
                prefer="resolution=merge-duplicates,return=minimal",
            ),
            json=[_serialize(row) for row in rows],
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return len(rows), None
    except requests.RequestException as exc:
        return 0, str(exc)


def load_mentions(
    url: str,
    key: str,
    brands: list[str],
    days: int = 30,
) -> tuple[list[dict[str, Any]], str | None]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    brand_values = ",".join(f'"{brand}"' for brand in brands)
    endpoint = f"{url.rstrip('/')}/rest/v1/mentions"
    try:
        response = requests.get(
            endpoint,
            headers=_headers(key),
            params={
                "select": "*",
                "brand": f"in.({brand_values})",
                "published_at": f"gte.{cutoff}",
                "order": "published_at.desc",
                "limit": "5000",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return [_deserialize(row) for row in response.json()], None
    except (requests.RequestException, ValueError, KeyError) as exc:
        return [], str(exc)


def prune_old_mentions(
    url: str,
    key: str,
    days: int = 30,
) -> str | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    endpoint = f"{url.rstrip('/')}/rest/v1/mentions"
    try:
        response = requests.delete(
            endpoint,
            headers=_headers(key, prefer="return=minimal"),
            params={"published_at": f"lt.{cutoff}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return None
    except requests.RequestException as exc:
        return str(exc)
