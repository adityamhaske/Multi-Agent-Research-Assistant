"""
Keeping unsupported claims out of a selected-files report (internal/rfcs/V3.1-corpus-scope.md §9.4).

`grounding.validate` measures; this decides what the reader sees. A unit — paragraph, bullet,
conclusion — holding a claim that is not supported is **rewritten** from its verified claims
by the PROTECTED `synthesizer.selection_repair`, and the rewrite is validated again from
scratch. Deleting sentences after the fact is what this replaces: it leaves dangling
references and conclusions whose premises are gone.

The loop is bounded. A unit still failing after `MAX_ATTEMPTS` rewrites is removed whole and
the reader is told so in place — a whole unit, so no half-sentence or orphan `[n]` survives.
A claim normalising to one already rejected is rejected again without a model call
(`reintroduced`), so a rewrite cannot launder a claim by rephrasing it slightly.

The outcome is one of three. `complete`: every remaining claim is supported and nothing went
unmeasured — the only state allowed to reach the approval gate. `unmeasured`: something
could not be judged, with its cause — the run fails rather than ship it. `no_evidence`: the
selection supports nothing the question asked — the run fails and says so.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from research_engine import grounding
from research_engine.grounding import (
    CAPTION,
    CONCLUSION,
    HEADING,
    LIMITATION,
    LIST_ITEM,
    PARAGRAPH,
    SUPPORTED,
    TABLE_ROW,
    UNMEASURED,
    Budget,
    BudgetExhausted,
    Validation,
)

MAX_ATTEMPTS = 2

REMOVED_NOTICE = grounding.REMOVED_NOTICE

#: Causes that a rewrite cannot fix — the checker itself could not run — so the loop stops
#: instead of spending more of the budget asking it again.
_TERMINAL_CAUSES = {"budget_exhausted", "provider_outage", "rate_limited", "timeout"}

_SOURCES_SPLIT_RE = re.compile(r"^#{1,6}\s*(sources|references|bibliography)\b", re.I | re.M)
_REWRITABLE = {PARAGRAPH, LIST_ITEM, LIMITATION, CONCLUSION}


@dataclass
class GroundingResult:
    text: str
    report: dict
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    failure: str | None = None


@dataclass
class _Ledger:
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    retries: int = 0
    estimated_usd: float = 0.0
    units_repaired: int = 0
    units_dropped: int = 0
    rejected: set[str] = field(default_factory=set)

    def absorb(self, v: Validation) -> None:
        self.cost_usd += v.cost_usd
        self.tokens_in += v.tokens_in
        self.tokens_out += v.tokens_out
        self.calls += v.calls
        self.retries += v.retries


def _norm(text: str) -> str:
    text = re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", " ", text.lower())
    return " ".join(re.findall(r"[a-z0-9.%]+", text))


def _split(draft: str) -> tuple[str, str]:
    m = _SOURCES_SPLIT_RE.search(draft or "")
    return (draft[: m.start()], draft[m.start() :]) if m else (draft or "", "")


def _preflight(body: str, budget: Budget) -> tuple[float, str | None]:
    """The estimated cost of validating `body`, and a refusal if it cannot fit (§9.9)."""
    units, _ = grounding.parse_units(body)
    sentences = sum(len(grounding.sentences_of(u)) for u in units)
    estimate = grounding._estimate(sentences)  # noqa: SLF001 — one estimator, one home
    tokens = (sentences + 2 * max(1, -(-sentences // grounding.BATCH))) * 900
    if budget.cost_cap and estimate and budget.spent_usd + estimate > budget.cost_cap:
        return estimate, (
            f"budget_insufficient: checking this report is estimated at ${estimate:.4f}; "
            f"${budget.spent_usd:.4f} of the ${budget.cost_cap:.2f} limit is already spent"
        )
    if budget.token_cap and budget.tokens_in + tokens > budget.token_cap:
        return estimate, (
            f"budget_insufficient: checking this report needs about {tokens:,} input tokens; "
            f"{budget.tokens_in:,} of the {budget.token_cap:,} limit are already used"
        )
    return estimate, None


async def ground(
    draft: str,
    sources: list[dict],
    *,
    question: str,
    admissible,
    budget: Budget,
) -> GroundingResult:
    """Validate `draft`, repair what fails, and return the text the reader may see."""
    body, _sources_tail = _split(draft)
    ledger = _Ledger()
    estimate, refused = _preflight(body, budget)
    ledger.estimated_usd = estimate
    if refused:
        return _finish(body, sources, None, ledger, status=UNMEASURED, failure=refused)

    validation: Validation | None = None
    # MAX_ATTEMPTS rewrites, each followed by a full re-validation; the final validation is
    # never followed by a rewrite, so every word the reader sees was checked. What still
    # fails after it is removed whole below — removal adds nothing that would need checking.
    for round_ in range(MAX_ATTEMPTS + 1):
        validation = await grounding.validate(
            body, sources, question=question, admissible=admissible, budget=budget
        )
        ledger.absorb(validation)
        for claim in validation.claims:
            if claim.state == SUPPORTED and _norm(claim.text) in ledger.rejected:
                claim.state, claim.cause = grounding.NOT_SUPPORTED, "reintroduced"
        if any(c.cause in _TERMINAL_CAUSES for c in validation.claims) or validation.unparsed_lines:
            break
        failing = sorted({c.unit for c in validation.claims if c.state != SUPPORTED})
        if not failing or round_ == MAX_ATTEMPTS:
            break
        for claim in validation.claims:
            if claim.state != SUPPORTED:
                ledger.rejected.add(_norm(claim.text))
        lines = body.splitlines()
        for index in failing:
            unit = validation.units[index]
            if unit.kind not in _REWRITABLE:
                lines[unit.line - 1] = (
                    "" if unit.kind in (TABLE_ROW, HEADING, CAPTION) else REMOVED_NOTICE
                )
                ledger.units_dropped += 1
                continue
            try:
                rewritten = await _rewrite(unit, validation, budget, ledger)
            except BudgetExhausted as exc:
                # The same form as every other unmeasured ending, so a limit crossed in a
                # repair still says which cause it was (§9.9, AC-43), not only the breach.
                return _finish(
                    body,
                    sources,
                    validation,
                    ledger,
                    status=UNMEASURED,
                    failure=f"grounding_unmeasured: budget_exhausted ({exc.reason})",
                )
            except Exception as exc:  # noqa: BLE001 — a failed rewrite is an unmeasured cause
                return _finish(
                    body,
                    sources,
                    validation,
                    ledger,
                    status=UNMEASURED,
                    failure=f"grounding_unmeasured: the repair call failed ({grounding.unmeasured_cause(exc)})",
                )
            if rewritten is None:
                lines[unit.line - 1] = REMOVED_NOTICE
                ledger.units_dropped += 1
            else:
                prefix = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", lines[unit.line - 1])
                lines[unit.line - 1] = (prefix.group(0) if prefix else "") + rewritten
                ledger.units_repaired += 1
        body = "\n".join(lines) + ("\n" if body.endswith("\n") else "")

    assert validation is not None
    if validation.unparsed_lines or any(c.state == UNMEASURED for c in validation.claims):
        causes = sorted({c.cause for c in validation.claims if c.state == UNMEASURED and c.cause})
        if "budget_exhausted" in causes and validation.budget_breach:
            causes[causes.index("budget_exhausted")] += f" ({validation.budget_breach})"
        if validation.unparsed_lines:
            causes.append("unparsed_content")
        return _finish(
            body,
            sources,
            validation,
            ledger,
            status=UNMEASURED,
            failure=f"grounding_unmeasured: {', '.join(causes)}",
        )
    if any(c.state != SUPPORTED for c in validation.claims):
        # The last round still had failing units and no rewrite left: drop them whole.
        lines = body.splitlines()
        for index in sorted({c.unit for c in validation.claims if c.state != SUPPORTED}):
            unit = validation.units[index]
            lines[unit.line - 1] = (
                "" if unit.kind in (TABLE_ROW, HEADING, CAPTION) else REMOVED_NOTICE
            )
            ledger.units_dropped += 1
        body = "\n".join(lines)
    if not any(c.state == SUPPORTED for c in validation.claims):
        return _finish(
            body,
            sources,
            validation,
            ledger,
            status="no_evidence",
            failure="selection_no_evidence",
        )
    body = _drop_non_supporting(body, validation)
    return _finish(body, sources, validation, ledger, status="complete", failure=None)


async def _rewrite(unit, validation: Validation, budget: Budget, ledger: _Ledger) -> str | None:
    """One unit rewritten from its verified claims, or None for "nothing left to say"."""
    own = [c for c in validation.claims if c.unit == unit.index]
    verified = [c for c in own if c.state == SUPPORTED]
    rejected = [c for c in own if c.state != SUPPORTED]
    if not verified:
        return None
    findings = "\n".join(f"- {c.text}" for c in validation.claims if c.state == SUPPORTED)
    human = (
        f"Passage:\n{unit.text}\n\nVerified claims in this passage:\n"
        + "\n".join(f"- {c.text}" for c in verified)
        + "\n\nRejected claims (must not appear):\n"
        + "\n".join(f"- {c.text}" for c in rejected)
    )
    if unit.kind == CONCLUSION:
        human += f"\n\nThe only findings a conclusion may rest on:\n{findings}"
    scratch = Validation(units=[], claims=[])
    text = await grounding.call_model(
        "synthesizer.selection_repair", human, budget=budget, result=scratch
    )
    ledger.absorb(scratch)
    text = (text or "").strip()
    if not text or text.upper() == "REMOVE":
        return None
    return " ".join(text.splitlines()).strip()


def _drop_non_supporting(body: str, validation: Validation) -> str:
    """Remove each citation the per-citation check found supporting nothing in its claim."""
    lines = body.splitlines()
    for claim in validation.claims:
        if claim.state != SUPPORTED or not claim.non_supporting_cites:
            continue
        unit = validation.units[claim.unit]
        drop = frozenset(claim.non_supporting_cites)
        lines[unit.line - 1] = re.sub(
            r"\[(\d+(?:\s*,\s*\d+)*)\]",
            lambda m, drop=drop: _without(m.group(1), drop),
            lines[unit.line - 1],
        )
    return "\n".join(lines)


def _without(group: str, drop: frozenset[int]) -> str:
    nums = [n.strip() for n in group.split(",") if int(n) not in drop]
    return f"[{', '.join(nums)}]" if nums else ""


def _finish(body, sources, validation, ledger: _Ledger, *, status: str, failure: str | None):
    used = sorted({n for line in body.splitlines() for n in grounding.markers_in(line)})
    by_index = {s.get("index"): s for s in sources or [] if isinstance(s, dict)}
    tail = ""
    if used:
        tail = (
            "\n## Sources\n"
            + "\n".join(f"[{n}] {by_index[n].get('url', '')}" for n in used if n in by_index)
            + "\n"
        )
    text = body.rstrip() + "\n" + tail
    counts = validation.counts() if validation is not None else {}
    report = {
        "status": status,
        "failure": failure,
        **counts,
        "units_repaired": ledger.units_repaired,
        "units_dropped": ledger.units_dropped,
        "validation_cost": {
            "estimated_usd": round(ledger.estimated_usd, 6),
            "actual_usd": round(ledger.cost_usd, 6),
            "calls": ledger.calls,
            "tokens_in": ledger.tokens_in,
            "tokens_out": ledger.tokens_out,
            "retries": ledger.retries,
            "repairs": ledger.units_repaired,
        },
        "claims": [c.as_dict() for c in validation.claims] if validation is not None else [],
        "validated_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()
        if status == "complete"
        else None,
    }
    return GroundingResult(
        text=text,
        report=report,
        cost_usd=ledger.cost_usd,
        tokens_in=ledger.tokens_in,
        tokens_out=ledger.tokens_out,
        failure=failure,
    )
