"""Load/performance smoke test for SMRA FastAPI /query endpoint.

Two intended usage modes (mock mode is set on the **API server**, not this client):

  Infra load test (high volume, no live LLM quota burn):
    Server: MOCK_MODE=1  (+ optional PINECONE_DISABLED=1)
    Client: python -u smra/scripts/load_test.py --mode infra --concurrency 20 --requests 200

  Realistic smoke test (low volume, real Groq/Ollama/Gemini):
    Server: MOCK_MODE unset / 0
    Client: python -u smra/scripts/load_test.py --mode smoke --concurrency 2 --requests 5

Example:
    python -u smra/scripts/load_test.py --url http://127.0.0.1:8010/query --mode infra
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from typing import Any
from urllib.parse import urlparse

# Line-buffered stdout so PowerShell shows progress immediately.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

DEFAULT_QUERIES = [
    "What was AAPL closing price in January 2025?",
    "What was Apple total net sales in the 10-K?",
    "What was NVIDIA revenue in the annual filing?",
    "Show AAPL price trend and summarize Apple revenue from filings",
    "Latest news about Tesla stock",
    "Top 5 stocks by marketcap",
    "What was Reliance Industries revenue in the annual report?",
    "Microsoft cloud revenue from the filing",
]

DEFAULT_TIMEOUT_S = 30.0
PROGRESS_EVERY = 5

INFRA_SERVER_HINT = """
=== INFRA LOAD TEST — start API with MOCK_MODE (separate terminal) ===
  Set-Location "c:\\Users\\ayush\\Xplorex_demo\\gen ai internship\\llm_outputs\\bda\\stock_market"
  $env:MOCK_MODE = "1"
  $env:PINECONE_DISABLED = "1"
  Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
  python -m uvicorn smra.api:app --port 8010
  Expect /health → mock_mode : True
======================================================================
"""

SMOKE_SERVER_HINT = """
=== REALISTIC SMOKE TEST — start API WITHOUT mock mode (separate terminal) ===
  Set-Location "c:\\Users\\ayush\\Xplorex_demo\\gen ai internship\\llm_outputs\\bda\\stock_market"
  Remove-Item Env:MOCK_MODE -ErrorAction SilentlyContinue
  python -m uvicorn smra.api:app --port 8010
  Expect /health → mock_mode : False
  Uses real Groq — keep concurrency/requests low to avoid 429 rate limits.
=================================================================================
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def _health_url(query_url: str) -> str:
    parsed = urlparse(query_url)
    return f"{parsed.scheme}://{parsed.netloc}/health"


async def _check_health(client, query_url: str, expect_mock: bool | None) -> dict[str, Any]:
    health_url = _health_url(query_url)
    try:
        resp = await client.get(health_url, timeout=10.0)
        data = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:
        log(f"WARNING: could not reach {health_url}: {exc}")
        return {"reachable": False, "mock_mode": None}

    mock = data.get("mock_mode")
    log(f"Health: status={data.get('status')} provider={data.get('provider')} mock_mode={mock}")
    if expect_mock is True and not mock:
        log("WARNING: --mode infra but server mock_mode=False — you are hitting REAL LLM APIs!")
    elif expect_mock is False and mock:
        log("WARNING: --mode smoke but server mock_mode=True — results are synthetic, not end-to-end.")
    return {"reachable": True, "mock_mode": mock, **data}


async def _one_request(
    client,
    url: str,
    query: str,
    api_key: str | None,
    timeout_s: float,
) -> tuple[float, int, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    start = time.perf_counter()
    try:
        resp = await client.post(
            url,
            json={"query": query},
            headers=headers,
            timeout=timeout_s,
        )
        elapsed = time.perf_counter() - start
        body = resp.text[:200]
        return elapsed, resp.status_code, body
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return elapsed, 0, str(exc)[:200]


async def run_load_test(
    url: str,
    concurrency: int,
    total: int,
    api_key: str | None,
    timeout_s: float,
    progress_every: int,
    mode: str,
) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit("Install httpx: pip install httpx") from exc

    expect_mock = True if mode == "infra" else False if mode == "smoke" else None
    if mode == "infra":
        log(INFRA_SERVER_HINT)
    elif mode == "smoke":
        log(SMOKE_SERVER_HINT)

    queries = [DEFAULT_QUERIES[i % len(DEFAULT_QUERIES)] for i in range(total)]
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []
    errors: list[str] = []
    completed = 0
    lock = asyncio.Lock()

    async with httpx.AsyncClient() as client:
        await _check_health(client, url, expect_mock)

        log(
            f"Starting load test [{mode}]: url={url} requests={total} "
            f"concurrency={concurrency} timeout={timeout_s}s"
        )

        async def worker(idx: int, q: str) -> None:
            nonlocal completed
            async with sem:
                log(f"  [{idx}/{total}] sending…")
                elapsed, status, detail = await _one_request(
                    client, url, q, api_key, timeout_s
                )
                latencies.append(elapsed)
                statuses.append(status)
                if not (200 <= status < 300):
                    errors.append(f"#{idx} status={status} {detail}")

            async with lock:
                completed += 1
                if completed % progress_every == 0 or completed == total:
                    ok_so_far = sum(1 for s in statuses if 200 <= s < 300)
                    log(
                        f"  progress: {completed}/{total} done "
                        f"({ok_so_far} ok, {completed - ok_so_far} failed)"
                    )

        wall_start = time.perf_counter()
        await asyncio.gather(*(worker(i + 1, q) for i, q in enumerate(queries)))
        wall = time.perf_counter() - wall_start

    ok = sum(1 for s in statuses if 200 <= s < 300)
    failed = total - ok
    sorted_lat = sorted(latencies) if latencies else [0.0]

    def pct(p: float) -> float:
        idx = int(round((p / 100) * (len(sorted_lat) - 1)))
        return sorted_lat[max(0, min(idx, len(sorted_lat) - 1))]

    if errors:
        log("Sample errors (up to 3):")
        for line in errors[:3]:
            log(f"  {line}")

    return {
        "mode": mode,
        "requests": total,
        "concurrency": concurrency,
        "timeout_s": timeout_s,
        "ok": ok,
        "failed": failed,
        "wall_seconds": round(wall, 2),
        "rps": round(total / wall, 2) if wall > 0 else 0,
        "latency_avg_s": round(statistics.mean(latencies), 3) if latencies else 0,
        "latency_p50_s": round(pct(50), 3),
        "latency_p95_s": round(pct(95), 3),
        "latency_p99_s": round(pct(99), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SMRA /query load smoke test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  infra  — high volume; server MUST have MOCK_MODE=1 (no live LLM/Pinecone/Tavily)\n"
            "  smoke  — low volume; server MUST have MOCK_MODE=0 (real end-to-end latency)\n"
        ),
    )
    parser.add_argument("--url", default="http://127.0.0.1:8010/query", help="POST /query URL")
    parser.add_argument(
        "--mode",
        choices=("infra", "smoke"),
        default="smoke",
        help="infra = mocked LLM on server; smoke = real LLM (default: smoke)",
    )
    parser.add_argument("--concurrency", type=int, default=None, help="Concurrent in-flight requests")
    parser.add_argument("--requests", type=int, default=None, help="Total requests to send")
    parser.add_argument("--api-key", default="", help="Optional X-API-Key header")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-request timeout in seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=PROGRESS_EVERY,
        help=f"Log progress every N completed requests (default: {PROGRESS_EVERY})",
    )
    args = parser.parse_args()

    if args.concurrency is None:
        args.concurrency = 20 if args.mode == "infra" else 2
    if args.requests is None:
        args.requests = 200 if args.mode == "infra" else 5

    summary = asyncio.run(
        run_load_test(
            args.url,
            max(1, args.concurrency),
            max(1, args.requests),
            args.api_key or None,
            max(1.0, args.timeout),
            max(1, args.progress_every),
            args.mode,
        )
    )
    log("")
    log("SMRA load test summary")
    for k, v in summary.items():
        log(f"  {k}: {v}")
    if args.mode == "infra":
        log("  NOTE: infra mode measures routing/DB/cache/rate-limit — NOT real LLM latency.")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
