"""Load/performance smoke test for SMRA FastAPI /query endpoint.

Uses asyncio + httpx (no Locust dependency). Reports latency percentiles and throughput.

Example:
    python smra/scripts/load_test.py --url http://127.0.0.1:8010/query --concurrency 10 --requests 30
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Any

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


async def _one_request(client, url: str, query: str, api_key: str | None) -> tuple[float, int, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    start = time.perf_counter()
    try:
        resp = await client.post(url, json={"query": query}, headers=headers, timeout=120.0)
        elapsed = time.perf_counter() - start
        body = resp.text[:200]
        return elapsed, resp.status_code, body
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return elapsed, 0, str(exc)[:200]


async def run_load_test(url: str, concurrency: int, total: int, api_key: str | None) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit("Install httpx: pip install httpx") from exc

    queries = [DEFAULT_QUERIES[i % len(DEFAULT_QUERIES)] for i in range(total)]
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []

    async with httpx.AsyncClient() as client:
        async def worker(q: str):
            async with sem:
                elapsed, status, _ = await _one_request(client, url, q, api_key)
                latencies.append(elapsed)
                statuses.append(status)

        wall_start = time.perf_counter()
        await asyncio.gather(*(worker(q) for q in queries))
        wall = time.perf_counter() - wall_start

    ok = sum(1 for s in statuses if 200 <= s < 300)
    failed = total - ok
    sorted_lat = sorted(latencies) if latencies else [0.0]

    def pct(p: float) -> float:
        idx = int(round((p / 100) * (len(sorted_lat) - 1)))
        return sorted_lat[max(0, min(idx, len(sorted_lat) - 1))]

    return {
        "requests": total,
        "concurrency": concurrency,
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
    parser = argparse.ArgumentParser(description="SMRA /query load smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8010/query", help="POST /query URL")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent in-flight requests")
    parser.add_argument("--requests", type=int, default=20, help="Total requests to send")
    parser.add_argument("--api-key", default="", help="Optional X-API-Key header")
    args = parser.parse_args()

    summary = asyncio.run(
        run_load_test(args.url, max(1, args.concurrency), max(1, args.requests), args.api_key or None)
    )
    print("SMRA load test summary")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
