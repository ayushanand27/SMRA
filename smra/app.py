import logging
import os
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
    from smra import ui
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.cache.semantic_cache import get_cached_answer, set_cached_answer
    from smra.orchestrator import synthesize_hybrid_answer
    from smra.router import classify_intent
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.friendly_errors import safe_agent_call
    from smra.utils.guardrails import check_input
    from smra.utils.observability import configure_logging, get_query_id, new_query_id
    from smra.utils.schemas import expand_routes
except (ModuleNotFoundError, ImportError):
    import ui
    from agents.rag_agent import run_rag_agent
    from agents.sql_agent import run_sql_agent
    from agents.web_agent import run_web_agent
    from cache.semantic_cache import get_cached_answer, set_cached_answer
    from orchestrator import synthesize_hybrid_answer
    from router import classify_intent
    from utils.config import get_settings
    from utils.friendly_errors import safe_agent_call
    from utils.guardrails import check_input
    from utils.observability import configure_logging, get_query_id, new_query_id
    from utils.schemas import expand_routes

    from utils import audit

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
    try:
        from smra.utils.db import scalar_query
    except (ModuleNotFoundError, ImportError):
        from utils.db import scalar_query
    try:
        return int(scalar_query("SELECT COUNT(*) FROM stock_prices") or 0)
    except Exception:
        logger.exception("Failed to count DB rows")
        return 0


def _pdf_count() -> int:
    pdf_dir = _SMRA_ROOT / "pdfs"
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("*.pdf")))


def _collect_sources(result: dict) -> list:
    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    return meta.get("sources") or (result or {}).get("sources", []) or []


def _serialize_sql_result(result: dict) -> dict:
    df = result.get("data")
    records = df.to_dict(orient="records") if isinstance(df, pd.DataFrame) and not df.empty else []
    return {
        "answer": result.get("answer", ""),
        "sql": result.get("sql", "") or result.get("meta", {}).get("sql", ""),
        "data": records,
    }


def _deserialize_sql_result(payload: dict) -> dict:
    df = pd.DataFrame(payload.get("data") or [])
    return {
        "answer": payload.get("answer", ""),
        "sql": payload.get("sql", ""),
        "data": df,
        "meta": {"sql": payload.get("sql", "")},
    }


def _serialize_rag_result(result: dict) -> dict:
    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    return {
        "answer": (result or {}).get("answer", ""),
        "meta": meta,
        "sources": _collect_sources(result),
        "scores": meta.get("scores") or (result or {}).get("scores", []),
        "fallback": bool((result or {}).get("fallback")),
    }


def _deserialize_rag_result(payload: dict) -> dict:
    meta = dict(payload.get("meta") or {})
    if payload.get("sources") and "sources" not in meta:
        meta["sources"] = payload["sources"]
    if payload.get("scores") and "scores" not in meta:
        meta["scores"] = payload["scores"]
    return {
        "answer": payload.get("answer", ""),
        "meta": meta,
        "sources": payload.get("sources", []),
        "scores": payload.get("scores", []),
        "fallback": payload.get("fallback", False),
    }


def _render_assistant_message(msg: dict) -> None:
    routes = msg.get("routes") or []
    if routes:
        ui.render_route_badges(routes)
    if msg.get("route_reason"):
        with st.expander("Why this route?"):
            st.write(msg["route_reason"])

    kind = msg.get("kind")
    if kind == "sql":
        _render_sql_result("", _deserialize_sql_result(msg.get("sql_result") or {}))
    elif kind == "rag":
        _render_rag_result("", _deserialize_rag_result(msg.get("rag_result") or {}))
    elif kind == "web":
        _render_web_result(msg.get("web_result") or {"answer": msg.get("content", ""), "sources": msg.get("sources", [])})
    elif kind == "hybrid":
        ui.safe_markdown(msg.get("content", ""))
        sql_result = _deserialize_sql_result(msg.get("sql_result") or {})
        rag_result = _deserialize_rag_result(msg.get("rag_result") or {})
        with st.expander("SQL details"):
            _render_sql_details(sql_result, nested=True)
        with st.expander("RAG / filing details"):
            _render_rag_details(rag_result)
    else:
        ui.safe_markdown(msg.get("content", ""))

    if msg.get("show_disclaimer"):
        st.warning("⚠️ This is not financial advice. Consult a licensed advisor.")


def _render_sql_details(result: dict, nested: bool = False) -> None:
    df = result.get("data")
    if isinstance(df, pd.DataFrame) and not df.empty and "date" in df.columns and "close" in df.columns:
        fig = go.Figure()
        try:
            fig.add_scatter(x=df["date"], y=df["close"], mode="lines", name="close")
            st.plotly_chart(ui.style_plotly(fig), use_container_width=True)
        except Exception:
            logger.exception("Failed to plot DataFrame result")

    sql_code = result.get("sql") or result.get("meta", {}).get("sql", "No SQL available")
    # Streamlit forbids nesting an expander inside another expander (HYBRID view).
    if nested:
        st.caption("SQL query used")
        st.code(sql_code, language="sql")
    else:
        with st.expander("SQL query used"):
            st.code(sql_code, language="sql")


def _render_sql_result(prompt: str, result: dict) -> None:
    ui.safe_markdown(result.get("answer", ""))
    _render_sql_details(result)


def _render_rag_details(result: dict) -> None:
    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    ui.render_grounding(meta)
    scores = meta.get("scores") or (result or {}).get("scores", [])
    if scores:
        avg = sum(scores) / len(scores)
        st.progress(min(max(int(avg * 100), 0), 100), text="Retrieval confidence")
    ui.render_sources(_collect_sources(result), title="Filing sources")


def _render_rag_result(prompt: str, result: dict) -> dict:
    if isinstance(result, dict) and result.get("fallback"):
        st.info("No high-confidence filing match — falling back to live web search.")
        with st.spinner("Searching web as fallback..."):
            result = run_web_agent(prompt)

    answer = (result or {}).get("answer", "")
    if not answer:
        st.error("No answer returned. Please wait a moment and try again.")
    else:
        ui.safe_markdown(answer)

    meta = (result or {}).get("meta", {}) if isinstance((result or {}).get("meta"), dict) else {}
    ui.render_grounding(meta)

    scores = meta.get("scores") or (result or {}).get("scores", [])
    if scores:
        avg = sum(scores) / len(scores)
        st.progress(min(max(int(avg * 100), 0), 100), text="Retrieval confidence")

    ui.render_sources(_collect_sources(result))
    return result


def _render_web_result(result: dict) -> None:
    answer = (result or {}).get("answer", "")
    if not answer:
        st.error("No answer returned. Please wait a moment and try again.")
    else:
        ui.safe_markdown(answer)
    ui.render_sources(_collect_sources(result), limit=10)


def main():
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    st.set_page_config(page_title="SMRA — Research Assistant", page_icon="📈", layout="wide")

    ui.inject_theme()

    provider = os.getenv("LLM_PROVIDER", "groq")
    ui.render_hero(provider)

    if not ui.require_password(settings.ui_password):
        st.stop()

    with st.sidebar:
        st.markdown('<div class="smra-side-title">Workspace</div>', unsafe_allow_html=True)
        ui.render_metric("Market rows", f"{_db_row_count():,}")
        ui.render_metric("Filings ingested", _pdf_count(), unit="PDFs")
        ui.render_metric("LLM provider", provider.upper())
        st.markdown('<div class="smra-side-title" style="margin-top:18px">Capabilities</div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:13px;color:#9a9aae;line-height:1.7">'
            "• <b style='color:#3b82f6'>SQL</b> — historical OHLCV & market data<br>"
            "• <b style='color:#8b5cf6'>RAG</b> — 10-K / filings with citations<br>"
            "• <b style='color:#f59e0b'>WEB</b> — live news & sentiment<br>"
            "• <b style='color:#10b981'>HYBRID</b> — fused, synthesized answer"
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Clear conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                _render_assistant_message(msg)
            else:
                st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about any stock, sector, or filing..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        assistant_msg: dict = {"role": "assistant", "content": "", "show_disclaimer": True}

        with st.chat_message("assistant"):
            new_query_id()
            guard = check_input(prompt)
            if not guard.ok:
                st.error(f"Your query could not be processed: {guard.reason}")
                st.stop()
            prompt = guard.text

            cached = get_cached_answer(prompt)
            if cached and cached.get("answer"):
                assistant_msg["routes"] = cached.get("routes", [])
                assistant_msg["content"] = cached.get("answer", "")
                assistant_msg["kind"] = "cached"
                ui.safe_markdown(cached.get("answer", ""))
                audit.record(
                    query_id=get_query_id(),
                    query=prompt,
                    routes=cached.get("routes", []),
                    answer=cached.get("answer", ""),
                    sql=cached.get("sql", ""),
                    sources=cached.get("sources", []),
                    provider=settings.llm_provider,
                )
                st.warning("⚠️ This is not financial advice. Consult a licensed advisor.")
                st.session_state.messages.append(assistant_msg)
                st.stop()

            routes = classify_intent(prompt)
            route_reason = _why_this_route(routes)
            assistant_msg["routes"] = routes
            assistant_msg["route_reason"] = route_reason
            ui.render_route_badges(routes)

            with st.expander("Why this route?"):
                st.write(route_reason)

            execution_routes = expand_routes(routes)
            is_hybrid = "HYBRID" in routes or ("SQL" in execution_routes and "RAG" in execution_routes)

            audit_answer = ""
            audit_sql = ""
            audit_sources: list = []

            if is_hybrid:
                assistant_msg["kind"] = "hybrid"
                with st.spinner("Running SQL + RAG agents..."):
                    sql_result = safe_agent_call("SQL", run_sql_agent, prompt)
                    rag_result = safe_agent_call("RAG", run_rag_agent, prompt)
                    if isinstance(rag_result, dict) and rag_result.get("fallback"):
                        rag_result = safe_agent_call("WEB", run_web_agent, prompt)
                    unified = synthesize_hybrid_answer(prompt, sql_result if isinstance(sql_result, dict) else {}, rag_result if isinstance(rag_result, dict) else {})
                ui.safe_markdown(unified)
                assistant_msg["content"] = unified
                assistant_msg["sql_result"] = _serialize_sql_result(sql_result)
                assistant_msg["rag_result"] = _serialize_rag_result(rag_result)
                with st.expander("SQL details"):
                    _render_sql_details(sql_result, nested=True)
                with st.expander("RAG / filing details"):
                    _render_rag_details(rag_result)
                audit_answer = unified
                audit_sql = (sql_result or {}).get("sql", "") if isinstance(sql_result, dict) else ""
                audit_sources = (rag_result or {}).get("meta", {}).get("sources", []) or (rag_result or {}).get("sources", []) if isinstance(rag_result, dict) else []
                set_cached_answer(
                    prompt,
                    {
                        "routes": routes,
                        "answer": unified,
                        "sql": audit_sql,
                        "sources": audit_sources,
                    },
                )
            else:
                for route in execution_routes:
                    if route == "SQL":
                        assistant_msg["kind"] = "sql"
                        result = safe_agent_call("SQL", run_sql_agent, prompt)
                        _render_sql_result(prompt, result if isinstance(result, dict) else {})
                        assistant_msg["content"] = (result or {}).get("answer", "") if isinstance(result, dict) else ""
                        assistant_msg["sql_result"] = _serialize_sql_result(result if isinstance(result, dict) else {})
                        audit_answer = assistant_msg["content"]
                        audit_sql = (result or {}).get("sql", "") if isinstance(result, dict) else ""
                    elif route == "RAG":
                        assistant_msg["kind"] = "rag"
                        result = safe_agent_call("RAG", run_rag_agent, prompt)
                        if isinstance(result, dict) and result.get("fallback"):
                            result = safe_agent_call("WEB", run_web_agent, prompt)
                        result = _render_rag_result(prompt, result if isinstance(result, dict) else {})
                        assistant_msg["content"] = (result or {}).get("answer", "")
                        assistant_msg["rag_result"] = _serialize_rag_result(result or {})
                        audit_answer = (result or {}).get("answer", "")
                        audit_sources = (result or {}).get("meta", {}).get("sources", []) or (result or {}).get("sources", [])
                    elif route == "WEB":
                        assistant_msg["kind"] = "web"
                        result = safe_agent_call("WEB", run_web_agent, prompt)
                        _render_web_result(result)
                        assistant_msg["content"] = result.get("answer", "")
                        assistant_msg["web_result"] = {
                            "answer": result.get("answer", ""),
                            "sources": result.get("sources", []),
                            "meta": result.get("meta", {}),
                        }
                        assistant_msg["sources"] = result.get("sources", [])
                        audit_answer = result.get("answer", "")
                        audit_sources = result.get("sources", [])

            if audit_answer:
                set_cached_answer(
                    prompt,
                    {
                        "routes": routes,
                        "answer": audit_answer,
                        "sql": audit_sql,
                        "sources": audit_sources,
                    },
                )

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

        st.session_state.messages.append(assistant_msg)


if __name__ == "__main__":
    main()
