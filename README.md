# Pulseboard

Pulseboard is a live brand-intelligence dashboard built for Streamlit. It
collects public mentions, normalizes them, estimates sentiment, compares brands,
and links every conclusion back to its source.

## Live sources

- Google News RSS
- Reddit search RSS
- WordPress tag feeds
- Selected technology publication RSS feeds
- YouTube Data API v3 when a key is configured

Source failures appear in the **Source health** tab instead of being silently
ignored.

## Run locally

```bash
cd brand-intelligence-hub
python3 -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`.

### Enable YouTube

Create `.streamlit/secrets.toml`:

```toml
YOUTUBE_API_KEY = "your-key"
```

The key requires **YouTube Data API v3** access in Google Cloud Console. Do not
commit the real secrets file.

## Deploy from GitHub to Streamlit Community Cloud

1. Create a GitHub repository and push this folder.
2. Sign in at <https://share.streamlit.io>.
3. Select **Create app** and choose the GitHub repository.
4. Set the entrypoint to `streamlit_app.py`.
5. Open **App settings → Secrets** and add:

   ```toml
   YOUTUBE_API_KEY = "your-key"
   ```

6. Deploy.

`requirements.txt` and `.streamlit/config.toml` are already configured.
The dependency set supports Streamlit Community Cloud's Python 3.14 runtime.

## Storage note

Streamlit Community Cloud does not provide durable local application storage.
This version fetches live data and uses a 15-minute cache. If historical data
must survive app restarts, connect PostgreSQL, Supabase, or another external
database rather than relying on a local CSV or SQLite file.

## Responsible collection

Pulseboard uses public feeds and official APIs. Availability, indexing, and
rate limits vary by source. Review each platform's terms before expanding the
collector or storing full content.
