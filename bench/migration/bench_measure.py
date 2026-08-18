"""M2C.5 — READ-ONLY measurement of the proposed P4 backfill read path.

Reads from marra_bench. Writes NOTHING. Does not create V2 tables.
Measures the two expensive steps: checkpoint read, and claim/evidence derivation.
"""
import asyncio, hashlib, json, statistics as st, sys, time, tracemalloc
sys.path.insert(0, ".")
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from research_engine.graph import build_graph
from research_engine import claims

DSN = "postgresql://research_user:research_pass@localhost:5432/marra_bench"

# The four outcome classes M2C §5 requires. "Could not read" is NEVER collapsed into zero.
READ_OK, EMPTY, UNREADABLE, FAILED = "READ_OK", "NONE_PRESENT", "CHECKPOINT_MISSING", "READ_FAILURE"

def pct(xs, p):
    return sorted(xs)[min(int(len(xs) * p / 100), len(xs) - 1)] if xs else float("nan")

async def main(concurrency=1):
    ids = open("/tmp/bench_scale_ids.txt").read().split()
    ck_ms, ev_ms, cl_ms = [], [], []
    outcome = {READ_OK: 0, EMPTY: 0, UNREADABLE: 0, FAILED: 0}
    rows = {"evidence": 0, "claims": 0, "links": 0, "sources": 0, "revisions": 0}
    ev_per_run = []

    tracemalloc.start()
    t0 = time.perf_counter()
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        graph = build_graph(saver)
        sem = asyncio.Semaphore(concurrency)

        async def one(sid):
            async with sem:
                t = time.perf_counter()
                try:
                    state = (await graph.aget_state({"configurable": {"thread_id": sid}})).values
                except Exception:
                    outcome[FAILED] += 1
                    return
                ck_ms.append((time.perf_counter() - t) * 1000)
                if not state:
                    outcome[UNREADABLE] += 1      # distinct from "had no evidence"
                    return

                t = time.perf_counter()
                ev = state.get("evidence") or []
                recs = [{"source_url": e.get("source_url", ""),
                         "snippet": e.get("snippet", ""),
                         "content_hash": hashlib.sha256((e.get("snippet") or "").encode()).hexdigest()}
                        for e in ev]
                ev_ms.append((time.perf_counter() - t) * 1000)

                report = state.get("draft_report") or ""
                t = time.perf_counter()
                cl = claims.claim_lines(report)
                links = sum(len(claims.extract_citations(c)) for c in cl)
                cl_ms.append((time.perf_counter() - t) * 1000)

                if not ev:
                    outcome[EMPTY] += 1
                else:
                    outcome[READ_OK] += 1
                ev_per_run.append(len(ev))
                rows["evidence"] += len(recs); rows["claims"] += len(cl)
                rows["links"] += links; rows["sources"] += len(state.get("sources") or [])
                rows["revisions"] += 1 if report else 0

        await asyncio.gather(*(one(s) for s in ids))
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()

    n = len(ids)
    print(f"\n{'='*66}\nM2C.5 — P4 backfill read path   (concurrency={concurrency})\n{'='*66}")
    print(f"runs                       {n}")
    print(f"total wall-clock           {wall:.2f}s   ({wall/n*1000:.2f} ms/run)")
    print(f"peak python heap           {peak/1024/1024:.1f} MB")
    print(f"\noutcome classification (never collapsed):")
    for k in (READ_OK, EMPTY, UNREADABLE, FAILED):
        print(f"  {k:22} {outcome[k]:6}   {outcome[k]/n*100:5.1f}%")
    print(f"\ncheckpoint read latency (ms)")
    for label, p in (("p50", 50), ("p95", 95), ("p99", 99)):
        print(f"  {label}                      {pct(ck_ms,p):7.2f}")
    print(f"  mean                     {st.mean(ck_ms):7.2f}   max {max(ck_ms):.2f}")
    print(f"\nevidence extraction (ms)   p50 {pct(ev_ms,50):.3f}  p95 {pct(ev_ms,95):.3f}  p99 {pct(ev_ms,99):.3f}")
    print(f"claim extraction (ms)      p50 {pct(cl_ms,50):.3f}  p95 {pct(cl_ms,95):.3f}  p99 {pct(cl_ms,99):.3f}")
    print(f"\nprojected V2 rows from {n} runs")
    for k, v in rows.items():
        print(f"  {k:22} {v:8}   ({v/n:.1f}/run)")
    total = sum(rows.values()) + n * 2
    print(f"  {'TOTAL inserts':22} {total:8}   ({total/n:.1f}/run)")
    print(f"\nevidence per run           mean {st.mean(ev_per_run):.1f}  max {max(ev_per_run)}")
    print(f"\nprojection")
    for scale in (1_000, 10_000, 100_000):
        print(f"  {scale:>7} runs  →  {wall/n*scale/60:8.1f} min   "
              f"{int(total/n*scale):>10,} inserts")

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
