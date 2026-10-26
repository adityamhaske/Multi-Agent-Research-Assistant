"""
Corpus-only mode is described by what the code enforces, and nothing more.

What it enforces: evidence comes only from the installed corpus, web search is off,
`read_webpage` refuses every non-corpus URL, and the corpus store refuses an embedder that
is not local (`corpus.py::_require_local_embedder_in_corpus_mode`). What it does not: where
the agents' model calls go. The question and the retrieved excerpts reach whichever
provider each role is routed to, and nothing in corpus mode checks that it is local.

A local *indexing* model is part of that and is not the whole of it. The planner, executor,
critic and synthesizer can each be remote, and when they are, the question and the excerpts
leave the machine whatever embedded the corpus — so copy that equates local indexing with
running offline is the same overclaim in other words, and is caught here too.

The product said otherwise on eight surfaces for several releases — the comparison table
promised it with a "guaranteed", the docs said a run reached nothing at all — because
`test_corpus_egress.py` runs with scripted models, and so proves the retrieval half only.
This test fails if that kind of absolute claim comes back on any published or user-facing
surface.

The phrasings are assembled from fragments rather than written out, so this file does not
contain the sentences it forbids (root AGENTS.md: a guard cannot tell a use from a mention).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_NET = r"network\s+calls?"
_INDEX = r"(?:embedd(?:er|ings?|ing\s+models?)|index(?:ing|er)(?:\s+models?)?)"
_OFFLINE = (
    r"\b(?:(?:completely|fully|entirely)\s+offline|offline\s+execution|air-?gapped"
    r"|(?:zero|no)\s+egress)"
)
_CLAIMS = (
    # "... does / makes no (or zero) network calls"
    rf"\b(?:makes?|making|made)\s+(?:no|zero)\s+{_NET}",
    # "no network calls at all", "... of any kind"
    rf"\bno\s+{_NET}\s+(?:at\s+all|of\s+any\s+kind)",
    # the comparison table's old row
    rf"\bzero\s+{_NET}\s*,?\s+guaranteed",
    rf"\bguarantee[sd]?\s+(?:zero|no)\s+{_NET}",
    # "research over your documents with zero network calls"
    rf"\bwith\s+(?:no|zero)\s+(?:outbound\s+)?{_NET}",
    # "nothing leaves the machine", "never leaves your computer"
    r"\b(?:nothing|never)\s+leaves?\s+(?:the|your)\s+(?:machine|computer)",
    # Local indexing presented as making the run offline, in either order:
    # "local embeddings ... zero egress", "completely offline with ... local embeddings",
    # an "Offline Execution" label beside "Local Embeddings".
    rf"\blocal\s+(?:document\s+)?{_INDEX}[^.]{{0,160}}?{_OFFLINE}",
    rf"{_OFFLINE}[^.]{{0,160}}?\blocal\s+(?:document\s+)?{_INDEX}",
    # "a local embedder makes the run offline" — but not "does not make the run offline".
    r"(?<!not )\bmakes?\s+(?:the\s+|a\s+)?(?:run|research)\s+offline",
)
CLAIM = re.compile("|".join(f"(?:{c})" for c in _CLAIMS), re.IGNORECASE)

# Everything a user or a reader of the public site sees, plus the engine and server code
# whose docstrings and error messages the docs are written from.
_SURFACES = (
    ("README.md", ("",)),
    ("docs", (".md",)),
    ("frontend/app", (".ts", ".tsx")),
    ("frontend/components", (".ts", ".tsx")),
    ("frontend/lib", (".ts", ".tsx")),
    ("frontend/hooks", (".ts", ".tsx")),
    ("backend/app", (".py",)),
    ("backend/research_engine", (".py",)),
    ("backend/desktop", (".py",)),
)


def _files() -> list[Path]:
    found: list[Path] = []
    for rel, suffixes in _SURFACES:
        base = ROOT / rel
        if base.is_file():
            found.append(base)
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if ".test." in path.name or "node_modules" in path.parts:
                continue
            found.append(path)
    return found


def _claims_in(text: str) -> list[str]:
    # Joined so a claim wrapped across two lines of Markdown, a docstring or a comment is
    # still seen — with each line's comment marker dropped, or a wrapped "does not / make"
    # would read as an affirmative "# make".
    unwrapped = re.sub(r"(?m)^\s*(?:#|//|\*|-)\s?", "", text)
    flat = re.sub(r"\s+", " ", unwrapped)
    return [m.group(0) for m in CLAIM.finditer(flat)]


def test_the_scan_reaches_every_surface():
    """A guard that scans nothing passes. Each surface must contribute files."""
    files = _files()
    for rel, _ in _SURFACES:
        assert any(ROOT / rel == f or (ROOT / rel) in f.parents for f in files), rel


def test_the_patterns_catch_each_shape_of_the_old_claim():
    """Negative controls, built from fragments for the reason the module docstring gives."""
    net = "network " + "calls"
    planted = [
        f"so the run makes no {net} at all",
        f"Zero {net}, guaranteed",
        f"Corpus-only mode guarantees zero {net}",
        f"research over your own documents with zero {net}",
        f"an airgapped mode with no {net}",
        "and nothing " + "leaves the machine",
        "your manuscript never " + "leaves the machine",
        f"the run makes zero\n{net}",
        # local indexing equated with offline — the shapes the old copy used
        "Combined with local embeddings (`nomic-embed-text` through the same Ollama), a fully "
        "local deployment can do private retrieval at zero cost and zero " + "egress.",
        "run completely " + "offline with Ollama local LLMs and local document embeddings.",
        "<td>Offline " + 'Execution</td>\n<td className="py-2 px-4">Ollama / Local Embeddings</td>',
        "a local indexing model makes the run " + "offline",
    ]
    for sentence in planted:
        assert _claims_in(sentence), sentence


def test_true_statements_about_corpus_mode_are_not_flagged():
    """The rewrite's own vocabulary, and honest negations, must stay writable."""
    net = "network " + "calls"
    honest = [
        "Corpus-only mode keeps the evidence local; model calls go to the configured provider.",
        f"It does not promise zero {net}, because the answer is still written by a model.",
        "so neither tool reaches the network",
        "retrieval never leaves the host",
        "the key itself never leaves the OS keychain",
        "A local indexing model does not make the run offline.",
        "Web search is off, and indexing requires a local model.",
        "Local corpus; research models local only if you choose Ollama",
        "Verify any exported report completely offline with the standalone verifier.",
    ]
    for sentence in honest:
        assert not _claims_in(sentence), sentence


def test_no_surface_claims_corpus_mode_stops_every_network_call():
    offenders = [
        f"{path.relative_to(ROOT)}: {claim!r}"
        for path in _files()
        for claim in _claims_in(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == [], (
        "Corpus-only mode keeps retrieval local; it does not stop model calls from leaving "
        "the machine. Say what the code enforces:\n  " + "\n  ".join(offenders)
    )
