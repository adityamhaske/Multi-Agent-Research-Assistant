# M2C.5 — Migration Scale Benchmark

**Status:** Results for review.
**Scope:** READ-ONLY measurement. No schema migration executed, no backfill performed, no V2
table created, no production data touched.
**Measures:** the read half of the proposed P4 backfill (`V2_Migration_Plan_M2C.md` §7).

---

## 1. Methodology

### 1.1 What was measured

P4 reads a LangGraph checkpoint per run and derives V2 rows from it. M2C §15 Q5 named that
read as the unmeasured step blocking P4 scheduling. This benchmark measures it, on both hosts.

Per run, the harness performs exactly what P4 would:

1. `build_graph(saver).aget_state(thread_id)` — the same call the bundle route already uses.
2. Build evidence records with `sha256` content hashes.
3. Derive claims with `claims.claim_lines` and links with `claims.extract_citations` — the real
   canonical extractor from M0A, not a stand-in.
4. Count the V2 rows that would result.

**Nothing is written.** No V2 table exists; the harness counts projected inserts rather than
performing them.

### 1.2 Isolation

All work happened in a scratch database `marra_bench` and a scratch file
`/tmp/bench_desktop_checkpoints.sqlite`. The application database `research_db` was never
written to and never read from during measurement. Both scratch stores were dropped afterwards.

### 1.3 How the dataset was built, and why it is not simply synthetic

The local dataset is 11 sessions with a maximum checkpoint blob of **743 bytes** — fake-mode
E2E leftovers, four evidence items each with 37-character snippets. Measuring against that
would have produced fast, meaningless numbers.

A hand-built checkpoint was tried first and **rejected**: `aget_tuple` returned `None`, because
a hand-constructed dict is not in the saver's persisted format. Measuring a read path that
returns nothing would have reported excellent latency for doing no work.

The dataset therefore comes from an **authentic checkpoint template**:

1. Run the real graph in fake mode against the scratch store, producing a genuine checkpoint.
2. Read it back through the saver, inflate `channel_values["evidence"]` and `draft_report` to
   production shape, and `aput` under fresh thread ids.

The format is the saver's own; only the payload is scaled. Verified by reading one back and
confirming evidence, report and sources are present.

### 1.4 Population shape

Deliberately seeded to exercise the classification M2C §5 requires:

| Population | Share | Purpose |
|---|---|---|
| Normal runs, 12–40 evidence items, ≤500-char snippets, ~10-paragraph cited report | 88.3% | The realistic case |
| **Genuinely empty** — checkpoint present, zero evidence | 6.7% | Must not be confused with the next row |
| **Checkpoint absent** — the pruned case | 5.0% | Must not be counted as zero evidence |

**"Could not read" is never collapsed into zero.** The harness reports four outcome classes
separately, and the benchmark would be invalid if it did not distinguish them — that is the
same unmeasured-vs-zero rule the product itself runs on.

---

## 2. Dataset characteristics

| | Postgres (server) | SQLite (desktop) |
|---|---|---|
| Runs | 2,000 | 1,000 |
| Checkpoints present | 1,900 | 950 |
| Evidence per run (mean / max) | 24.2 / 40 | ~24 / 40 |
| Snippet length | ≤500 chars (the `EvidenceChunk` cap) | same |
| Report length | ~10 paragraphs, ~75% of sentences cited | same |
| Store size | 19 MB (checkpoints) | 30.1 MB |

---

## 3. Results

### 3.1 Server — Postgres, sequential

```
runs                       2000
total wall-clock           4.75s   (2.37 ms/run)
peak python heap           3.5 MB

outcome classification (never collapsed):
  READ_OK                  1767    88.3%
  NONE_PRESENT              133     6.7%     ← genuinely empty
  CHECKPOINT_MISSING        100     5.0%     ← could not read
  READ_FAILURE                0     0.0%

checkpoint read latency (ms)   p50 1.50   p95 1.97   p99 2.91   max 12.09
evidence extraction (ms)       p50 0.053  p95 0.092  p99 0.108
claim extraction (ms)          p50 0.706  p95 0.824  p99 0.874
```

The classification matches the seeded population exactly (5.0% missing, 6.7% empty), which is
the benchmark's own correctness check: a harness that silently swallowed unreadable checkpoints
would have reported 93.3% READ_OK.

**Failure rate: 0%** across 2,000 runs. Every checkpoint that existed was read.

### 3.2 Concurrency — measured, and it does not help

| Concurrency | Wall-clock | p99 checkpoint read |
|---|---|---|
| 1 | 4.75 s | 2.91 ms |
| 4 | 4.62 s | 10.83 ms |
| 8 | 4.68 s | 21.57 ms |
| 16 | 4.67 s | 40.31 ms |

**Throughput is flat while p99 degrades 14×.** `AsyncPostgresSaver` serialises on a single
connection, so concurrent `aget_state` calls queue rather than parallelise — the added
concurrency buys nothing and makes tail latency worse. Peak heap was unchanged at 3.5 MB.

### 3.3 Desktop — SQLite

```
runs                       1000
checkpoints.sqlite         30.1 MB
total wall-clock           1.59s   (1.59 ms/run)
peak python heap           0.4 MB

  READ_OK                   883   88.3%
  NONE_PRESENT               67    6.7%
  CHECKPOINT_MISSING         50    5.0%
  READ_FAILURE                0    0.0%

checkpoint read (ms)       p50 0.86  p95 1.08  p99 1.20
claim extraction (ms)      p50 0.475 p95 0.552
```

SQLite is **faster than Postgres** (0.86 ms vs 1.50 ms p50) — no socket, no network hop, and a
30 MB file that the OS page cache holds entirely.

### 3.4 Projected V2 row counts

From 2,000 runs:

| Table | Rows | Per run |
|---|---|---|
| `evidence` | 45,897 | 22.9 |
| `claims` | 104,642 | 52.3 |
| `claim_evidence_links` | 78,369 | 39.2 |
| `sources` | 3,800 | 1.9 |
| `revisions` | 1,900 | 0.9 |
| plus `research_runs`, `research_plans` | 4,000 | 2.0 |
| **Total inserts** | **238,608** | **119.3** |

`claims` is the largest table, at roughly **52 rows per run** — more than double evidence. That
is a consequence of M2A §3.5 persisting one row per cited sentence rather than deriving them at
read time, and it is the number to size indexes against.

---

## 4. Projected production-scale duration

**Read path only.** See §4.1 for what this excludes.

| Runs | Read wall-clock | Projected inserts |
|---|---|---|
| 1,000 | 2.4 s | 119,304 |
| 10,000 | 24 s | 1,193,040 |
| 100,000 | 4.0 min | 11,930,400 |
| Desktop, 2,000 | 3.2 s | ~150,000 |

### 4.1 What this projection does NOT include — stated plainly

**The write side is unmeasured.** M2C.5 is read-only, so the harness counts projected inserts
without performing them. At 100,000 runs the backfill would issue ~11.9M inserts, and **that is
very likely the dominant cost** — not the 4 minutes of reading.

Reporting "P4 takes 4 minutes" would be exactly the kind of false precision this project
refuses. The honest statement is:

> The read path is **not** the bottleneck. It costs ~2.4 ms/run and ~4 minutes at 100k runs.
> The write path is unmeasured and is expected to dominate.

Measuring it needs inserts into real V2 tables, which do not exist until M2D.

### 4.2 Two further caveats

1. **Local Docker Postgres, warm cache, no network.** A managed database across a network adds
   a round trip per `aget_state`. At +2 ms/run the 100k projection becomes ~7 minutes — still
   not a bottleneck, but the measured 1.50 ms p50 is a floor, not a forecast.
2. **Evidence volume is modelled, not observed from production.** 12–40 items per run comes
   from the pipeline's own shape (`max_critic_loops`, tasks per plan), not from a production
   sample. A deployment doing comprehensive-depth research would sit at the top of that range
   or above.

---

## 5. Bottlenecks

Ranked by measured cost per run:

| Step | p50 | Share of read path |
|---|---|---|
| **Checkpoint read** | 1.50 ms | **~66%** |
| Claim extraction | 0.71 ms | ~31% |
| Evidence extraction + hashing | 0.05 ms | ~2% |

The checkpoint read dominates, as M2C §15 Q5 predicted — but at 1.5 ms it dominates a total
that is already small. **There is no bottleneck worth optimising.**

Claim extraction at 0.71 ms/run is notable only because it is pure Python regex work over
~10 paragraphs; it scales with report length, not with database performance.

---

## 6. Can P4 run synchronously?

**Yes, for any plausible deployment size.**

- 10,000 runs read in 24 seconds.
- 100,000 runs read in 4 minutes.
- A desktop library of 2,000 runs reads in 3.2 seconds.

The desktop number matters most, because M2C §7 requires the sidecar to backfill at startup
without blocking first paint. At 3.2 seconds for a library far larger than any real desktop
user will have, that requirement is comfortably met.

**Caveat:** this answers the *read* question. Whether the whole of P4 runs synchronously
depends on the unmeasured write side (§4.1).

---

## 7. Is resumability sufficient?

**Yes, and it is the right mechanism** — but for correctness, not performance.

The `migration_ledger` (M2C §5) makes the backfill idempotent per run. At these durations,
resumability is not needed to survive long runtimes; it is needed because:

- The desktop app can be killed mid-backfill at any moment.
- A run whose checkpoint is unreadable must be *recorded* as unreadable, not retried forever.
- The 5% `CHECKPOINT_MISSING` population must be distinguishable after the fact, which is
  precisely what the ledger is for.

The measured 0% failure rate does not weaken this. Zero failures on synthetic data says
nothing about a production checkpoint written by an older library version.

---

## 8. Is batching or concurrency necessary?

**No. Measured, and it is actively harmful.**

§3.2 shows throughput flat from concurrency 1 to 16 while p99 latency degrades from 2.91 ms to
40.31 ms. The saver serialises on one connection, so concurrency adds queueing and nothing else.

Batching is equally unnecessary: peak heap was **3.5 MB** processing 2,000 runs sequentially,
because each run's state is released before the next is read. There is no memory pressure to
batch away.

This is the clearest instance of the rule *do not optimise before measuring*: a concurrent,
batched backfill would have been a reasonable-sounding design, and it would have been slower at
the tail and more complex for no gain.

---

## 9. Recommendations

1. **Run P4 sequentially, single-connection, no batching.** Measured as fastest and simplest.
   Reject concurrency unless a future measurement on real production data contradicts §3.2.
2. **Keep the migration ledger.** Justified by correctness and the 5%/6.7% split, not by
   runtime.
3. **Do not optimise the read path.** 2.37 ms/run with a 3.5 MB heap needs no work.
4. **Measure the write path in M2D**, once the V2 tables exist. It is the remaining unknown and
   probably dominates. A `COPY`-based bulk insert is the obvious first thing to compare against
   row-by-row ORM inserts — but *measure before choosing*.
5. **Run the desktop backfill at startup, sequentially, with a progress indicator.** 3.2 s for
   2,000 runs is fast enough not to need a background worker; the indicator is for the tail
   case, not the median.
6. **Re-run this benchmark against a production-sized copy before P4 is scheduled**, if one
   becomes available. §4.2's caveats are real, and the two numbers most likely to move are
   network latency and evidence volume.
7. **P4 is not schedule-blocked by the read path.** M2C §15 Q5 can be closed for reads and
   reopened for writes.

---

## 10. Reproducing

Harness scripts are in the session scratchpad, not committed — they build and drop their own
scratch stores:

| Script | Purpose |
|---|---|
| `bench_real_ckpt.py` | Produce authentic checkpoints via the real graph |
| `bench_scale_seed.py` | Inflate an authentic template to production scale (Postgres) |
| `bench_measure.py <concurrency>` | The read-only measurement |
| `bench_sqlite.py <n>` | The desktop equivalent, seed and measure |

Not committed because they are throwaway measurement tools, not project infrastructure. Say if
you would rather they lived in `backend/evals/` or a `bench/` directory — there is a reasonable
argument for keeping them so the benchmark can be re-run against production later
(recommendation 6).

---

## 11. Out of scope

No schema migration, no backfill, no V2 table, no Alembic revision, no production data read or
written, no production code changed. Scratch stores dropped.
