# ClassroomAI — frontend

Vite + React + TypeScript SPA. Dev server proxies `/api` → `http://127.0.0.1:8000` so the client can call the FastAPI app at `/api/v1/...` without CORS issues during development.

## Run locally

From this directory:

```bash
npm install
npm run dev
```

Ensure the backend is running on port 8000 (see `../backend/README.md` or repo root README).

## High-level flow

1. **`src/api.ts`** — Thin wrappers around `fetch` for every backend route (`/api/v1/explain/...`, `/quiz/generate`, `/video/jobs`, etc.). Types mirror the FastAPI response models.

2. **`src/App.tsx`** — Main UI:
   - **Model stack** and **output language** apply to all API calls.
   - **Learn** tab: chapter text or screenshots → `explainFromText` / `explainFromImages` → shows markdown, optional **Diagram** from `mermaid_diagram`, visual briefs, AI illustration button.
   - **Generate explanation** also runs a **client-side pipeline**: after the explain response returns, it sequentially calls quiz, slide deck, flashcards, infographic, and lesson audio APIs (video is **not** included; use the **Video** tab).
   - Other tabs (Quiz, Slides, Flashcards, Infographic, Listen, Video) expose the same APIs with individual **Generate** buttons so one artifact can be regenerated.

3. **`src/MermaidDiagram.tsx`** — Renders Mermaid 11 diagrams: sanitizes text, tries a few safe variants, uses `mermaid.parse()` before `render()`, and treats “error SVG” output as failure so users see a text fallback instead of repeated bomb icons.

4. **Markdown in lessons** — `ReactMarkdown` uses a custom **`pre`** component (`MarkdownPre` in `App.tsx`): fenced ` ```mermaid ` blocks in `explanation_markdown` are rendered through the same `MermaidDiagram` pipeline as the dedicated `mermaid_diagram` field (so embedded diagrams are validated the same way).

5. **Styling** — `App.css` (layout, panels, quiz, slides preview, diagram boxes).

## Build

```bash
npm run build
```

Output in `dist/`; serve with any static host and configure it to forward `/api` to your backend in production if you do not use a separate API domain.
