"""
Claim-level grounding for selected-files runs (internal/rfcs/V3.1-corpus-scope.md §9).

The requirement: every substantive factual claim in the answer is supported by the selected
documents, and a claim that cannot be supported is never presented as a verified conclusion.
This module decides, claim by claim, which is which — and records, without rounding off,
what it could not decide.

**Nothing here trusts a model's say-so about anything code can check.** The model splits
sentences into claims and rules on meaning; code checks that the split covers the sentence,
that every citation it names resolves to a selected document's retrieved evidence, and that
every number the claim states is in those snippets (`quantities.py`). Prompts that rule are
PROTECTED (`prompt_composition`), because a user who could rewrite them would grade their
own report.

**Four final states and no fifth.** A claim ends `supported`, `not_supported`,
`contradicted` or `unmeasured`. Unmeasured always carries a cause and is never counted as
supported or as rejected: "the checker could not run" must stay distinguishable from "the
claim is false" (AGENTS.md: unmeasured is not zero). The caller fails a run that has any
unmeasured claim left; it never ships one as verified.

This file is the measuring half. The repair loop that keeps rejected claims out of the text
is `grounding_repair.py`, and both are driven from `graph.synthesizer_node`.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from research_engine import claims, quantities
from research_engine.llm_factory import estimate_cost, get_llm, text_of, token_counts
from research_engine.prompt_composition import system_prompt
from research_engine.runconfig import get_run_config

# ── States, causes, units ─────────────────────────────────────────────────────────

SUPPORTED, NOT_SUPPORTED, CONTRADICTED, UNMEASURED = (
    "supported",
    "not_supported",
    "contradicted",
    "unmeasured",
)

#: Why a claim was rejected. `uncited`: no valid citation; `number_not_in_snippet`: a stated
#: quantity is absent from its snippets; the rest come from a model verdict.
REJECTION_CAUSES = (
    "uncited",
    "number_not_in_snippet",
    "not_supported",
    "contradicted",
    "reintroduced",
    "inference_rejected",
)

#: Why a claim could not be judged. Decided from an exception's type and status, never from
#: its message text, so a provider rewording an error cannot move a claim between causes.
UNMEASURED_CAUSES = (
    "provider_outage",
    "rate_limited",
    "timeout",
    "budget_exhausted",
    "malformed_response",
    "decomposition_invalid",
    "unparsed_content",
)

#: Units of the report the validator reads. `label` units are not claims unless they carry
#: a citation marker, a digit, or more than 12 words (§9.1).
PARAGRAPH, LIST_ITEM, TABLE_ROW, CAPTION, BLOCKQUOTE, HEADING, LIMITATION, CONCLUSION = (
    "paragraph",
    "list_item",
    "table_row",
    "caption",
    "blockquote",
    "heading",
    "limitation",
    "conclusion",
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SOURCES_RE = re.compile(r"^#{1,6}\s*(sources|references|bibliography)\b", re.IGNORECASE)
_LIMITATIONS_RE = re.compile(
    r"^#{1,6}\s*(limitations|what your files don.t cover)\b", re.IGNORECASE
)
_CONCLUSION_RE = re.compile(
    r"^#{1,6}\s*(conclusion|conclusions|summary|executive summary|overall|in short|key findings)\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
_CAPTION_RE = re.compile(r"^(figure|table|source)\s*[\d:.]", re.IGNORECASE)
_ITALIC_RE = re.compile(r"^(\*[^*].*\*|_[^_].*_)$")
_UNPARSEABLE_RE = re.compile(r"^(```|~~~|<[a-zA-Z/!])")
_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SELECTION_PHRASE_RE = re.compile(
    r"\b(the selected (files|documents)|these (files|documents)|your (selected )?files|"
    r"none of the \d+ (selected )?(files|documents)|the files you selected)\b",
    re.IGNORECASE,
)


@dataclass
class Unit:
    """One piece of the draft the validator reads, in document order."""

    index: int
    kind: str
    text: str
    line: int
    section: str = ""


@dataclass
class Claim:
    """One atomic claim and everything decided about it."""

    unit: int
    sentence: str
    text: str
    span: tuple[int, int]
    cites: list[int]
    calculation: dict | None = None
    valid_cites: list[int] = field(default_factory=list)
    invalid_cites: list[int] = field(default_factory=list)
    non_supporting_cites: list[int] = field(default_factory=list)
    state: str = UNMEASURED
    cause: str | None = None

    def as_dict(self) -> dict:
        return {
            "unit": self.unit,
            "text": self.text,
            "cites": self.cites,
            "valid_cites": self.valid_cites,
            "invalid_cites": self.invalid_cites,
            "non_supporting_cites": self.non_supporting_cites,
            "state": self.state,
            "cause": self.cause,
        }


@dataclass
class Validation:
    """What one validation pass found. `units` and `claims` are in document order."""

    units: list[Unit]
    claims: list[Claim]
    unparsed_lines: list[int] = field(default_factory=list)
    limitation_violations: list[int] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    retries: int = 0
    estimated_usd: float = 0.0
    failure: str | None = None

    def counts(self) -> dict:
        rejected = {cause: 0 for cause in REJECTION_CAUSES}
        unmeasured = {cause: 0 for cause in UNMEASURED_CAUSES}
        supported = 0
        for c in self.claims:
            if c.state == SUPPORTED:
                supported += 1
            elif c.state == UNMEASURED:
                unmeasured[c.cause or "malformed_response"] += 1
            else:
                rejected[c.cause or c.state] += 1
        if self.unparsed_lines:
            unmeasured["unparsed_content"] += len(self.unparsed_lines)
        return {
            "claims_total": len(self.claims),
            "claims_supported": supported,
            "claims_rejected": sum(rejected.values()),
            "rejected_by_cause": rejected,
            "claims_unmeasured": sum(unmeasured.values()),
            "unmeasured_by_cause": unmeasured,
            "invalid_citations": sum(len(c.invalid_cites) for c in self.claims),
            "non_supporting_citations": sum(len(c.non_supporting_cites) for c in self.claims),
        }


# ── Parsing the draft into units (§9.1) ───────────────────────────────────────────


def parse_units(draft: str) -> tuple[list[Unit], list[int]]:
    """Every line of the draft, assigned to exactly one unit — or reported as unparsed.

    Stops at the Sources heading: the reference list is generated, not asserted. A line no
    rule recognises (raw HTML, a code fence) is returned in the second list rather than
    skipped, so content cannot escape validation by being formatted oddly (AC-38).
    """
    units: list[Unit] = []
    unparsed: list[int] = []
    section, in_table, last_was_table = "", False, False
    for number, raw in enumerate((draft or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            in_table = False
            continue
        if _SOURCES_RE.match(line):
            break
        heading = _HEADING_RE.match(line)
        if heading:
            section = line
            units.append(Unit(len(units), HEADING, heading.group(2).strip(), number, section))
            in_table = last_was_table = False
            continue
        if _UNPARSEABLE_RE.match(line):
            unparsed.append(number)
            continue
        kind_in_section = (
            LIMITATION
            if _LIMITATIONS_RE.match(section)
            else CONCLUSION
            if _CONCLUSION_RE.match(section)
            else None
        )
        if line.startswith("|"):
            if _TABLE_SEPARATOR_RE.match(line):
                continue
            if not in_table:
                in_table = last_was_table = True
                continue  # the header row is a label
            units.append(Unit(len(units), TABLE_ROW, line.strip("|").strip(), number, section))
            continue
        if line.startswith(">"):
            units.append(Unit(len(units), BLOCKQUOTE, line.lstrip("> ").strip(), number, section))
            last_was_table = False
            continue
        if _CAPTION_RE.match(line) or (last_was_table and _ITALIC_RE.match(line)):
            units.append(Unit(len(units), CAPTION, line.strip("*_ "), number, section))
            last_was_table = False
            continue
        last_was_table = False
        if _LIST_RE.match(line):
            text = _LIST_RE.sub("", line)
            units.append(Unit(len(units), kind_in_section or LIST_ITEM, text, number, section))
            continue
        units.append(Unit(len(units), kind_in_section or PARAGRAPH, line, number, section))
    return units, unparsed


def heading_is_claim(text: str) -> bool:
    """A heading is a topic label — unless it carries a marker, a digit or a sentence."""
    return bool(_MARKER_RE.search(text)) or bool(re.search(r"\d", text)) or len(text.split()) > 12


def limitation_is_about_the_selection(sentence: str, question: str) -> bool:
    """A "what your files don't cover" sentence must be about the selection, not the world.

    Deterministic: it names the selection, carries no citation marker, and states no number
    that is not already in the question. One that fails is validated as a body claim.
    """
    if _MARKER_RE.search(sentence) or not _SELECTION_PHRASE_RE.search(sentence):
        return False
    return not [q for q in quantities.extract(sentence) if q not in quantities.extract(question)]


def sentences_of(unit: Unit) -> list[str]:
    if unit.kind in (TABLE_ROW, HEADING, CAPTION):
        return [unit.text]
    return [s.strip() for s in claims.split_sentences(unit.text) if s.strip()]


def markers_in(sentence: str) -> list[int]:
    return sorted({int(p) for m in _MARKER_RE.finditer(sentence) for p in m.group(1).split(",")})


# ── Decomposition (§9.2) ──────────────────────────────────────────────────────────

_FACTUAL_TOKEN_RE = re.compile(r"\d[\d,.]*|\"[^\"]+\"|“[^”]+”|\b[A-Z][a-zA-Z]{2,}\b")


def factual_token_positions(sentence: str) -> list[int]:
    """Start offsets of everything a decomposition must cover: digits, quoted strings, and
    capitalised words — except the sentence's first word and the citation markers."""
    stripped = _MARKER_RE.sub(lambda m: " " * len(m.group(0)), sentence)
    first = re.match(r"\s*\S+", stripped)
    first_end = first.end() if first else 0
    return [m.start() for m in _FACTUAL_TOKEN_RE.finditer(stripped) if m.start() >= first_end]


def check_decomposition(sentence: str, decomposed: list[dict]) -> list[Claim] | None:
    """The claims a decomposition proposes, or None when it fails a structural check.

    Spans inside the sentence and non-overlapping; together they cover every factual token;
    every `cites` entry is a marker the sentence carries. A failure makes the whole sentence
    unmeasured — never supported — because an uncovered clause is exactly where an invented
    assertion would hide.
    """
    if not isinstance(decomposed, list):
        return None
    allowed = set(markers_in(sentence))
    out: list[Claim] = []
    spans: list[tuple[int, int]] = []
    for item in decomposed:
        if not isinstance(item, dict):
            return None
        span = item.get("span")
        text = item.get("text")
        cites = item.get("cites") or []
        if (
            not isinstance(span, list | tuple)
            or len(span) != 2
            or not all(isinstance(x, int) for x in span)
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(cites, list)
            or not all(isinstance(n, int) for n in cites)
        ):
            return None
        start, end = span
        if not (0 <= start < end <= len(sentence)):
            return None
        if any(start < e and s < end for s, e in spans):
            return None
        if not set(cites) <= allowed:
            return None
        calculation = item.get("calculation")
        if calculation is not None and not isinstance(calculation, dict):
            return None
        spans.append((start, end))
        out.append(
            Claim(
                unit=-1,
                sentence=sentence,
                text=text.strip(),
                span=(start, end),
                cites=sorted(set(cites)),
                calculation=calculation,
            )
        )
    for position in factual_token_positions(sentence):
        if not any(s <= position < e for s, e in spans):
            return None
    return out


# ── Model calls, budget and causes ────────────────────────────────────────────────

#: Backoff between retries of one call. Module-level so tests can make it instant.
RETRY_BACKOFF_SECONDS = 0.5
MAX_RETRIES = 2


class BudgetExhausted(Exception):
    """A run limit was crossed during validation. `reason` names which, and by how much."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def unmeasured_cause(exc: BaseException) -> str:
    """Which unmeasured cause an exception from a model call is — by type and status."""
    if isinstance(exc, BudgetExhausted):
        return "budget_exhausted"
    if isinstance(exc, asyncio.TimeoutError | TimeoutError) or "Timeout" in type(exc).__name__:
        return "timeout"
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status == 429 or type(exc).__name__ == "RateLimitError":
        return "rate_limited"
    return "provider_outage"


class Budget:
    """The run's existing limits, applied to validation's calls as well (§9.9).

    Starts from what the run has already spent; every validation call adds to it. Checked
    at each call boundary — a call in flight is never cut off mid-response.
    """

    def __init__(self, *, spent_usd: float, tokens_in: int, started_at: float | None) -> None:
        cfg = get_run_config()
        self.cost_cap = cfg.max_cost_per_session_usd
        self.token_cap = cfg.max_input_tokens
        self.time_cap = cfg.max_wallclock_seconds
        self.spent_usd = spent_usd
        self.tokens_in = tokens_in
        self.started_at = started_at if started_at is not None else time.time()

    def breach(self) -> str | None:
        if self.cost_cap and self.spent_usd >= self.cost_cap:
            return f"cost ceiling reached during validation: ${self.spent_usd:.4f} of ${self.cost_cap:.2f}"
        if self.token_cap and self.tokens_in >= self.token_cap:
            return (
                f"input-token ceiling reached during validation: {self.tokens_in:,} of "
                f"{self.token_cap:,}"
            )
        elapsed = time.time() - self.started_at
        if self.time_cap and elapsed >= self.time_cap:
            return f"time limit reached during validation: {elapsed:.0f}s of {self.time_cap}s"
        return None


async def call_model(purpose: str, human: str, *, budget: Budget, result: Validation) -> str:
    """One protected model call, retried for transient causes, charged to the budget.

    Raises `BudgetExhausted` before calling if a limit is already crossed, and re-raises the
    last error after `MAX_RETRIES` — the caller turns either into an unmeasured cause.
    """
    breach = budget.breach()
    if breach:
        raise BudgetExhausted(breach)
    role = purpose.split(".", 1)[0]
    model = get_llm(role)
    messages = [SystemMessage(content=system_prompt(purpose)), HumanMessage(content=human)]
    attempt = 0
    while True:
        try:
            response = await model.ainvoke(messages)
            break
        except Exception as exc:  # noqa: BLE001 — classified, retried or re-raised below
            cause = unmeasured_cause(exc)
            if (
                cause not in ("rate_limited", "timeout", "provider_outage")
                or attempt >= MAX_RETRIES
            ):
                raise
            attempt += 1
            result.retries += 1
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    cost = estimate_cost(response, role)
    i, o = token_counts(response)
    result.cost_usd += cost
    result.tokens_in += i
    result.tokens_out += o
    result.calls += 1
    budget.spent_usd += cost
    budget.tokens_in += i
    return text_of(response)


_VERDICT_RE = re.compile(
    r"^\s*Claim\s+(\d+)\s*:\s*(SUPPORTED|NOT_SUPPORTED|CONTRADICTED)\s*$", re.I
)
_PAIR_RE = re.compile(r"^\s*Pair\s+(\d+)\s*:\s*(YES|NO)\s*$", re.I)


def parse_verdicts(text: str, n: int) -> list[str | None]:
    """One three-way verdict per claim; a missing or malformed line is `None` (unmeasured)."""
    out: list[str | None] = [None] * n
    for line in (text or "").splitlines():
        m = _VERDICT_RE.match(line)
        if m and 1 <= int(m.group(1)) <= n:
            out[int(m.group(1)) - 1] = m.group(2).lower()
    return out


def parse_pairs(text: str, n: int) -> list[bool | None]:
    out: list[bool | None] = [None] * n
    for line in (text or "").splitlines():
        m = _PAIR_RE.match(line)
        if m and 1 <= int(m.group(1)) <= n:
            out[int(m.group(1)) - 1] = m.group(2).upper() == "YES"
    return out


def _json_array(text: str):
    """The JSON array in a model reply, tolerating a fenced block around it."""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start = body.find("[")
    if start < 0:
        raise ValueError("no JSON array in the reply")
    return json.loads(body[start : body.rfind("]") + 1])


# ── Validation ────────────────────────────────────────────────────────────────────

BATCH = 4


@dataclass
class Evidence:
    """What a citation number resolves to: its snippets, and whether it may be cited.

    `admissible` is False for a source outside the frozen selection, or one with no
    retrieved evidence behind it — a marker pointing at either cites nothing.
    """

    snippets: list[str]
    admissible: bool


def evidence_by_index(
    sources: list[dict], admissible: Callable[[str], bool]
) -> dict[int, Evidence]:
    out: dict[int, Evidence] = {}
    for source in sources or []:
        if not isinstance(source, dict) or not isinstance(source.get("index"), int):
            continue
        snippets = [s for s in (source.get("snippets") or [source.get("snippet") or ""]) if s]
        out[source["index"]] = Evidence(
            snippets=snippets, admissible=bool(snippets) and admissible(source.get("url") or "")
        )
    return out


async def validate(
    draft: str,
    sources: list[dict],
    *,
    question: str,
    admissible: Callable[[str], bool],
    budget: Budget,
) -> Validation:
    """Parse, decompose and verify every claim in `draft`. Never raises for a model failure:
    each failure becomes an unmeasured cause on the claims it left undecided."""
    units, unparsed = parse_units(draft)
    result = Validation(units=units, claims=[], unparsed_lines=unparsed)
    evidence = evidence_by_index(sources, admissible)

    # Which sentences need decomposing, and under which rule.
    todo: list[tuple[Unit, str]] = []
    for unit in units:
        if unit.kind == HEADING and not heading_is_claim(unit.text):
            continue
        for sentence in sentences_of(unit):
            if not claims.is_claim_sentence(sentence) and unit.kind != HEADING:
                continue
            if unit.kind == LIMITATION and limitation_is_about_the_selection(sentence, question):
                continue
            if unit.kind == LIMITATION:
                result.limitation_violations.append(unit.index)
            todo.append((unit, sentence))

    result.estimated_usd = _estimate(len(todo))

    await _decompose(todo, result, budget)
    decided = [c for c in result.claims if c.state == UNMEASURED and c.cause is None]
    _check_citations(decided, evidence)
    _check_quantities(decided, evidence)
    pending = [c for c in decided if c.state == UNMEASURED and c.cause is None]
    conclusion_units = {u.index for u in units if u.kind == CONCLUSION}
    body = [c for c in pending if c.unit not in conclusion_units]
    conclusions = [c for c in pending if c.unit in conclusion_units]
    await _verify(body, evidence, result, budget, purpose="critic.claim_verify")
    await _relevance(body, evidence, result, budget)
    supported = [c for c in result.claims if c.state == SUPPORTED]
    await _verify_inference(conclusions, supported, evidence, result, budget)
    return result


def _estimate(sentences: int) -> float:
    """A pre-flight estimate of validation's cost: calls × observed tokens × the price.

    One decomposition call per sentence, and per four claims one verification and one
    relevance call — taken at roughly one claim per sentence. 0.0 when the route is
    unpriced, which the caller reports as unknown rather than as free.
    """
    from research_engine import catalog
    from research_engine.llm_factory import model_name_for

    spec = catalog.get(model_name_for("critic"))
    if spec is None or not spec.priced:
        return 0.0
    calls = sentences + 2 * max(1, -(-sentences // BATCH))
    tokens_in, tokens_out = 900, 200
    return calls * (tokens_in * spec.input_per_mtok + tokens_out * spec.output_per_mtok) / 1e6


async def _decompose(todo: list[tuple[Unit, str]], result: Validation, budget: Budget) -> None:
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        human = "\n\n".join(f"Sentence {i}: {s}" for i, (_, s) in enumerate(batch, start=1))
        cause = None
        parsed = None
        try:
            parsed = _json_array(
                await call_model("critic.claim_decompose", human, budget=budget, result=result)
            )
        except ValueError, json.JSONDecodeError:
            cause = "malformed_response"
        except Exception as exc:  # noqa: BLE001 — every failure becomes a named cause
            cause = unmeasured_cause(exc)
        by_sentence: dict[int, list] = {}
        if parsed is not None:
            for item in parsed if isinstance(parsed, list) else []:
                if isinstance(item, dict) and isinstance(item.get("sentence"), int):
                    by_sentence[item["sentence"]] = item.get("claims")
        for i, (unit, sentence) in enumerate(batch, start=1):
            if cause is not None:
                result.claims.append(_undecided(unit, sentence, cause))
                continue
            checked = check_decomposition(sentence, by_sentence.get(i))
            if checked is None:
                result.claims.append(_undecided(unit, sentence, "decomposition_invalid"))
                continue
            for claim in checked:
                claim.unit = unit.index
                result.claims.append(claim)


def _undecided(unit: Unit, sentence: str, cause: str) -> Claim:
    return Claim(
        unit=unit.index,
        sentence=sentence,
        text=sentence,
        span=(0, len(sentence)),
        cites=markers_in(sentence),
        state=UNMEASURED,
        cause=cause,
    )


def _check_citations(pending: list[Claim], evidence: dict[int, Evidence]) -> None:
    """Structural citation validation, before any model is asked anything (§9.3)."""
    for claim in pending:
        for n in claim.cites:
            ev = evidence.get(n)
            (claim.valid_cites if ev is not None and ev.admissible else claim.invalid_cites).append(
                n
            )
        if not claim.valid_cites:
            claim.state, claim.cause = NOT_SUPPORTED, "uncited"


def _snippets(claim: Claim, evidence: dict[int, Evidence], cites: list[int] | None = None) -> str:
    return "\n".join(
        f"- {s}"
        for n in (cites if cites is not None else claim.valid_cites)
        for s in evidence[n].snippets
    )


def _check_quantities(pending: list[Claim], evidence: dict[int, Evidence]) -> None:
    for claim in pending:
        if claim.state != UNMEASURED or claim.cause is not None:
            continue
        snippets = _snippets(claim, evidence)
        # Citation markers are not quantities the claim states: `[1]` is not the number 1.
        missing = quantities.unsupported(_MARKER_RE.sub(" ", claim.text), snippets)
        calc = claim.calculation
        if (
            missing
            and calc
            and quantities.calculation_holds(
                str(calc.get("op")),
                [str(v) for v in calc.get("operands") or []],
                str(calc.get("result")),
                snippets,
            )
        ):
            # The stated result is accounted for by a recomputed calculation, and its
            # operands were checked inside it; only the result itself may be absent.
            result_values = {str(v) for v in [calc.get("result")]}
            missing = [m for m in missing if not any(m in r or r in m for r in result_values)]
        if missing:
            claim.state, claim.cause = NOT_SUPPORTED, "number_not_in_snippet"


async def _verify(
    pending: list[Claim],
    evidence: dict[int, Evidence],
    result: Validation,
    budget: Budget,
    *,
    purpose: str,
) -> None:
    for start in range(0, len(pending), BATCH):
        batch = pending[start : start + BATCH]
        human = "\n\n".join(
            f"Claim {i}: {c.text}\nEvidence {i}:\n{_snippets(c, evidence)}"
            for i, c in enumerate(batch, start=1)
        )
        try:
            verdicts = parse_verdicts(
                await call_model(purpose, human, budget=budget, result=result), len(batch)
            )
        except Exception as exc:  # noqa: BLE001
            cause = unmeasured_cause(exc)
            for c in batch:
                c.state, c.cause = UNMEASURED, cause
            continue
        for c, verdict in zip(batch, verdicts, strict=True):
            if verdict is None:
                c.state, c.cause = UNMEASURED, "malformed_response"
            elif verdict == "supported":
                c.state, c.cause = SUPPORTED, None
            elif verdict == "contradicted":
                c.state, c.cause = CONTRADICTED, "contradicted"
            else:
                c.state, c.cause = NOT_SUPPORTED, "not_supported"


async def _relevance(
    claims_: list[Claim], evidence: dict[int, Evidence], result: Validation, budget: Budget
) -> None:
    """Each citation of a supported claim, judged alone: does it support any part of it?

    A citation that supports nothing is removed from the claim and counted, even when the
    others carry it (§9.3). A relevant document that does not state the claim is caught here.
    """
    pairs = [(c, n) for c in claims_ if c.state == SUPPORTED for n in c.valid_cites]
    for start in range(0, len(pairs), BATCH):
        batch = pairs[start : start + BATCH]
        human = "\n\n".join(
            f"Pair {i}: Claim: {c.text}\nSnippet:\n{_snippets(c, evidence, [n])}"
            for i, (c, n) in enumerate(batch, start=1)
        )
        try:
            answers = parse_pairs(
                await call_model("critic.citation_relevance", human, budget=budget, result=result),
                len(batch),
            )
        except Exception as exc:  # noqa: BLE001
            cause = unmeasured_cause(exc)
            for c, _ in batch:
                c.state, c.cause = UNMEASURED, cause
            continue
        for (c, n), answer in zip(batch, answers, strict=True):
            if answer is None:
                c.state, c.cause = UNMEASURED, "malformed_response"
            elif answer is False and n not in c.non_supporting_cites:
                c.non_supporting_cites.append(n)
    for c in claims_:
        if c.state == SUPPORTED and set(c.non_supporting_cites) >= set(c.valid_cites):
            # Every citation it named supports nothing on its own: the verdict that combined
            # them cannot stand on citations each of which is irrelevant.
            c.state, c.cause = NOT_SUPPORTED, "not_supported"


async def _verify_inference(
    conclusions: list[Claim],
    supported: list[Claim],
    evidence: dict[int, Evidence],
    result: Validation,
    budget: Budget,
) -> None:
    """A conclusion claim is checked against the supported findings, not only snippets."""
    if not conclusions:
        return
    findings = "\n".join(f"- {c.text}" for c in supported) or "- (no supported findings)"
    for start in range(0, len(conclusions), BATCH):
        batch = conclusions[start : start + BATCH]
        human = "\n\n".join(
            f"Claim {i}: {c.text}\nFindings:\n{findings}\nSnippets:\n{_snippets(c, evidence)}"
            for i, c in enumerate(batch, start=1)
        )
        try:
            verdicts = parse_verdicts(
                await call_model("critic.inference_verify", human, budget=budget, result=result),
                len(batch),
            )
        except Exception as exc:  # noqa: BLE001
            cause = unmeasured_cause(exc)
            for c in batch:
                c.state, c.cause = UNMEASURED, cause
            continue
        for c, verdict in zip(batch, verdicts, strict=True):
            if verdict is None:
                c.state, c.cause = UNMEASURED, "malformed_response"
            elif verdict == "supported":
                c.state, c.cause = SUPPORTED, None
            else:
                c.state, c.cause = NOT_SUPPORTED, "inference_rejected"
