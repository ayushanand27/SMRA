import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the app directory first so Streamlit runs from repo root or smra/ both work
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

import streamlit as st
import logging
# module logger
logger = logging.getLogger("smra.app")
# Use package-qualified imports so app works when run from repo root or as a module
try:
    from smra.router import classify_intent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.web_agent import run_web_agent
except Exception:
    # Fallback to local imports when running directly from the smra/ directory
    logger.exception("Package imports failed; falling back to local imports")
    from router import classify_intent
    from agents.sql_agent import run_sql_agent
    from agents.rag_agent import run_rag_agent
    from agents.web_agent import run_web_agent
import plotly.graph_objects as go
import sqlite3
import pandas as pd


ROUTE_EXPLANATIONS = {
    "SQL": "Chosen because your question is about historical stock prices, volume, or market data stored in our database.",
    "RAG": "Chosen because your question is about financial filings, revenue, or annual reports stored as PDFs.",
    "WEB": "Chosen because your question needs real-time news or recent market events from the internet.",
    "HYBRID": "Chosen because your question needs both historical data AND document context.",
}


def _why_this_route(routes: list[str]) -> str:
    route_set = {route.upper() for route in routes}

    if {"SQL", "RAG"}.issubset(route_set):
        explanations = [ROUTE_EXPLANATIONS["HYBRID"]]
        if "WEB" in route_set:
            explanations.append(ROUTE_EXPLANATIONS["WEB"])
        return " ".join(explanations)

    explanations = [ROUTE_EXPLANATIONS[route] for route in routes if route in ROUTE_EXPLANATIONS]
    return " ".join(explanations) if explanations else "Selected by heuristics and router policy."


def _db_row_count() -> int:
    db = Path("data/smra.db")
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stock_prices")
        n = cur.fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        logger.exception("Failed to count DB rows")
        return 0


def _pdf_count() -> int:
    pdf_dir = Path("pdfs")
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("*.pdf")))


def main():
    # Ensure logging is configured so modules using logging.exception/info produce output
    logging.basicConfig(level=logging.INFO)
    st.set_page_config(page_title="SMRA", page_icon="📈", layout="wide")
    st.title("📈 Stock Market Research Assistant")
    st.caption("RAG + SQL + Live Web — interactive research")

    # Sidebar
    with st.sidebar:
        st.markdown("### Dataset & Environment")
        st.write("Rows in DB:", _db_row_count())
        st.write("PDFs ingested:", _pdf_count())
        st.write("LLM provider:", os.getenv("LLM_PROVIDER", "groq"))
        with st.expander("How it works"):
            st.write(
                "This app routes questions to a SQL agent (historical data), RAG agent (company filings), or Web agent (news). The router uses heuristics + LLM to pick the best agents."
            )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about any stock, sector, or filing..."):
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            routes = classify_intent(prompt)
            st.caption(f"🔍 Routing to: {', '.join(routes)}")

            why = _why_this_route(routes)

            with st.expander("Why this route?"):
                st.write(why)

            for route in routes:
                if route == "SQL":
                    r = run_sql_agent(prompt)
                    st.markdown(r.get("answer", ""))
                    df = r.get("data")
                    if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns:
                        fig = go.Figure()
                        # attempt to plot close price over date
                        try:
                            fig.add_scatter(x=df["date"], y=df["close"], mode="lines", name="close")
                            st.plotly_chart(fig, use_container_width=True)
                        except Exception:
                            logger.exception("Failed to plot DataFrame result")
                    # show SQL in expander
                        with st.expander("SQL Query used"):
                            st.code(r.get("sql", "No SQL available"), language="sql")

                elif route == "RAG":
                    result = run_rag_agent(prompt)
                    # If agent signals fallback, call web_agent automatically
                    if isinstance(result, dict) and result.get("fallback"):
                        st.warning("RAG did not find high-confidence matches — falling back to web search.")
                        with st.spinner("Searching web as fallback..."):
                            result = run_web_agent(prompt)

                    answer = (result or {}).get("answer", "")
                    if not answer:
                        st.error("No answer returned. Please wait a moment and try again.")
                    else:
                        st.markdown(answer)

                    source_urls = []
                    if isinstance((result or {}).get("meta"), dict):
                        source_urls = [u for u in (result or {}).get("meta", {}).get("sources", []) if u]

                    if not source_urls:
                        source_urls = [u for u in ((result or {}).get("sources", []) or []) if u]

                    if source_urls:
                        st.markdown("**Sources**")
                        for idx, url in enumerate(source_urls[:5], start=1):
                            st.markdown(f"{idx}. [{url}]({url})")
                    else:
                        articles = (result or {}).get("data", []) or (result or {}).get("articles", [])
                        if articles:
                            st.markdown("**Sources**")
                            for idx, a in enumerate(articles[:5], start=1):
                                url = a.get("url")
                                title = a.get("title") or url or "Source"
                                if url:
                                    st.markdown(f"{idx}. [{title}]({url})")
                                else:
                                    st.markdown(f"{idx}. {title}")

                    if isinstance(result, dict) and result.get("fallback"):
                        continue

                    scores = (result or {}).get("scores", [])
                    if scores:
                        avg = sum(scores) / len(scores)
                        st.progress(min(max(int(avg * 100), 0), 100))

                    srcs = (result or {}).get("sources", [])
                    if srcs:
                        clean = [os.path.basename(s) for s in srcs]
                        st.caption(f"Sources: {', '.join(clean)}")

                elif route == "WEB":
                    result = run_web_agent(prompt)
                    answer = (result or {}).get("answer", "")
                    if not answer:
                        st.error("No answer returned. Please wait a moment and try again.")
                    else:
                        st.markdown(answer)

                    source_urls = [u for u in (result or {}).get("sources", []) if u]
                    if source_urls:
                        st.markdown("**Sources**")
                        for idx, url in enumerate(source_urls[:10], start=1):
                            st.markdown(f"{idx}. [{url}]({url})")
                    else:
                        for a in (result or {}).get("articles", [])[:10]:
                            label = a.get("sentiment", {}).get("label", "Neutral")
                            score = a.get("sentiment", {}).get("score", 0.0)
                            color = "gray"
                            if label == "Positive":
                                color = "green"
                            elif label == "Negative":
                                color = "red"
                            # clickable link and colored badge
                            st.markdown(f"- <a href='{a.get('url')}' target='_blank'>{a.get('title')}</a> <span style='color:{color}'>[{label} {score:.2f}]</span>", unsafe_allow_html=True)

            st.warning("⚠️ This is not financial advice. Consult a licensed advisor.")


if __name__ == "__main__":
    main()
