"""Scheduled collector entrypoint for GitHub Actions."""

from __future__ import annotations

import os
import sys

from archive import load_archive, save_archive
from collectors import brand_is_relevant, collect_mentions, sentiment_for


def main() -> int:
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

    existing = load_archive(days=30)
    reclassified = []
    for row in existing + rows:
        searchable = f"{row['title']} {row['summary']}"
        if not brand_is_relevant(row["brand"], searchable):
            continue
        sentiment, score, confidence, reason = sentiment_for(
            row["title"],
            row["summary"],
        )
        row.update(
            {
                "sentiment": sentiment,
                "sentiment_score": score,
                "sentiment_confidence": confidence,
                "sentiment_reason": reason,
            }
        )
        reclassified.append(row)

    stored = save_archive(reclassified, days=30)
    print(f"Archive now contains {stored} mentions for the last 30 days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
