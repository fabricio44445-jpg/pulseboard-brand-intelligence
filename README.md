# ReoNeura

ReoNeura is a live brand-intelligence workspace built with Streamlit. It
collects public mentions, estimates sentiment, compares brands, and preserves a
rolling 30-day archive.

## Live sources

- Google News RSS
- Reddit search RSS
- WordPress tag feeds
- Selected technology publication RSS feeds
- YouTube Data API v3 when a key is configured

## 30-day retention

The repository contains a scheduled GitHub Actions workflow that:

1. Collects mentions every two hours.
2. Merges them into `data/mentions.json`.
3. Deduplicates records using stable mention IDs.
4. Removes records older than 30 days.
5. Commits the updated archive to the repository.

No external database is required. Public mention metadata is stored in the
public repository.

To start an immediate collection, open the GitHub repository and select:

**Actions → Collect brand mentions → Run workflow**

The workflow tracks `Reolink,Arlo,Eufy` by default. Set the optional repository
variable `TRACKED_BRANDS` to a comma-separated list to change the scheduled
brands.

## Run locally

```bash
python3 -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`.

## Enable YouTube

Create `.streamlit/secrets.toml` locally or add this value to Streamlit
Community Cloud secrets:

```toml
YOUTUBE_API_KEY = "your-key"
```

Add the same `YOUTUBE_API_KEY` as a GitHub Actions repository secret so
scheduled collection includes YouTube. Never commit the real key.

## Deploy

Deploy from:

- Repository: `fabricio44445-jpg/pulseboard-brand-intelligence`
- Branch: `main`
- Entrypoint: `streamlit_app.py`

The dependency set supports Streamlit Community Cloud's Python 3.14 runtime.

## Notes

Sentiment is automated and directional. Open the supporting source before
making a response or reputation decision. Feed availability and indexing vary
by platform.
