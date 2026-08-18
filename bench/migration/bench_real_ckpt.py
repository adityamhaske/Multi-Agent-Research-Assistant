"""Produce AUTHENTIC checkpoints by running the real graph in fake mode."""
import asyncio, os, sys, time, uuid
sys.path.insert(0, ".")
os.environ.setdefault("LLM_MODE", "fake")
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from research_engine.graph import build_graph
from research_engine.local import run_config_from_env
from research_engine.runconfig import set_process_default
from research_engine.runner import initial_state

DSN = "postgresql://research_user:research_pass@localhost:5432/marra_bench"

async def main(n):
    set_process_default(run_config_from_env(fake=True))
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        await saver.setup()
        graph = build_graph(saver)
        ids, t0 = [], time.perf_counter()
        for i in range(n):
            sid = str(uuid.uuid4())
            cfg = {"configurable": {"thread_id": sid}}
            await graph.ainvoke(
                initial_state(session_id=sid, user_id="bench",
                              query="What are the trade-offs of logical replication?",
                              depth="fast"), cfg)
            ids.append(sid)
            if (i + 1) % 5 == 0:
                print(f"  {i+1}/{n}  ({(time.perf_counter()-t0)/(i+1):.2f}s/run)", flush=True)
        print("\n".join(ids), file=open("/tmp/bench_thread_ids.txt", "w"))
        print(f"produced {len(ids)} authentic checkpoints in {time.perf_counter()-t0:.1f}s")

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
