"""
The mechanical quantity check (internal/rfcs/V3.1-corpus-scope.md §9.3, AC-39).

Table-driven in both directions: every rule is pinned by a pair it must accept *and* a pair
it must refuse. A rule tested only on what it accepts is how an equivalence that is usually
right becomes one that waves an invented figure through.
"""

from __future__ import annotations

import pytest

from research_engine.quantities import calculation_holds, extract, unsupported

ACCEPTED = [
    ("1,000 participants", "There were 1000 participants."),
    ("1000 participants", "There were 1,000 participants."),
    ("1 000 participants", "There were 1000 participants."),
    ("2.3 million users", "The service had 2,300,000 users."),
    ("2,300,000 users", "The service had 2.3 million users."),
    ("4k samples", "We drew 4,000 samples."),
    ("12% of respondents", "12 percent of respondents agreed."),
    ("12 per cent", "about 12% of them"),
    ("about 12% of respondents", "12.4% of respondents agreed."),
    ("5 km", "a distance of 5000 m"),
    ("250 g", "0.25 kg of sample"),
    ("90 minutes", "a 90 min session"),
    ("in March 2021", "on 14 March 2021 the trial began"),
    ("on 2021-03-14", "on 14 March 2021 the trial began"),
    ("on March 14, 2021", "on 2021-03-14 the trial began"),
    ("in 2021", "on 14 March 2021 the trial began"),
    ("on 03/04/2021", "dated 03/04/2021"),
    ("$40 per unit", "priced at 40 USD each"),
]

REFUSED = [
    ("1,5 litres", "1.5 litres"),  # a comma before one digit is not a thousands group
    ("13% of respondents", "12.4% of respondents agreed."),
    ("12.40% of respondents", "12.4% of respondents agreed."),  # invented precision
    ("12% of respondents", "a ratio of 0.12"),  # ratio and percent are not equated
    ("5 km", "5 kg"),  # across dimensions never matches
    ("5 m", "5 million"),  # bare m is metres, never million
    ("on 04/03/2021", "dated 03/04/2021"),  # ambiguous numeric dates compare literally
    ("in April 2021", "on 14 March 2021"),
    ("in 2022", "on 14 March 2021"),
    ("7 participants", "There were 1000 participants."),
    ("$40 per unit", "priced at 40 EUR each"),
]


@pytest.mark.parametrize(("claim", "snippet"), ACCEPTED)
def test_equivalent_representations_are_accepted(claim, snippet):
    assert unsupported(claim, snippet) == [], (claim, snippet, extract(claim), extract(snippet))


@pytest.mark.parametrize(("claim", "snippet"), REFUSED)
def test_different_values_are_refused(claim, snippet):
    assert unsupported(claim, snippet), (claim, snippet, extract(claim), extract(snippet))


def test_a_claim_with_no_quantity_is_left_to_the_model():
    assert unsupported("Silicon cells release electrons.", "nothing numeric here") == []


def test_a_stated_calculation_is_recomputed():
    snippets = "Enrolment was 1,200 in 2020 and 1,500 in 2021."
    assert calculation_holds("subtract", ["1,500", "1,200"], "300", snippets)
    assert calculation_holds("percent_change", ["1,200", "1,500"], "25%", snippets)
    assert not calculation_holds("subtract", ["1,500", "1,200"], "350", snippets)
    # An operand that is not in the evidence sinks the whole calculation.
    assert not calculation_holds("subtract", ["1,600", "1,200"], "400", snippets)
    assert not calculation_holds("cube_root", ["1,500", "1,200"], "300", snippets)


def test_a_computed_value_with_no_stated_calculation_is_not_in_the_snippets():
    """The difference 300 appears in neither snippet, so without a stated calculation the
    mechanical check refuses it — the decomposition must say how it was derived."""
    assert unsupported("Enrolment rose by 300.", "Enrolment was 1,200 in 2020 and 1,500 in 2021.")
