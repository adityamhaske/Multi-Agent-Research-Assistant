"""
Report outline templates (docs/07 §2, Phase 4).

The four structures a researcher picks between at the design gate, held as **data** so
there is exactly one copy of them. The alternative — a picker in the browser that knows
the section list, and a prompt on the server that also knows it — is the shape of every
drift bug catalogued in AGENTS.md, and here it would be silent: the UI would promise a
structure the synthesizer never received.

So the flow is: the picker asks the API for this catalog, sends back only a template
*id*, `RunConfig.outline_template` carries that id, and `planner_node` resolves it into
the `proposed_outline` the reviewer then edits. What the synthesizer is finally handed is
the reviewer's edited list, not the template — the template is only the starting point.

`custom` is deliberately empty: it means "I will author the sections myself at the gate",
which is a different thing from "no outline" (that is `outline_template=None`, today's
unconstrained synthesizer).
"""

from __future__ import annotations

#: template id → ordered sections. Titles become the report's `##` headings, and the
#: description is guidance for the synthesizer rather than text that appears verbatim.
TEMPLATES: dict[str, dict] = {
    "literature_review": {
        "label": "Literature Review",
        "summary": "Background, how the field studies it, what is known, what is missing.",
        "sections": [
            {"title": "Background", "description": "The problem and why it is studied."},
            {"title": "Methods", "description": "How the literature investigates it."},
            {"title": "Findings", "description": "What the sources establish, with weight."},
            {"title": "Gaps", "description": "Open questions and thin evidence."},
        ],
    },
    "systematic_comparison": {
        "label": "Systematic Comparison",
        "summary": "Compare named alternatives against shared criteria, then conclude.",
        "sections": [
            {"title": "Criteria", "description": "The dimensions being compared."},
            {"title": "Alternatives", "description": "Each option described on its own terms."},
            {"title": "Comparison", "description": "Alternatives against criteria, side by side."},
            {"title": "Trade-offs", "description": "What each choice costs."},
        ],
    },
    "methods_survey": {
        "label": "Methods Survey",
        "summary": "Survey the techniques in an area and how they are evaluated.",
        "sections": [
            {"title": "Scope", "description": "Which techniques are in and out of scope."},
            {"title": "Techniques", "description": "Each method and its mechanism."},
            {"title": "Evaluation", "description": "How the literature measures them."},
            {"title": "Limitations", "description": "Where the methods break down."},
        ],
    },
    "custom": {
        "label": "Custom",
        "summary": "Start from an empty outline and write your own sections at the gate.",
        "sections": [],
    },
}


def sections_for(template_id: str | None) -> list[dict]:
    """The sections a template id resolves to. Unknown or absent → no sections.

    Never raises: this reads a value that arrives from a request, and a typo'd template
    must degrade to today's unconstrained report rather than fail a run that has already
    been paid for. The reviewer sees the empty outline at the gate either way, so the
    mistake is visible before anything is spent.
    """
    template = TEMPLATES.get(template_id or "")
    return [dict(s) for s in template["sections"]] if template else []


def catalog() -> list[dict]:
    """The picker's payload: id, label, one-line summary, and the sections themselves."""
    return [
        {
            "id": template_id,
            "label": entry["label"],
            "summary": entry["summary"],
            "sections": [dict(s) for s in entry["sections"]],
        }
        for template_id, entry in TEMPLATES.items()
    ]
