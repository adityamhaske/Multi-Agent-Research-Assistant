"""Seed N production-scale runs by inflating an AUTHENTIC checkpoint template.

Format comes from the real saver (a genuine graph run); only the payload is scaled to
production shape. Writes ONLY to marra_bench.
"""
import asyncio, json, random, sys, uuid
sys.path.insert(0, ".")
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

DSN = "postgresql://research_user:research_pass@localhost:5432/marra_bench"
W = ("retrieval latency throughput replication consistency partition index cache embedding "
     "vector benchmark workload cluster shard quorum durability compaction").split()

def evidence(rng, n):
    out = []
    for i in range(n):
        out.append({
            "task_id": (i % 4) + 1,
            "source_url": f"https://example.org/paper-{(i % 8) + 1}-2024",
            "source_title": f"A study of {rng.choice(W)} under sustained load",
            "snippet": (" ".join(rng.choice(W) for _ in range(80)))[:500],
            "key_fact": " ".join(rng.choice(W) for _ in range(14)),
        })
    return out

def report(rng, paras=10):
    out = ["# Findings\n"]
    for _ in range(paras):
        sents = []
        for _ in range(rng.randint(4, 7)):
            body = " ".join(rng.choice(W) for _ in range(rng.randint(14, 26))).capitalize()
            sents.append(f"{body} [{rng.randint(1,8)}]." if rng.random() < 0.75 else f"{body}.")
        out += [" ".join(sents), ""]
    out += ["## Limitations\n", "No production workload was measured.", "", "## Sources\n"]
    out += [f"{i}. https://example.org/paper-{i}-2024" for i in range(1, 9)]
    return "\n".join(out)

async def main(n_runs, seed=11):
    rng = random.Random(seed)
    template_id = open("/tmp/bench_thread_ids.txt").read().split()[0]
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        await saver.setup()
        tup = await saver.aget_tuple({"configurable": {"thread_id": template_id}})
        assert tup is not None, "template checkpoint missing"
        ids = []
        for k in range(n_runs):
            sid = str(uuid.uuid4()); ids.append(sid)
            if k % 20 == 0:            # 5% get NO checkpoint at all
                continue
            n_ev = 0 if k % 12 == 0 else rng.randint(12, 40)   # 8% genuinely empty
            ck = json.loads(json.dumps(tup.checkpoint, default=str))
            ck["id"] = str(uuid.uuid4())
            cv = ck.setdefault("channel_values", {})
            cv["evidence"] = evidence(rng, n_ev)
            cv["draft_report"] = report(rng)
            cv["session_id"] = sid
            await saver.aput({"configurable": {"thread_id": sid, "checkpoint_ns": ""}},
                             ck, {"source": "loop", "step": 7, "writes": {}},
                             ck.get("channel_versions", {}))
            if (k + 1) % 500 == 0:
                print(f"  {k+1}/{n_runs}", flush=True)
        open("/tmp/bench_scale_ids.txt", "w").write("\n".join(ids))
    print(f"seeded {n_runs} production-scale runs")

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000))
