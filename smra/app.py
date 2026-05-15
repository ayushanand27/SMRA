import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the app directory first so Streamlit runs from repo root or smra/ both work
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    # fallback to any .env on the PYTHONPATH / current working dir
    load_dotenv(override=True)

import streamlit as st
from router import classify_intent
from agents.sql_agent import run_sql_agent
from agents.rag_agent import run_rag_agent
from agents.web_agent import run_web_agent
import plotly.graph_objects as go


def main():
    st.set_page_config(page_title="SMRA", page_icon="📈", layout="wide")
    st.title("📈 Stock Market Research Assistant")
    st.caption("Powered by Groq (Llama 3.1) · RAG + SQL + Live Web Search")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about any stock, sector, or filing..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant"):
            routes = classify_intent(prompt)
            st.caption(f"🔍 Routing to: {', '.join(routes)}")
            
            results = []
            for route in routes:
                if route == "SQL":
                    r = run_sql_agent(prompt)
                    st.markdown(r["answer"])
                    if not r["data"].empty and len(r["data"]) > 1:
                        # Auto-chart if data has date column
                        if "date" in r["data"].columns:
                            fig = go.Figure()
                            fig.add_scatter(x=r["data"]["date"], y=r["data"]["close"])
                            st.plotly_chart(fig, use_container_width=True)
                    results.append(r["answer"])
                
                elif route == "RAG":
                    r = run_rag_agent(prompt)
                    st.markdown(r["answer"])
                    clean_sources = [os.path.basename(s) for s in r["sources"]]
                    st.caption(f"Sources: {', '.join(clean_sources)}")
                    results.append(r["answer"])
                
                elif route == "WEB":
                    r = run_web_agent(prompt)
                    st.markdown(r["answer"])
                    results.append(r["answer"])
            
            st.warning("⚠️ This is not financial advice. Consult a licensed advisor.")


if __name__ == "__main__":
    main()
