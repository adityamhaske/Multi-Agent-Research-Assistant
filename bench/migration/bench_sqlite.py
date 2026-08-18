"""M2C.5 — the desktop half. Same read path, AsyncSqliteSaver, scratch file only."""
import asyncio, hashlib, json, os, random, statistics as st, sys, time, tracemalloc, uuid
sys.path.insert(0, ".")
os.environ.setdefault("LLM_MODE", "fake")
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from research_engine.graph import build_graph
from research_engine.local import run_config_from_env
from research_engine.runconfig import set_process_default
from research_engine.runner import initial_state
from research_engine import claims

DB = "/tmp/bench_desktop_checkpoints.sqlite"
W = ("retrieval latency throughput replication consistency partition index cache embedding "
     "vector benchmark workload cluster shard quorum durability compaction").split()

def evidence(rng, n):
    return [{"task_id": (i % 4) + 1,
             "source_url": f"https://example.org/paper-{(i % 8) + 1}-2024",
             "source_title": f"A study of {rng.choice(W)} under load",
             "snippet": (" ".join(rng.choice(W) for _ in range(80)))[:500],
             "key_fact": " ".join(rng.choice(W) for _ in range(14))} for i in range(n)]

def report(rng, paras=10):
    out = ["# Findings\n"]
    for _ in range(paras):
        s = []
        for _ in range(rng.randint(4, 7)):
            b = " ".join(rng.choice(W) for _ in range(rng.randint(14, 26))).capitalize()
            s.append(f"{b} [{rng.randint(1,8)}]." if rng.random() < 0.75 else f"{b}.")
        out += [" ".join(s), ""]
    return "\n".join(out + ["## Sources\n"] + [f"{i}. https://example.org/p-{i}" for i in range(1, 9)])

def pct(xs, p):
    return sorted(xs)[min(int(len(xs) * p / 100), len(xs) - 1)] if xs else float("nan")

async def main(n):
    rng = random.Random(23)
    if os.path.exists(DB): os.remove(DB)
    set_process_default(run_config_from_env(fake=True))

    # 1) one authentic checkpoint as the format template
    async with AsyncSqliteSaver.from_conn_string(DB) as saver:
        g = build_graph(saver)
        tid = str(uuid.uuid4())
        await g.ainvoke(initial_state(session_id=tid, user_id="b",
                                      query="What are the trade-offs?", depth="fast"),
                        {"configurable": {"thread_id": tid}})
        tup = await saver.aget_tuple({"configurable": {"thread_id": tid}})
        assert tup, "template missing"
        ids = []
        t0 = time.perf_counter()
        for k in range(n):
            sid = str(uuid.uuid4()); ids.append(sid)
            if k % 20 == 0: continue
            n_ev = 0 if k % 12 == 0 else rng.randint(12, 40)
            ck = json.loads(json.dumps(tup.checkpoint, default=str))
            ck["id"] = str(uuid.uuid4())
            cv = ck.setdefault("channel_values", {})
            cv["evidence"] = evidence(rng, n_ev); cv["draft_report"] = report(rng)
            await saver.aput({"configurable": {"thread_id": sid, "checkpoint_ns": ""}},
                             ck, {"source": "loop", "step": 7, "writes": {}},
                             ck.get("channel_versions", {}))
        seed_s = time.perf_counter() - t0

    size_mb = os.path.getsize(DB) / 1024 / 1024
    ck_ms, cl_ms = [], []
    out = {"READ_OK": 0, "NONE_PRESENT": 0, "CHECKPOINT_MISSING": 0, "READ_FAILURE": 0}
    rows = 0
    tracemalloc.start(); t0 = time.perf_counter()
    async with AsyncSqliteSaver.from_conn_string(DB) as saver:
        g = build_graph(saver)
        for sid in ids:
            t = time.perf_counter()
            try:
                state = (await g.aget_state({"configurable": {"thread_id": sid}})).values
            except Exception:
                out["READ_FAILURE"] += 1; continue
            ck_ms.append((time.perf_counter() - t) * 1000)
            if not state:
                out["CHECKPOINT_MISSING"] += 1; continue
            ev = state.get("evidence") or []
            for e in ev: hashlib.sha256((e.get("snippet") or "").encode()).hexdigest()
            t = time.perf_counter()
            cl = claims.claim_lines(state.get("draft_report") or "")
            cl_ms.append((time.perf_counter() - t) * 1000)
            out["NONE_PRESENT" if not ev else "READ_OK"] += 1
            rows += len(ev) + len(cl)
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()

    print(f"\n{'='*66}\nM2C.5 — desktop (SQLite) read path\n{'='*66}")
    print(f"runs                       {n}   (seed {seed_s:.1f}s)")
    print(f"checkpoints.sqlite         {size_mb:.1f} MB")
    print(f"total wall-clock           {wall:.2f}s   ({wall/n*1000:.2f} ms/run)")
    print(f"peak python heap           {peak/1024/1024:.1f} MB")
    for k, v in out.items(): print(f"  {k:22} {v:6}  {v/n*100:5.1f}%")
    print(f"checkpoint read (ms)       p50 {pct(ck_ms,50):.2f}  p95 {pct(ck_ms,95):.2f}  p99 {pct(ck_ms,99):.2f}")
    print(f"claim extraction (ms)      p50 {pct(cl_ms,50):.3f}  p95 {pct(cl_ms,95):.3f}")
    print(f"projected V2 rows          {rows}  ({rows/n:.1f}/run)")
    print(f"\nprojection (a desktop library is small)")
    for s in (100, 500, 2000):
        print(f"  {s:>5} runs  →  {wall/n*s:7.1f} s")

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000))
