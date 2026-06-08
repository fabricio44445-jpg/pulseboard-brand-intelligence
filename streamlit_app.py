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

from collectors import SOURCE_ICONS, collect_mentions, deduplicate
from storage import (
    configured as archive_configured,
    load_mentions as load_archive_mentions,
    prune_old_mentions,
    upsert_mentions,
)


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
    schema_version: int = 2,
) -> tuple[list[dict], list[dict]]:
    del schema_version
    return collect_mentions(list(brands), list(sources), youtube_api_key)


@st.cache_data(ttl=300, show_spinner=False)
def load_archive(
    url: str,
    key: str,
    brands: tuple[str, ...],
) -> tuple[list[dict], str | None]:
    return load_archive_mentions(url, key, list(brands), days=30)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#101b2b; --muted:#536273; --line:#cbd5df;
          --primary:#075e54; --primary-dark:#06483f; --soft:#dceeea;
          --positive:#087a55; --negative:#b42338; --warning:#9a5b00;
          --canvas:#e9eef3; --surface:#f9fbfc; --nav:#0b2733;
        }
        .stApp { background:var(--canvas); color:var(--ink); }
        [data-testid="stHeader"] { background:rgba(233,238,243,.94); }
        [data-testid="stSidebar"] { background:var(--nav); border-right:1px solid #244452; }
        [data-testid="stSidebar"] * { color:#eef6f7; }
        [data-testid="stSidebar"] .stButton button {
          background:#0e766a; color:#fff; border:1px solid #38a89b; font-weight:800;
          min-height:2.8rem;
        }
        [data-testid="stSidebar"] .stButton button:hover {
          background:#119184; border-color:#69cbbf;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
          color:#d9e8eb; font-size:.8rem; font-weight:800;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] > div,
        [data-testid="stSidebar"] [data-baseweb="input"] > div,
        [data-testid="stSidebar"] input {
          background:#f7fafb !important; color:#10212b !important;
          border-color:#9db0bb !important;
        }
        [data-testid="stSidebar"] input::placeholder { color:#667885 !important; opacity:1; }
        [data-testid="stSidebar"] [data-baseweb="tag"] {
          background:#dceeea !important; border:1px solid #8dbbb4 !important;
        }
        [data-testid="stSidebar"] [data-baseweb="tag"] * { color:#084d45 !important; }
        [data-testid="stSidebar"] svg { fill:#16333d; }
        [data-testid="stSidebar"] hr { border-color:#31515e; }
        [data-testid="stSidebar"] small,
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
          color:#bed0d5 !important;
        }
        .block-container { max-width:1500px; padding-top:1.25rem; }
        h1,h2,h3 { letter-spacing:-.025em; }
        h1 { font-size:2rem !important; }
        .hero {
          background:linear-gradient(115deg,#082b37 0%,#075e54 68%,#0d7668 100%);
          border:1px solid #2d8176; border-radius:18px; padding:1.35rem 1.55rem;
          box-shadow:0 16px 45px rgba(10,34,45,.18); margin-bottom:1rem;
        }
        .hero .kicker {
          color:#9fe1d4; font-size:.72rem; font-weight:900; letter-spacing:.14em;
          text-transform:uppercase;
        }
        .hero h1 { color:#fff !important; margin:.25rem 0 .35rem; }
        .hero p { color:#d2e7e4; margin:0; font-size:.9rem; }
        .mode-row { display:flex; gap:.45rem; flex-wrap:wrap; margin-top:.85rem; }
        .mode-badge {
          display:inline-flex; align-items:center; gap:.35rem; border-radius:999px;
          padding:.28rem .62rem; background:rgba(255,255,255,.1); color:#fff;
          border:1px solid rgba(255,255,255,.22); font-size:.7rem; font-weight:800;
        }
        .mode-badge.history { background:#d8f5e9; color:#07563e; border-color:#7bc9ae; }
        .mode-badge.live { background:#fff0d4; color:#744300; border-color:#e6b963; }
        .eyebrow {
          color:var(--primary); font-size:.7rem; font-weight:800;
          letter-spacing:.13em; text-transform:uppercase; margin-bottom:.35rem;
        }
        .subtle { color:var(--muted); font-size:.9rem; margin-top:-.7rem; }
        .metric-card {
          background:var(--surface); border:1px solid var(--line); border-radius:14px;
          padding:1.15rem 1.2rem; min-height:128px;
          box-shadow:0 8px 24px rgba(22,43,58,.07);
        }
        .metric-label { color:var(--muted); font-size:.76rem; font-weight:650; }
        .metric-value { font-size:1.8rem; font-weight:800; margin:.75rem 0 .3rem; }
        .metric-change {
          display:inline-block; color:var(--positive); background:#dcefe7;
          border-radius:5px; padding:.12rem .35rem; font-size:.68rem; font-weight:800;
        }
        .metric-change.down { color:var(--negative); background:#f8dfe3; }
        .metric-change.bad-up { color:var(--negative); background:#f8dfe3; }
        .metric-change.good-down { color:var(--positive); background:#dcefe7; }
        .metric-change.neutral { color:#425466; background:#e3e9ee; }
        .metric-foot { color:#8a9795; font-size:.68rem; margin-left:.35rem; }
        .panel {
          background:var(--surface); border:1px solid var(--line); border-radius:14px;
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
          background:var(--surface); border:1px solid var(--line); border-radius:12px;
          padding:1rem 1.1rem; margin-bottom:.7rem;
        }
        .mention-top { display:flex; align-items:center; gap:.5rem; margin-bottom:.5rem; }
        .source-pill,.sentiment {
          border-radius:999px; padding:.2rem .5rem; font-size:.68rem; font-weight:800;
        }
        .source-pill { color:#153d4a; background:#dfe8ed; border:1px solid #b6c8d1; }
        .sentiment.Positive { color:#075d43; background:#d8f0e5; border:1px solid #9bcdb9; }
        .sentiment.Negative { color:#8e1730; background:#f8dfe3; border:1px solid #e9aeb8; }
        .sentiment.Neutral { color:#354656; background:#e4e9ed; border:1px solid #bdc8d0; }
        .mention-title { font-weight:800; font-size:.96rem; line-height:1.4; }
        .mention-summary { color:var(--muted); font-size:.8rem; line-height:1.5; margin:.4rem 0; }
        .mention-meta { color:#8b9795; font-size:.7rem; }
        .status-ok { color:#198754; font-weight:800; }
        .status-error { color:#d55050; font-weight:800; }
        [data-testid="stMetric"] {
          background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:1rem;
        }
        .stTabs [data-baseweb="tab-list"] { gap:.5rem; }
        .stTabs [data-baseweb="tab"] {
          background:#f7fafb; border:1px solid #b9c7d0; border-radius:9px;
          padding:.55rem 1rem;
        }
        .stTabs [aria-selected="true"] {
          background:#cfe8e3 !important; color:#064e46 !important; border-color:#5b9d93;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        [data-testid="stNumberInput"] input {
          background:#f9fbfc !important; color:#101b2b !important;
          border-color:#9dabb6 !important;
        }
        .stButton button, .stDownloadButton button, .stLinkButton a {
          border-color:#8fa2af !important; color:#102d39 !important; font-weight:800 !important;
        }
        .stButton button:hover, .stDownloadButton button:hover, .stLinkButton a:hover {
          border-color:#075e54 !important; color:#064e46 !important; background:#e0efec !important;
        }
        [data-testid="stAlert"] { border:1px solid #aebdc7; }
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


def period_rows(rows: list[dict], start_days: int, end_days: int = 0) -> list[dict]:
    now = datetime.now(timezone.utc)
    oldest = now - timedelta(days=start_days)
    newest = now - timedelta(days=end_days)
    return [row for row in rows if oldest <= row["published_at"] < newest]


def percent_change(current: float, previous: float) -> tuple[str, str]:
    if previous == 0:
        if current == 0:
            return "no change", "neutral"
        return "new activity", "up"
    change = round((current - previous) / previous * 100)
    return f"{abs(change)}% vs prior 7d", "up" if change > 0 else "down" if change < 0 else "neutral"


def point_change(current: float, previous: float) -> tuple[str, str]:
    change = round(current - previous)
    return (
        f"{abs(change)} pts vs prior 7d",
        "up" if change > 0 else "down" if change < 0 else "neutral",
    )


def metric_card(
    label: str,
    value: str,
    change: str,
    foot: str,
    direction: str = "neutral",
) -> None:
    arrow = (
        "↗"
        if direction in {"up", "bad-up"}
        else "↘"
        if direction in {"down", "good-down"}
        else "•"
    )
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{safe(label)}</div>
          <div class="metric-value">{safe(value)}</div>
          <span class="metric-change {safe(direction)}">{arrow} {safe(change)}</span>
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
    current_target = period_rows(target_rows, 7)
    previous_target = period_rows(target_rows, 14, 7)
    current_all = period_rows(rows, 7)
    previous_all = period_rows(rows, 14, 7)
    current_positive = (
        sum(row["sentiment"] == "Positive" for row in current_target)
        / len(current_target)
        * 100
        if current_target
        else 0
    )
    previous_positive = (
        sum(row["sentiment"] == "Positive" for row in previous_target)
        / len(previous_target)
        * 100
        if previous_target
        else 0
    )
    current_share = len(current_target) / len(current_all) * 100 if current_all else 0
    previous_share = (
        len(previous_target) / len(previous_all) * 100 if previous_all else 0
    )
    current_negative = sum(row["sentiment"] == "Negative" for row in current_target)
    previous_negative = sum(row["sentiment"] == "Negative" for row in previous_target)

    volume_change, volume_direction = percent_change(
        len(current_target), len(previous_target)
    )
    sentiment_change, sentiment_direction = point_change(
        current_positive, previous_positive
    )
    share_change, share_direction = point_change(current_share, previous_share)
    risk_change, risk_direction = percent_change(current_negative, previous_negative)
    risk_direction = (
        "bad-up"
        if risk_direction == "up"
        else "good-down"
        if risk_direction == "down"
        else "neutral"
    )

    metric_cols = st.columns(4)
    with metric_cols[0]:
        metric_card(
            "Total mentions",
            f"{len(target_rows):,}",
            volume_change,
            "7-day movement",
            volume_direction,
        )
    with metric_cols[1]:
        metric_card(
            "Positive sentiment",
            f"{positive_pct}%",
            sentiment_change,
            f"{positive} positive mentions",
            sentiment_direction,
        )
    with metric_cols[2]:
        metric_card(
            "Share of voice",
            f"{share}%",
            share_change,
            "selected brands",
            share_direction,
        )
    with metric_cols[3]:
        metric_card(
            "Priority mentions",
            f"{negative:,}",
            risk_change,
            "negative coverage",
            risk_direction,
        )

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
            st.altair_chart(chart, width="stretch")
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
            st.altair_chart(donut, width="stretch")

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
            Pulseboard found <strong>{len(target_rows)} mentions</strong> in the selected
            period. {safe(top_source_name)} currently contributes the largest volume.
            {negative} mentions are classified as negative and deserve manual review.
            Seven-day volume is {safe(volume_change.lower())}. Automated sentiment is
            directional, so open the supporting sources before acting.
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
            st.altair_chart(bars, width="stretch")
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
        st.altair_chart(source_chart, width="stretch")
    with second:
        st.subheader("Sentiment by source")
        st.altair_chart(sentiment_chart, width="stretch")


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
    st.markdown("## ◉ Pulseboard")
    st.caption("Brand intelligence workspace")
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
    live_mentions, source_statuses = load_mentions(
        tuple(brands_to_fetch),
        tuple(selected_sources),
        secret("YOUTUBE_API_KEY"),
        2,
    )

supabase_url = secret("SUPABASE_URL")
supabase_key = secret("SUPABASE_SERVICE_ROLE_KEY")
history_enabled = archive_configured(supabase_url, supabase_key)
archive_message = ""

if history_enabled:
    stored_count, store_error = upsert_mentions(
        supabase_url,
        supabase_key,
        live_mentions,
    )
    prune_error = prune_old_mentions(supabase_url, supabase_key, days=30)
    archived_mentions, load_error = load_archive(
        supabase_url,
        supabase_key,
        tuple(brands_to_fetch),
    )
    archive_error = store_error or load_error or prune_error
    if archive_error:
        archive_message = f"Archive error: {archive_error}"
        mentions = live_mentions
        history_enabled = False
    else:
        mentions = deduplicate(archived_mentions + live_mentions)
        archive_message = f"{stored_count} live rows synchronized"
else:
    session_rows = st.session_state.get("session_archive", [])
    mentions = deduplicate(session_rows + live_mentions)
    st.session_state.session_archive = mentions
    archive_message = "Add Supabase secrets for durable 30-day history"

source_statuses.append(
    {
        "brand": "Workspace",
        "source": "30-day archive",
        "count": len(mentions),
        "ok": history_enabled,
        "message": archive_message,
    }
)

cutoff = datetime.now(timezone.utc) - timedelta(days=date_window)
filtered = [
    row
    for row in mentions
    if row["published_at"] >= cutoff
    and row["source"] in selected_sources
    and row["sentiment"] in selected_sentiments
    and (
        not query
        or query.casefold()
        in f"{row['title']} {row['summary']} {row['author']} {row['publisher']}".casefold()
    )
]

latest_collection = max(
    (
        row.get("collected_at", row.get("published_at", datetime.now(timezone.utc)))
        for row in live_mentions
    ),
    default=datetime.now(timezone.utc),
)
history_badge = (
    '<span class="mode-badge history">● 30-day archive active</span>'
    if history_enabled
    else '<span class="mode-badge live">● Live-feed mode</span>'
)
youtube_badge = (
    '<span class="mode-badge">YouTube connected</span>'
    if secret("YOUTUBE_API_KEY")
    else '<span class="mode-badge">YouTube pending</span>'
)
st.markdown(
    f"""
    <section class="hero">
      <div class="kicker">Live brand intelligence</div>
      <h1>{safe(target_brand)} intelligence</h1>
      <p>What changed, why it matters, and which public sources support it.</p>
      <div class="mode-row">
        {history_badge}
        {youtube_badge}
        <span class="mode-badge">Updated {safe(relative_time(latest_collection))}</span>
        <span class="mode-badge">{len(filtered)} visible mentions</span>
      </div>
    </section>
    """,
    unsafe_allow_html=True,
)

download_col, freshness_col = st.columns([0.28, 0.72])
with download_col:
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
with freshness_col:
    if history_enabled:
        st.success(
            "Accumulation is active. New mentions are deduplicated and retained for 30 days.",
            icon="✓",
        )
    else:
        st.warning(
            "Current feeds are live, but history is only retained for this session. "
            "Configure Supabase to accumulate a full month.",
            icon="!",
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
