# The research record

A research run does not produce a report with citations attached to it. It produces a
record, of which the report is one part — and not the part the others are derived from. The
evidence, the claims, the sources, the conflicts and the human decision are structured
records in their own right, and the report is a rendering of them.

That inversion is the whole point. A report you cannot interrogate is a claim about
research; a record you can interrogate is research.

## The shape of a run

```
  Question
     │
     ▼
  Research plan ──────────────► you approve or change it, before any search spends money
     │
     ▼
  Evidence + Sources ─────────► what was retrieved, verbatim, with a content hash
     │
     ▼
  Revision (a report version) ─► immutable; a rework adds one, never overwrites one
     │
     ▼
  Claims ─────────────────────► each sentence the report asserts, on its own
     │
     ▼
  Claim → Evidence links ─────► which evidence, if any, a claim resolved to
     │
     ▼
  Contradictions ─────────────► two attributed quotations that cannot both hold
     │
     ▼
  Review ─────────────────────► your decision, bound to the exact bytes you read
     │
     ▼
  Artifact ───────────────────► frozen, hashed, and verifiable by someone who does not
     │                           trust this application
     ▼
  verify_bundle ──────────────► six checks, offline, no network and no model
```

## Three distinctions the product refuses to blur

These are not presentation choices. Each is enforced in the database, carried through the
API unflattened, and shown in the interface.

**Retrieved is not verified.** Every evidence item carries a provenance state, and
`UNCHECKED` means *nobody checked* — which is neither "verified" nor "failed". A system that
rendered a tick there would be claiming a check it never ran.

**Retrieved is not cited.** A source the report does not reference keeps no citation number.
It still appears in the Sources view, because hiding it would overstate how much of the
retrieval reached the report.

**A citation marker is not evidence.** A `[3]` that resolves to nothing produces no link,
and the Claims view says the claim resolved to no evidence rather than rendering prose that
looks supported.

## What approval means

Approving a report is a domain event, not a dismissed dialog. It:

- records **who** decided, **when**, and the **hash of the exact report text** they read;
- freezes a `ResearchArtifact` — a self-contained snapshot, not a set of joins, so reading
  it later cannot be changed by anything that happens to the live tables;
- is the **only** thing that can create an artifact. A plan approval cannot, and a rework
  request cannot. That rule is enforced in the schema, in the application, in the bundle
  serialization and in the verifier — four places, because each reaches somewhere the
  others do not.

The review screen shows what you are approving before you approve it: how many claims have
supporting evidence and how many do not, cited versus retrieved-only sources, unresolved
conflicts, and evidence that carries no verification. An unmeasured citation rate is
reported as unmeasured, never as `0%`.

## Verifying an artifact yourself

Download the bundle from the run's **Artifact** tab, then run the verifier that ships in
this repository:

```bash
python -m research_engine.verify_bundle path/to/research-abc12345.bundle.json
```

Add `--format json` for machine-readable output. Exit status is `0` when every check passes
and `1` when any fails. It checks six things:

| Check | What it proves |
|---|---|
| `bundle_integrity` | The bundle's own hash covers every field it contains |
| `report_integrity` | The report text matches the hash recorded for it |
| `evidence_integrity` | Every snippet matches its content hash — nothing was edited afterwards |
| `citation_resolution` | Every `[n]` in the report resolves to a source in the bundle |
| `claim_evidence_linkage` | Every cited source has evidence backing it |
| `approval_chain` | An approval exists, and its hash is the hash of *this* report |

The verifier needs no network, no API key and no model. It reads one file.

**What a passing verification does and does not mean.** It means the artifact is internally
consistent and has not been altered since it was approved. It does **not** mean the research
is correct, the sources are trustworthy, or the claims are true. Those are judgements; this
is arithmetic. The product's contribution is making the arithmetic possible.

## Self-hosting and keys

The application is self-hosted and brings your own keys. It provides no hosted model access
and requires no account with this project.

- **Server deployment** needs PostgreSQL (with pgvector), Redis, the API, a Celery worker and
  the frontend. `./start.sh` brings the whole stack up with Docker; `--fake` runs a keyless
  demo with scripted models and fixture retrievers.
- **Desktop** is a single application with a bundled sidecar and SQLite — no Postgres, no
  Redis, no worker. Provider keys live in the OS keychain.
- **Your provider keys are yours.** They are supplied by you, stored by your deployment, and
  used only for your runs. Spend limits are enforced where the provider exposes pricing;
  where it does not — OpenRouter and custom endpoints — the estimate is `0.00` and the cap
  cannot fire, so cap spend at the provider.

## Limitations, stated plainly

- **Cancellation does not interrupt work in flight.** The decision itself is durable and
  authoritative — a cancelled run stays cancelled, and the outcome that arrives afterwards
  cannot move it back to the review gate — but research already running continues to its
  next checkpoint, and the tokens it spends there are recorded rather than discarded.
- **Claims are extracted from prose**, not emitted as structured output, and carry no
  per-claim verification. `verification_state` is `UNCHECKED` on every claim written.
- **Claim lineage across revisions is not tracked.** Nothing observes that a sentence in
  revision 2 *is* the assertion from revision 1, and matching by text would manufacture a
  relationship the system never saw.
- **Contradiction detection is source-level** and unscored: the detector reports pairs it
  found, and the system neither ranks nor resolves them.
- **Corpus-mode research works** but has no end-to-end test, because corpus mode requires a
  local embedder and the test environment has none.
