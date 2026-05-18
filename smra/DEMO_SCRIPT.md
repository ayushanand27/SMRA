# SMRA — Presentation Demo Script

## Opening (30 seconds)

"I built a Stock Market Research Assistant that works like a mini Bloomberg terminal.
You ask it anything in plain English — stock prices, company financials, latest news —
and it figures out where to look and gives you a cited answer.

The key innovation is the routing layer. Most AI tools just search one place.
SMRA has three specialized agents and a router that picks the right one — or combines them."

---

## Demo Query 1 — SQL Agent (show first, most visual)

**Type in UI:** `What was NVDA closing price in January 2025?`

**While it loads, say:**
"This routes to the SQL agent. It converts my English question into a SQL query,
runs it against 7,560 rows of stock price data, and synthesizes a natural language answer."

**Point out:**
- "Routing to: SQL" label
- "Why this route?" expander
- The actual SQL query shown below the answer
- The Plotly chart if it appears

---

## Demo Query 2 — RAG Agent (most impressive technically)

**Type in UI:** `What was Apple total net sales?`

**While it loads, say:**
"This routes to the RAG agent — Retrieval Augmented Generation.
I have Apple's actual 10-K annual filing stored as vectors in Pinecone.
The system finds the most relevant chunks and extracts the answer."

**Point out:**
- "Routing to: RAG" — correctly identified this needs a document
- Source citation: `apple.pdf, page 40`
- The actual numbers: $383,285M (2023), $394,328M (2022), $365,817M (2021)
- Similarity scores showing retrieval confidence

**Key explanation:**
"The PDFs were scanned images — no text layer. So I built an OCR pipeline using
PyMuPDF and Tesseract to extract text page by page, then embedded it into 250 vectors.
This is the same approach Morgan Stanley uses for their internal research agents."

---

## Demo Query 3 — Web Agent

**Type in UI:** `Latest news about Tesla stock`

**While it loads, say:**
"This routes to the web search agent using Tavily API.
It fetches live articles, deduplicates them, and adds a sentiment score."

**Point out:**
- Real-time news with clickable source URLs
- Sentiment badge (Positive/Neutral/Negative)
- Sources from Bloomberg, Yahoo Finance, BBC

---

## Demo Query 4 — SQL Analytics

**Type in UI:** `Which sector had the highest average volume in 2025?`

**While it loads, say:**
"The SQL agent doesn't just do simple lookups — it can write complex aggregation queries.
This requires a GROUP BY sector with AVG(volume) — the LLM writes that SQL automatically."

**Point out:**
- Complex SQL generated automatically
- Answer: Consumer Discretionary sector

---

## Demo Query 5 — NVIDIA RAG

**Type in UI:** `What was NVIDIA revenue in 2024?`

**Point out:**
- Routes to RAG, finds nvidia.pdf
- Returns $60,922M for FY2024

---

## Architecture Explanation (1 minute)

Draw or point to the architecture:

"There are three layers:

**Layer 1 — Router:** When you type a question, Groq's Mixtral LLM classifies it.
Is this about historical data? → SQL.
Is this about company filings? → RAG.
Is this about current events? → Web.
Sometimes both SQL and WEB — that's a HYBRID query.

**Layer 2 — Agents:** Each agent is specialized.
SQL agent generates and executes database queries with retry logic.
RAG agent searches 250 Pinecone vectors with cosine similarity.
Web agent caches results for 1 hour to avoid redundant API calls.

**Layer 3 — Synthesis:** The LLM formats the raw data into a clear answer with citations."

---

## Industry Validation (30 seconds)

"This architecture isn't something I invented — it's validated by industry.

FinRobot from AI4Finance Foundation, published at ICAIF 2024 — the top AI in Finance conference — uses this exact same multi-agent pattern.

Franklin Templeton deployed the same RAG architecture to support 300+ financial advisors.

Morgan Stanley uses retrieval agents for internal financial research.

My implementation uses open-source tools and free APIs — no Bloomberg terminal required."

---

## Technical Highlights to Mention

- **OCR pipeline:** PyMuPDF tries text extraction first; falls back to Tesseract OCR for scanned pages — same approach as production document pipelines
- **Robust SQL:** Auto-retry with LLM-repaired queries when first attempt fails
- **Vector search:** 384-dimension embeddings, cosine similarity, namespace-aware search
- **Fallback chain:** RAG → local store → web if Pinecone unavailable
- **Rate limiting:** Exponential backoff, parses retry-after from Groq error messages
- **Caching:** 1-hour TTL on web results to reduce API calls

---

## Questions You Might Get

**Q: How does the router decide which agent to use?**
A: "It sends the question to the LLM with a system prompt listing rules — SQL for price/volume data, RAG for revenue/filings/earnings, WEB for news/current events. The LLM returns a JSON like `{'route': ['SQL']}`. If it's ambiguous, I have keyword fallbacks so it never crashes."

**Q: What if the PDF answer is wrong?**
A: "The system shows similarity scores alongside the answer. If the top score is below 0.5, it automatically falls back to web search instead of giving a low-confidence answer."

**Q: Why Groq instead of OpenAI?**
A: "Groq runs open models like Mixtral on specialized hardware — it's free for development, has higher rate limits than OpenAI's free tier, and is 10x faster for inference. The architecture works with any LLM provider — I built a unified wrapper."

**Q: How would you scale this to production?**
A: "Replace SQLite with PostgreSQL or Snowflake, Pinecone free tier with an enterprise index, add authentication, and deploy on cloud. The agent logic doesn't change — just swap the data layer."
