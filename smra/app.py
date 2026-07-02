import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

_SMRA_ROOT = Path(__file__).resolve().parent
env_path = _SMRA_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.orchestrator import synthesize_hybrid_answer
    from smra.router import classify_intent
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.guardrails import check_input
    from smra.utils.observability import configure_logging, get_query_id, new_query_id
    from smra.utils.schemas import expand_routes
except (ModuleNotFoundError, ImportError):
    from agents.rag_agent import run_rag_agent
    from agents.sql_agent import run_sql_agent
    from agents.web_agent import run_web_agent
    from orchestrator import synthesize_hybrid_answer
    from router import classify_intent

    from utils import audit
    from utils.config import get_settings
    from utils.guardrails import check_input
    from utils.observability import configure_logging, get_query_id, new_query_id
    from utils.schemas import expand_routes

logger = logging.getLogger("smra.app")

ROUTE_EXPLANATIONS = {
    "SQL": "Chosen because your question is about historical stock prices, volume, or market data stored in our database.",
    "RAG": "Chosen because your question is about financial filings, revenue, or annual reports stored as PDFs.",
    "WEB": "Chosen because your question needs real-time news or recent market events from the internet.",
    "HYBRID": "Chosen because your question needs both historical data AND document context.",
}


def _why_this_route(routes: list[str]) -> str:
    route_set = {route.upper() for route in routes}

    if "HYBRID" in route_set or {"SQL", "RAG"}.issubset(route_set):
        explanations = [ROUTE_EXPLANATIONS["HYBRID"]]
        if "WEB" in route_set:
            explanations.append(ROUTE_EXPLANATIONS["WEB"])
        return " ".join(explanations)

    explanations = [ROUTE_EXPLANATIONS[route] for route in routes if route in ROUTE_EXPLANATIONS]
    return " ".join(explanations) if explanations else "Selected by heuristics and router policy."


def _db_row_count() -> int:
    db = _SMRA_ROOT / "data" / "smra.db"
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
    pdf_dir = _SMRA_ROOT / "pdfs"
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("*.pdf")))


def _render_sql_details(result: dict) -> None:
    df = result.get("data")
    if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns and "close" in df.columns:
        fig = go.Figure()
        try:
            fig.add_scatter(x=df["date"], y=df["close"], mode="lines", name="close")
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            logger.exception("Failed to plot DataFrame result")

    with st.expander("SQL Query used"):
        st.code(result.get("sql") or result.get("meta", {}).get("sql", "No SQL available"), language="sql")


def _render_sql_result(prompt: str, result: dict) -> None:
    st.markdown(result.get("answer", ""))
    _render_sql_details(result)


def _render_rag_details(result: dict) -> None:
    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    source_urls = [u for u in meta.get("sources", []) if u and str(u).startswith("http")]
    if not source_urls:
        srcs = meta.get("sources") or (result or {}).get("sources", [])
        if srcs:
            clean = [os.path.basename(str(s)) for s in srcs]
            st.caption(f"Filing sources: {', '.join(clean)}")

    scores = meta.get("scores") or (result or {}).get("scores", [])
    if scores:
        avg = sum(scores) / len(scores)
        st.progress(min(max(int(avg * 100), 0), 100))


def _render_rag_result(prompt: str, result: dict) -> dict:
    if isinstance(result, dict) and result.get("fallback"):
        st.warning("RAG did not find high-confidence matches — falling back to web search.")
        with st.spinner("Searching web as fallback..."):
            result = run_web_agent(prompt)

    answer = (result or {}).get("answer", "")
    if not answer:
        st.error("No answer returned. Please wait a moment and try again.")
    else:
        st.markdown(answer)

    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    source_urls = [u for u in meta.get("sources", []) if u and str(u).startswith("http")]
    if not source_urls:
        source_urls = [u for u in ((result or {}).get("sources", []) or []) if u and str(u).startswith("http")]

    if source_urls:
        st.markdown("**Sources**")
        for idx, url in enumerate(source_urls[:5], start=1):
            st.markdown(f"{idx}. [{url}]({url})")
    else:
        srcs = meta.get("sources") or (result or {}).get("sources", [])
        if srcs:
            clean = [os.path.basename(str(s)) for s in srcs]
            st.caption(f"Filing sources: {', '.join(clean)}")

    scores = meta.get("scores") or (result or {}).get("scores", [])
    if scores:
        avg = sum(scores) / len(scores)
        st.progress(min(max(int(avg * 100), 0), 100))

    return result


def _render_web_result(result: dict) -> None:
    answer = (result or {}).get("answer", "")
    if not answer:
        st.error("No answer returned. Please wait a moment and try again.")
    else:
        st.markdown(answer)

    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    source_urls = [u for u in meta.get("sources", result.get("sources", [])) if u]
    if source_urls:
        st.markdown("**Sources**")
        for idx, url in enumerate(source_urls[:10], start=1):
            st.markdown(f"{idx}. [{url}]({url})")


def main():
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    st.set_page_config(page_title="SMRA", page_icon="📈", layout="wide")
    st.title("📈 Stock Market Research Assistant")
    st.caption("RAG + SQL + Live Web — interactive research")

    with st.sidebar:
        st.markdown("### Dataset & Environment")
        st.write("Rows in DB:", _db_row_count())
        st.write("PDFs ingested:", _pdf_count())
        st.write("LLM provider:", os.getenv("LLM_PROVIDER", "groq"))
        with st.expander("How it works"):
            st.write(
                "This app routes questions to a SQL agent (historical data), RAG agent (company filings), "
                "or Web agent (news). HYBRID runs SQL + RAG and synthesizes one answer."
            )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about any stock, sector, or filing..."):
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            new_query_id()
            guard = check_input(prompt)
            if not guard.ok:
                st.error(f"Your query could not be processed: {guard.reason}")
                st.stop()
            prompt = guard.text
            routes = classify_intent(prompt)
            st.caption(f"🔍 Routing to: {', '.join(routes)}")

            with st.expander("Why this route?"):
                st.write(_why_this_route(routes))

            execution_routes = expand_routes(routes)
            is_hybrid = "HYBRID" in routes or ("SQL" in execution_routes and "RAG" in execution_routes)

            audit_answer = ""
            audit_sql = ""
            audit_sources: list = []

            if is_hybrid:
                with st.spinner("Running SQL + RAG agents..."):
                    sql_result = run_sql_agent(prompt)
                    rag_result = run_rag_agent(prompt)
                    if isinstance(rag_result, dict) and rag_result.get("fallback"):
                        rag_result = run_web_agent(prompt)
                    unified = synthesize_hybrid_answer(prompt, sql_result, rag_result)
                st.markdown(unified)
                with st.expander("SQL details"):
                    _render_sql_details(sql_result)
                with st.expander("RAG / filing details"):
                    _render_rag_details(rag_result)
                audit_answer = unified
                audit_sql = sql_result.get("sql", "")
                audit_sources = rag_result.get("meta", {}).get("sources", []) or rag_result.get("sources", [])
            else:
                for route in execution_routes:
                    if route == "SQL":
                        result = run_sql_agent(prompt)
                        _render_sql_result(prompt, result)
                        audit_answer = result.get("answer", "")
                        audit_sql = result.get("sql", "")
                    elif route == "RAG":
                        result = _render_rag_result(prompt, run_rag_agent(prompt))
                        audit_answer = (result or {}).get("answer", "")
                        audit_sources = (result or {}).get("meta", {}).get("sources", []) or (result or {}).get("sources", [])
                    elif route == "WEB":
                        result = run_web_agent(prompt)
                        _render_web_result(result)
                        audit_answer = result.get("answer", "")
                        audit_sources = result.get("sources", [])

            audit.record(
                query_id=get_query_id(),
                query=prompt,
                routes=routes,
                answer=audit_answer,
                sql=audit_sql,
                sources=audit_sources,
                provider=settings.llm_provider,
            )

            st.warning("⚠️ This is not financial advice. Consult a licensed advisor.")


if __name__ == "__main__":
    main()
