"""Pulseboard: live brand intelligence dashboard for Streamlit."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import html
import os
import re

import altair as alt
import pandas as pd
import streamlit as st

from collectors import SOURCE_ICONS, collect_mentions


st.set_page_config(
    page_title="Pulseboard | Brand Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

SOURCES = ["Google News", "Reddit", "YouTube", "Blogs"]
DEFAULT_BRANDS = ["Reolink", "Arlo", "Eufy"]
STOP_WORDS = {
    "about", "after", "again", "against", "also", "been", "before", "being",
    "camera", "cameras", "could", "from", "have", "into", "more", "most",
    "news", "over", "review", "security", "smart", "than", "that", "their",
    "there", "these", "they", "this", "video", "what", "when", "where",
    "which", "while", "with", "would", "your",
}


def secret(name: str) -> str | None:
    try:
        return str(st.secrets[name])
    except (KeyError, FileNotFoundError):
        return os.getenv(name)


@st.cache_data(ttl=900, show_spinner=False)
def load_mentions(
    brands: tuple[str, ...],
    sources: tuple[str, ...],
    youtube_api_key: str | None,
) -> tuple[list[dict], list[dict]]:
    return collect_mentions(list(brands), list(sources), youtube_api_key)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#14201f; --muted:#6d7b79; --line:#e2e8e7;
          --primary:#136f63; --primary-dark:#0b5148; --soft:#e7f3f0;
          --positive:#198754; --negative:#d55050; --warning:#d58a27;
        }
        .stApp { background:#f5f7f9; color:var(--ink); }
        [data-testid="stSidebar"] { background:#102c29; }
        [data-testid="stSidebar"] * { color:#e5f0ee; }
        [data-testid="stSidebar"] .stButton button {
          background:#c9f26b; color:#163934; border:0; font-weight:800;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
          color:#a9bfbc; font-size:.77rem; font-weight:700;
        }
        .block-container { max-width:1500px; padding-top:2.3rem; }
        h1,h2,h3 { letter-spacing:-.025em; }
        h1 { font-size:2rem !important; }
        .eyebrow {
          color:var(--primary); font-size:.7rem; font-weight:800;
          letter-spacing:.13em; text-transform:uppercase; margin-bottom:.35rem;
        }
        .subtle { color:var(--muted); font-size:.9rem; margin-top:-.7rem; }
        .metric-card {
          background:white; border:1px solid var(--line); border-radius:14px;
          padding:1.15rem 1.2rem; min-height:128px;
          box-shadow:0 10px 35px rgba(26,48,45,.05);
        }
        .metric-label { color:var(--muted); font-size:.76rem; font-weight:650; }
        .metric-value { font-size:1.8rem; font-weight:800; margin:.75rem 0 .3rem; }
        .metric-change {
          display:inline-block; color:var(--positive); background:#e8f6ee;
          border-radius:5px; padding:.12rem .35rem; font-size:.68rem; font-weight:800;
        }
        .metric-foot { color:#8a9795; font-size:.68rem; margin-left:.35rem; }
        .panel {
          background:white; border:1px solid var(--line); border-radius:14px;
          padding:1.2rem; box-shadow:0 10px 35px rgba(26,48,45,.05);
        }
        .briefing {
          background:linear-gradient(120deg,#143a35,#102d2a 70%,#1c4640);
          border-radius:14px; padding:1.35rem 1.5rem; color:white; margin:.35rem 0 1rem;
        }
        .briefing .eyebrow { color:#a9c8c2; }
        .briefing h3 { color:white; margin:.15rem 0 .45rem; }
        .briefing p { color:#bfd0cd; line-height:1.65; }
        .briefing strong { color:#c9f26b; }
        .mention-card {
          background:white; border:1px solid var(--line); border-radius:12px;
          padding:1rem 1.1rem; margin-bottom:.7rem;
        }
        .mention-top { display:flex; align-items:center; gap:.5rem; margin-bottom:.5rem; }
        .source-pill,.sentiment {
          border-radius:999px; padding:.2rem .5rem; font-size:.68rem; font-weight:800;
        }
        .source-pill { color:#31534e; background:#edf3f2; }
        .sentiment.Positive { color:#198754; background:#e8f6ee; }
        .sentiment.Negative { color:#d55050; background:#fceded; }
        .sentiment.Neutral { color:#667370; background:#edf1f0; }
        .mention-title { font-weight:800; font-size:.96rem; line-height:1.4; }
        .mention-summary { color:var(--muted); font-size:.8rem; line-height:1.5; margin:.4rem 0; }
        .mention-meta { color:#8b9795; font-size:.7rem; }
        .status-ok { color:#198754; font-weight:800; }
        .status-error { color:#d55050; font-weight:800; }
        [data-testid="stMetric"] {
          background:white; border:1px solid var(--line); border-radius:12px; padding:1rem;
        }
        .stTabs [data-baseweb="tab-list"] { gap:.5rem; }
        .stTabs [data-baseweb="tab"] {
          background:white; border:1px solid var(--line); border-radius:9px;
          padding:.55rem 1rem;
        }
        .stTabs [aria-selected="true"] { background:var(--soft); color:var(--primary); }
        a { color:var(--primary) !important; }
        @media (max-width:700px) {
          .block-container { padding:1.5rem .8rem; }
          h1 { font-size:1.65rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe(value: object) -> str:
    return html.escape(str(value or ""))


def relative_time(value: datetime) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def topic_counts(rows: list[dict], brand: str) -> list[tuple[str, int]]:
    ignored = STOP_WORDS | {part.casefold() for part in re.findall(r"\w+", brand)}
    words: list[str] = []
    for row in rows:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", row["title"]):
            normalized = word.casefold().strip("-'")
            if normalized not in ignored:
                words.append(normalized)
    return Counter(words).most_common(8)


def metric_card(label: str, value: str, change: str, foot: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{safe(label)}</div>
          <div class="metric-value">{safe(value)}</div>
          <span class="metric-change">↗ {safe(change)}</span>
          <span class="metric-foot">{safe(foot)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mention(row: dict) -> None:
    summary = row["summary"] or "No summary supplied by this source."
    st.markdown(
        f"""
        <div class="mention-card">
          <div class="mention-top">
            <span class="source-pill">{SOURCE_ICONS.get(row["source"], "•")} {safe(row["source"])}</span>
            <span class="sentiment {safe(row["sentiment"])}">{safe(row["sentiment"])}</span>
          </div>
          <div class="mention-title">{safe(row["title"])}</div>
          <div class="mention-summary">{safe(summary[:300])}</div>
          <div class="mention-meta">
            {safe(row["author"])} · {safe(relative_time(row["published_at"]))} ·
            sentiment {row["sentiment_score"]:+.2f}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.link_button("Open source ↗", row["link"], width="content")


def render_overview(rows: list[dict], target: str, competitor: str | None) -> None:
    target_rows = [row for row in rows if row["brand"] == target]
    competitor_rows = [row for row in rows if competitor and row["brand"] == competitor]
    positive = sum(row["sentiment"] == "Positive" for row in target_rows)
    negative = sum(row["sentiment"] == "Negative" for row in target_rows)
    positive_pct = round(positive / len(target_rows) * 100) if target_rows else 0
    share = round(len(target_rows) / len(rows) * 100) if rows else 0

    metric_cols = st.columns(4)
    with metric_cols[0]:
        metric_card("Total mentions", f"{len(target_rows):,}", "live", "selected filters")
    with metric_cols[1]:
        metric_card("Positive sentiment", f"{positive_pct}%", f"{positive} mentions", "title + summary")
    with metric_cols[2]:
        metric_card("Share of voice", f"{share}%", "current", "selected brands")
    with metric_cols[3]:
        metric_card("Priority mentions", f"{negative:,}", "review", "negative coverage")

    st.write("")
    chart_col, sentiment_col = st.columns([1.75, 1])
    frame = pd.DataFrame(target_rows + competitor_rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["published_at"], utc=True).dt.floor("D")
        timeline = frame.groupby(["date", "brand"]).size().reset_index(name="mentions")
        chart = (
            alt.Chart(timeline)
            .mark_line(point=True, strokeWidth=2.5)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d")),
                y=alt.Y("mentions:Q", title="Mentions", scale=alt.Scale(zero=True)),
                color=alt.Color(
                    "brand:N",
                    scale=alt.Scale(range=["#136f63", "#b4c1bf", "#6757d9"]),
                    legend=alt.Legend(title=None, orient="top"),
                ),
                tooltip=["brand:N", alt.Tooltip("date:T", format="%b %d"), "mentions:Q"],
            )
            .properties(height=310)
        )
        with chart_col:
            st.markdown('<div class="eyebrow">Conversation activity</div>', unsafe_allow_html=True)
            st.subheader("Mention volume")
            st.altair_chart(chart, use_container_width=True)
        with sentiment_col:
            st.markdown('<div class="eyebrow">Audience response</div>', unsafe_allow_html=True)
            st.subheader("Sentiment")
            sentiment = (
                pd.DataFrame(target_rows)
                .groupby("sentiment")
                .size()
                .reset_index(name="mentions")
            )
            donut = (
                alt.Chart(sentiment)
                .mark_arc(innerRadius=70, outerRadius=105)
                .encode(
                    theta="mentions:Q",
                    color=alt.Color(
                        "sentiment:N",
                        scale=alt.Scale(
                            domain=["Positive", "Neutral", "Negative"],
                            range=["#198754", "#c9d0ce", "#d55050"],
                        ),
                        legend=alt.Legend(title=None, orient="bottom"),
                    ),
                    tooltip=["sentiment:N", "mentions:Q"],
                )
                .properties(height=310)
            )
            st.altair_chart(donut, use_container_width=True)

    topics = topic_counts(target_rows, target)
    top_topic = topics[0][0].title() if topics else "general coverage"
    top_source = Counter(row["source"] for row in target_rows).most_common(1)
    top_source_name = top_source[0][0] if top_source else "selected sources"
    st.markdown(
        f"""
        <div class="briefing">
          <div class="eyebrow">Evidence-backed briefing</div>
          <h3>{safe(target)} is receiving the most attention around {safe(top_topic)}.</h3>
          <p>
            Pulseboard found <strong>{len(target_rows)} live mentions</strong> in the selected
            period. {safe(top_source_name)} currently contributes the largest volume.
            {negative} mentions are classified as negative and deserve manual review.
            Automated sentiment is directional, so open the supporting sources before acting.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    topic_col, attention_col = st.columns([1, 1.7])
    with topic_col:
        st.markdown('<div class="eyebrow">Conversation drivers</div>', unsafe_allow_html=True)
        st.subheader("Trending terms")
        if topics:
            topic_frame = pd.DataFrame(topics, columns=["topic", "mentions"])
            bars = (
                alt.Chart(topic_frame)
                .mark_bar(color="#136f63", cornerRadiusEnd=4)
                .encode(
                    x=alt.X("mentions:Q", title=None),
                    y=alt.Y("topic:N", sort="-x", title=None),
                    tooltip=["topic:N", "mentions:Q"],
                )
                .properties(height=300)
            )
            st.altair_chart(bars, use_container_width=True)
        else:
            st.info("Not enough text to identify topics.")
    with attention_col:
        st.markdown('<div class="eyebrow">Latest activity</div>', unsafe_allow_html=True)
        st.subheader("Mentions requiring attention")
        priority = sorted(
            target_rows,
            key=lambda row: (
                row["sentiment"] != "Negative",
                -abs(row["sentiment_score"]),
                -row["published_at"].timestamp(),
            ),
        )[:4]
        if priority:
            for row in priority:
                render_mention(row)
        else:
            st.info("No mentions match the current filters.")


def render_mentions(rows: list[dict]) -> None:
    st.markdown('<div class="eyebrow">Unified inbox</div>', unsafe_allow_html=True)
    st.header("Live mentions")
    st.caption(f"{len(rows)} results · newest first · open a source to verify context")
    if not rows:
        st.warning("No mentions match the current filters.")
        return

    page_size = 12
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=pages, value=1)
    start = (page - 1) * page_size
    for row in rows[start : start + page_size]:
        render_mention(row)


def render_analytics(rows: list[dict], target: str) -> None:
    st.markdown('<div class="eyebrow">Deeper analysis</div>', unsafe_allow_html=True)
    st.header("Analytics")
    target_rows = [row for row in rows if row["brand"] == target]
    if not target_rows:
        st.warning("No data is available for this view.")
        return

    frame = pd.DataFrame(target_rows)
    source_counts = frame.groupby("source").size().reset_index(name="mentions")
    source_chart = (
        alt.Chart(source_counts)
        .mark_bar(color="#136f63", cornerRadiusEnd=5)
        .encode(
            x=alt.X("mentions:Q", title="Mentions"),
            y=alt.Y("source:N", sort="-x", title=None),
            tooltip=["source:N", "mentions:Q"],
        )
        .properties(height=280)
    )
    sentiment_counts = (
        frame.groupby(["source", "sentiment"]).size().reset_index(name="mentions")
    )
    sentiment_chart = (
        alt.Chart(sentiment_counts)
        .mark_bar()
        .encode(
            x=alt.X("mentions:Q", stack="normalize", title="Share"),
            y=alt.Y("source:N", title=None),
            color=alt.Color(
                "sentiment:N",
                scale=alt.Scale(
                    domain=["Positive", "Neutral", "Negative"],
                    range=["#198754", "#c9d0ce", "#d55050"],
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=["source:N", "sentiment:N", "mentions:Q"],
        )
        .properties(height=280)
    )
    first, second = st.columns(2)
    with first:
        st.subheader("Mentions by source")
        st.altair_chart(source_chart, use_container_width=True)
    with second:
        st.subheader("Sentiment by source")
        st.altair_chart(sentiment_chart, use_container_width=True)


def render_source_health(statuses: list[dict]) -> None:
    st.markdown('<div class="eyebrow">Collection diagnostics</div>', unsafe_allow_html=True)
    st.header("Source health")
    st.caption("Failures are shown explicitly; Pulseboard never silently drops a source.")
    if not statuses:
        st.info("No source checks have run.")
        return
    frame = pd.DataFrame(statuses)
    frame["Status"] = frame["ok"].map({True: "Connected", False: "Unavailable"})
    st.dataframe(
        frame[["brand", "source", "Status", "count", "message"]].rename(
            columns={
                "brand": "Brand",
                "source": "Source",
                "count": "Mentions",
                "message": "Details",
            }
        ),
        width="stretch",
        hide_index=True,
    )


inject_styles()

if "brands" not in st.session_state:
    st.session_state.brands = DEFAULT_BRANDS.copy()

with st.sidebar:
    st.markdown("## 📡 Pulseboard")
    st.caption("Live brand intelligence")
    target_brand = st.selectbox("Primary brand", st.session_state.brands)
    competitor_options = ["None"] + [
        brand for brand in st.session_state.brands if brand != target_brand
    ]
    competitor_choice = st.selectbox("Compare with", competitor_options)
    competitor_brand = None if competitor_choice == "None" else competitor_choice

    st.divider()
    new_brand = st.text_input("Add a tracked brand", placeholder="e.g. Ring")
    if st.button("Add brand", width="stretch"):
        cleaned = new_brand.strip()
        if cleaned and cleaned.casefold() not in {
            brand.casefold() for brand in st.session_state.brands
        }:
            st.session_state.brands.append(cleaned)
            st.rerun()

    st.divider()
    selected_sources = st.multiselect("Sources", SOURCES, default=SOURCES)
    date_window = st.select_slider(
        "Date range",
        options=[1, 3, 7, 14, 30],
        value=30,
        format_func=lambda days: f"Last {days} days",
    )
    selected_sentiments = st.multiselect(
        "Sentiment",
        ["Positive", "Neutral", "Negative"],
        default=["Positive", "Neutral", "Negative"],
    )
    query = st.text_input("Search", placeholder="Headline, author, publisher")

    st.divider()
    force_refresh = st.button("↻ Refresh live data", width="stretch")
    if force_refresh:
        st.cache_data.clear()
        st.rerun()
    if not secret("YOUTUBE_API_KEY"):
        st.caption("YouTube is paused until `YOUTUBE_API_KEY` is added to Streamlit Secrets.")

brands_to_fetch = [target_brand] + ([competitor_brand] if competitor_brand else [])
with st.spinner("Collecting live mentions…"):
    mentions, source_statuses = load_mentions(
        tuple(brands_to_fetch),
        tuple(selected_sources),
        secret("YOUTUBE_API_KEY"),
    )

cutoff = datetime.now(timezone.utc) - timedelta(days=date_window)
filtered = [
    row
    for row in mentions
    if row["published_at"] >= cutoff
    and row["sentiment"] in selected_sentiments
    and (
        not query
        or query.casefold()
        in f"{row['title']} {row['summary']} {row['author']} {row['publisher']}".casefold()
    )
]

header_left, header_right = st.columns([1, 0.32])
with header_left:
    st.markdown('<div class="eyebrow">Live brand intelligence</div>', unsafe_allow_html=True)
    st.title(f"{target_brand} intelligence")
    st.markdown(
        '<p class="subtle">What changed, why it matters, and which sources support it.</p>',
        unsafe_allow_html=True,
    )
with header_right:
    csv_frame = pd.DataFrame(filtered)
    if not csv_frame.empty:
        csv_frame["published_at"] = csv_frame["published_at"].astype(str)
    st.download_button(
        "Download CSV",
        csv_frame.to_csv(index=False).encode("utf-8"),
        file_name=f"{target_brand.casefold().replace(' ', '-')}-mentions.csv",
        mime="text/csv",
        width="stretch",
    )

overview_tab, mentions_tab, analytics_tab, health_tab = st.tabs(
    ["Overview", "Mentions", "Analytics", "Source health"]
)
with overview_tab:
    render_overview(filtered, target_brand, competitor_brand)
with mentions_tab:
    render_mentions(filtered)
with analytics_tab:
    render_analytics(filtered, target_brand)
with health_tab:
    render_source_health(source_statuses)

st.caption(
    "Sentiment is automated and should be reviewed in context. "
    "Feed availability and indexing vary by source."
)
