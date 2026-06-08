"""Scheduled collector entrypoint for GitHub Actions."""

from __future__ import annotations

import os
import sys

from collectors import collect_mentions
from storage import prune_old_mentions, upsert_mentions


def main() -> int:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        return 2

    brand_config = os.getenv("TRACKED_BRANDS") or "Reolink,Arlo,Eufy"
    brands = [
        brand.strip()
        for brand in brand_config.split(",")
        if brand.strip()
    ]
    sources = ["Google News", "Reddit", "Blogs"]
    youtube_key = os.getenv("YOUTUBE_API_KEY")
    if youtube_key:
        sources.append("YouTube")

    rows, statuses = collect_mentions(brands, sources, youtube_key)
    for status in statuses:
        state = "ok" if status["ok"] else "error"
        print(
            f"[{state}] {status['brand']} / {status['source']}: "
            f"{status['count']} ({status['message']})"
        )

    stored, error = upsert_mentions(supabase_url, supabase_key, rows)
    if error:
        print(f"Archive write failed: {error}")
        return 1

    prune_error = prune_old_mentions(supabase_url, supabase_key, days=30)
    if prune_error:
        print(f"Archive cleanup failed: {prune_error}")
        return 1

    print(f"Stored or refreshed {stored} mentions for {len(brands)} brands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
