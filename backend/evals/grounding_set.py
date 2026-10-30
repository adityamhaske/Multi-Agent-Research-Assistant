"""Build the G-6 grounding benchmark set (internal/rfcs/V3.1-corpus-scope.md §17, D-23).

The set is atomic claims, each to be labelled `supported`, `not_supported` or `contradicted`
by a person, against the snippets it cites. What makes it a test of the shipped checker
rather than of clean prose:
- **Real extracted text.** 64 facts are written into 16 documents, one per shipped format
  (Tier A, B and C, plus PDF, HTML, Markdown and text). Every snippet is a line the shipped
  extractor produced from those files, so a spreadsheet's snippet is its linearised row and
  a slide's is its slide text, never the sentence the fact started as.
- **Hard negatives,** most of the set. Each fact yields its supported paraphrases (and, where
  the source allows, a rounded figure, a stated cause, a computed value or a unit
  conversion), plus four of the §17 traps:
  - a wrong number;
  - the right number about the wrong subject;
  - the opposite direction;
  - the wrong period;
  - a compound with one invented clause;
  - an inference the snippet does not state;
  - a fact smuggled into a parenthetical;
  - a wrong computation.

  Pairs of facts add the citation cases: two sources needed together; one of two
  enough; a relevant citation that does not support.
- **Blind.** `items.json` is all the labelling page reads. What each item was written to be
  (`authoring.json`) is kept apart and never shown to the labeller, so their label is
  theirs.

    python -m evals.grounding_set     # writes evals/datasets/grounding/v1/

The writers it uses (python-docx, xlsxwriter, xlwt, python-pptx, odfpy) are imported only
here and are not runtime dependencies. The committed documents are what the benchmark and
its tests read.
"""

from __future__ import annotations

import io
import json
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path

from research_engine.documents import extract

OUT = Path(__file__).resolve().parent / "datasets" / "grounding" / "v1"
SEED = 3100


@dataclass(frozen=True)
class Fact:
    doc: str
    #: The fact as the document states it.
    source: str
    #: The claim frame: {S} subject, {V} verb, {X} value, {P} period.
    frame: str
    S: str
    alt_S: str
    V: str
    X: str
    wrong_X: str
    P: str
    alt_P: str
    opp_V: str | None = None
    rounded: str | None = None
    cause: str | None = None
    wrong_cause: str = "a change in how it was counted"
    extra_ok: str | None = None
    extra_bad: str | None = None

    def claim(self, **swap) -> str:
        fields = {"S": self.S, "V": self.V, "X": self.X, "P": self.P, **swap}
        text = self.frame.format(**fields)
        return text[0].upper() + text[1:] + "."


def F(doc, source, frame, S, alt_S, V, X, wrong_X, P, alt_P, **kw) -> Fact:
    return Fact(doc, source, frame, S, alt_S, V, X, wrong_X, P, alt_P, **kw)


# ── The facts, four per document ─────────────────────────────────────────────────

FACTS: list[Fact] = [
    # district-report.docx — schools
    F(
        "district-report.docx",
        "Enrolment in the North district rose 12.4% in 2021, from 1,104 to 1,241 pupils.",
        "enrolment in {S} {V} by {X} in {P}",
        "the North district",
        "the South district",
        "rose",
        "12.4%",
        "21.4%",
        "2021",
        "2019",
        opp_V="fell",
        rounded="about 12%",
        extra_ok="Enrolment in the North district rose by 137 pupils in 2021",
        extra_bad="Enrolment in the North district rose by 173 pupils in 2021",
    ),
    F(
        "district-report.docx",
        "Attendance in the South district fell to 91.8% in 2022, after a flu outbreak in February.",
        "attendance in {S} {V} {X} in {P}",
        "the South district",
        "the East district",
        "fell to",
        "91.8%",
        "89.1%",
        "2022",
        "2020",
        opp_V="rose to",
        rounded="roughly 92%",
        cause="a flu outbreak in February",
        wrong_cause="a teachers' strike",
    ),
    F(
        "district-report.docx",
        "The East district hired 38 new teachers in 2023, 22 of them in mathematics and science.",
        "{S} {V} {X} new teachers in {P}",
        "the East district",
        "the West district",
        "hired",
        "38",
        "83",
        "2023",
        "2021",
        extra_ok="The East district hired 16 new teachers outside mathematics and science in 2023",
        extra_bad="The East district hired 26 new teachers outside mathematics and science in 2023",
    ),
    F(
        "district-report.docx",
        "Average class size in the West district was 27 pupils in 2022.",
        "average class size in {S} {V} {X} pupils in {P}",
        "the West district",
        "the North district",
        "was",
        "27",
        "31",
        "2022",
        "2018",
    ),
    # clinic-review.odt — health
    F(
        "clinic-review.odt",
        "The Riverside clinic saw 18,240 patients in 2023, up 9% on the year before.",
        "{S} {V} {X} patients in {P}",
        "the Riverside clinic",
        "the Hillcrest clinic",
        "saw",
        "18,240",
        "12,840",
        "2023",
        "2021",
        rounded="about 18,000",
        extra_ok="The Riverside clinic's patient numbers rose 9% in 2023",
        extra_bad="The Riverside clinic's patient numbers rose 19% in 2023",
    ),
    F(
        "clinic-review.odt",
        "Median waiting time at the Hillcrest clinic fell from 34 to 21 minutes in 2023 after a second triage nurse was hired.",
        "median waiting time at {S} {V} {X} minutes in {P}",
        "the Hillcrest clinic",
        "the Riverside clinic",
        "fell to",
        "21",
        "12",
        "2023",
        "2022",
        opp_V="rose to",
        cause="a second triage nurse was hired",
        wrong_cause="the clinic moved to a larger building",
        extra_ok="Median waiting time at the Hillcrest clinic fell by 13 minutes in 2023",
        extra_bad="Median waiting time at the Hillcrest clinic fell by 15 minutes in 2023",
    ),
    F(
        "clinic-review.odt",
        "The county's two clinics gave 6,450 flu vaccinations in the 2023 season.",
        "{S} {V} {X} flu vaccinations in {P}",
        "the county's two clinics",
        "the county hospital",
        "gave",
        "6,450",
        "4,650",
        "the 2023 season",
        "the 2021 season",
        rounded="about 6,500",
    ),
    F(
        "clinic-review.odt",
        "Missed appointments at the Riverside clinic dropped to 7.5% in 2023 once text reminders began.",
        "missed appointments at {S} {V} {X} in {P}",
        "the Riverside clinic",
        "the Hillcrest clinic",
        "dropped to",
        "7.5%",
        "5.7%",
        "2023",
        "2020",
        opp_V="climbed to",
        rounded="under 8%",
        cause="text reminders began",
        wrong_cause="opening hours were extended",
    ),
    # transit-memo.rtf — transport
    F(
        "transit-memo.rtf",
        "Ridership on Route 7 grew 15% in 2022 after the service ran every ten minutes.",
        "ridership on {S} {V} {X} in {P}",
        "Route 7",
        "Route 12",
        "grew",
        "15%",
        "51%",
        "2022",
        "2019",
        opp_V="shrank",
        cause="the service ran every ten minutes",
        wrong_cause="fares were cut",
    ),
    F(
        "transit-memo.rtf",
        "The city's bus fleet covered 4.2 million kilometres in 2022.",
        "{S} {V} {X} kilometres in {P}",
        "the city's bus fleet",
        "the city's tram fleet",
        "covered",
        "4.2 million",
        "2.4 million",
        "2022",
        "2020",
        extra_ok="The city's bus fleet covered 4,200,000 kilometres in 2022",
        extra_bad="The city's bus fleet covered 420,000 kilometres in 2022",
    ),
    F(
        "transit-memo.rtf",
        "On-time performance on Route 12 was 81% in 2022.",
        "on-time performance on {S} {V} {X} in {P}",
        "Route 12",
        "Route 7",
        "was",
        "81%",
        "18%",
        "2022",
        "2021",
        rounded="about four in five",
    ),
    F(
        "transit-memo.rtf",
        "Average fare revenue per trip fell to 1.15 dollars in 2022.",
        "average fare revenue per trip {V} {X} dollars in {P}",
        "the network",
        "Route 7",
        "fell to",
        "1.15",
        "1.51",
        "2022",
        "2021",
        opp_V="rose to",
    ),
    # water-history.epub — utility
    F(
        "water-history.epub",
        "The Eastbrook reservoir was completed in 1958 with a capacity of 42 million cubic metres.",
        "{S} {V} a capacity of {X} million cubic metres when it was completed in {P}",
        "the Eastbrook reservoir",
        "the Millford reservoir",
        "had",
        "42",
        "24",
        "1958",
        "1985",
    ),
    F(
        "water-history.epub",
        "Leakage across the network fell from 23% to 14% between 2010 and 2020 after old iron mains were replaced.",
        "leakage across {S} {V} {X} between {P}",
        "the network",
        "the treatment works",
        "fell to",
        "14%",
        "4%",
        "2010 and 2020",
        "2000 and 2010",
        opp_V="rose to",
        cause="old iron mains were replaced",
        wrong_cause="water pressure was raised",
        extra_ok="Leakage across the network fell by 9 percentage points between 2010 and 2020",
        extra_bad="Leakage across the network fell by 11 percentage points between 2010 and 2020",
    ),
    F(
        "water-history.epub",
        "Average household use was 142 litres per person per day in 2020.",
        "average household use {V} {X} litres per person per day in {P}",
        "households",
        "businesses",
        "was",
        "142",
        "124",
        "2020",
        "2010",
        rounded="about 140",
    ),
    F(
        "water-history.epub",
        "The Millford treatment works was expanded in 1994 to serve 310,000 people.",
        "{S} {V} expanded in {P} to serve {X} people",
        "the Millford treatment works",
        "the Eastbrook works",
        "was",
        "310,000",
        "130,000",
        "1994",
        "1984",
        rounded="about 300,000",
    ),
    # wind-farm.pdf — energy (one fact per page line)
    F(
        "wind-farm.pdf",
        "The Hollow Ridge wind farm generated 412 gigawatt hours in 2022",
        "{S} {V} {X} gigawatt hours in {P}",
        "the Hollow Ridge wind farm",
        "the Coast Point wind farm",
        "generated",
        "412",
        "214",
        "2022",
        "2020",
        rounded="just over 400",
        extra_ok="The Hollow Ridge wind farm generated 412,000 megawatt hours in 2022",
        extra_bad="The Hollow Ridge wind farm generated 41,200 megawatt hours in 2022",
    ),
    F(
        "wind-farm.pdf",
        "Its capacity factor was 34 percent in 2022 because of a windy winter",
        "the capacity factor of {S} {V} {X} percent in {P}",
        "the Hollow Ridge wind farm",
        "the Coast Point wind farm",
        "was",
        "34",
        "43",
        "2022",
        "2021",
        cause="a windy winter",
        wrong_cause="new turbine blades",
    ),
    F(
        "wind-farm.pdf",
        "The Coast Point wind farm has 48 turbines of 3.6 megawatts each",
        "{S} {V} {X} turbines of 3.6 megawatts each in {P}",
        "the Coast Point wind farm",
        "the Hollow Ridge wind farm",
        "has",
        "48",
        "84",
        "its current layout",
        "its first phase",
        extra_ok="The Coast Point wind farm has 172.8 megawatts of turbines",
        extra_bad="The Coast Point wind farm has 182.8 megawatts of turbines",
    ),
    F(
        "wind-farm.pdf",
        "Curtailment at Coast Point rose to 6 percent in 2022 when the grid link was congested",
        "curtailment at {S} {V} {X} percent in {P}",
        "Coast Point",
        "Hollow Ridge",
        "rose to",
        "6",
        "16",
        "2022",
        "2020",
        opp_V="fell to",
        cause="the grid link was congested",
        wrong_cause="turbines were taken offline for repairs",
    ),
    # library-report.html
    F(
        "library-report.html",
        "Loans at the Central Library rose 8% in 2023, to 214,000 items.",
        "loans at {S} {V} {X} in {P}",
        "the Central Library",
        "the Harbour branch",
        "rose",
        "8%",
        "18%",
        "2023",
        "2021",
        opp_V="fell",
        rounded="under 10%",
    ),
    F(
        "library-report.html",
        "The Harbour branch reopened in March 2023 after an 11-month refurbishment.",
        "{S} {V} after a {X}-month refurbishment in {P}",
        "the Harbour branch",
        "the Central Library",
        "reopened",
        "11",
        "7",
        "March 2023",
        "March 2022",
    ),
    F(
        "library-report.html",
        "E-book loans across the service reached 96,500 in 2023.",
        "e-book loans across {S} {V} {X} in {P}",
        "the service",
        "the Harbour branch",
        "reached",
        "96,500",
        "69,500",
        "2023",
        "2020",
        rounded="nearly 100,000",
    ),
    F(
        "library-report.html",
        "Free computer sessions at the Central Library fell 12% in 2023 as more visitors brought laptops.",
        "free computer sessions at {S} {V} {X} in {P}",
        "the Central Library",
        "the Harbour branch",
        "fell",
        "12%",
        "21%",
        "2023",
        "2021",
        opp_V="rose",
        cause="more visitors brought laptops",
        wrong_cause="opening hours were cut",
    ),
    # lab-notes.md
    F(
        "lab-notes.md",
        "In run one the phosphate buffer drifted by 0.08 pH units over fourteen days at room temperature.",
        "in run one {S} {V} {X} pH units over {P}",
        "the phosphate buffer",
        "the citrate buffer",
        "drifted by",
        "0.08",
        "0.8",
        "fourteen days",
        "seven days",
    ),
    F(
        "lab-notes.md",
        "In run two, at 37 degrees, the phosphate buffer drifted by 0.21 pH units.",
        "in run two, at 37 degrees, {S} {V} {X} pH units",
        "the phosphate buffer",
        "the Tris buffer",
        "drifted by",
        "0.21",
        "0.12",
        "",
        "",
        extra_ok="The phosphate buffer drifted 0.13 pH units more in run two than in run one",
        extra_bad="The phosphate buffer drifted 0.31 pH units more in run two than in run one",
    ),
    F(
        "lab-notes.md",
        "The pH meter's slope stayed between 98 and 101 percent across all calibrations this month.",
        "{S}'s slope {V} between {X} percent across all calibrations in {P}",
        "the pH meter",
        "the conductivity meter",
        "stayed",
        "98 and 101",
        "95 and 99",
        "this month",
        "last month",
    ),
    F(
        "lab-notes.md",
        "Twelve bottles were set aside as controls and kept at four degrees.",
        "{S} {V} {X} control bottles at four degrees in {P}",
        "the study",
        "the pilot study",
        "kept",
        "twelve",
        "twenty",
        "this study",
        "the pilot",
    ),
    # food-bank.txt
    F(
        "food-bank.txt",
        "The Northside food bank served 3,120 households in the winter of 2023, a rise of 22% after heating costs climbed.",
        "{S} {V} {X} households in {P}",
        "the Northside food bank",
        "the Southside food bank",
        "served",
        "3,120",
        "2,130",
        "the winter of 2023",
        "the winter of 2021",
        rounded="about 3,100",
        cause="heating costs climbed",
        wrong_cause="a new school opened nearby",
    ),
    F(
        "food-bank.txt",
        "Volunteers gave 14,800 hours in 2023.",
        "{S} {V} {X} hours in {P}",
        "volunteers",
        "paid staff",
        "gave",
        "14,800",
        "18,400",
        "2023",
        "2021",
        rounded="nearly 15,000",
    ),
    F(
        "food-bank.txt",
        "Fresh produce made up 31% of donations in 2023, up from 19% in 2021.",
        "fresh produce {V} {X} of {S} in {P}",
        "donations",
        "purchases",
        "made up",
        "31%",
        "13%",
        "2023",
        "2020",
        extra_ok="Fresh produce's share of donations rose 12 percentage points between 2021 and 2023",
        extra_bad="Fresh produce's share of donations rose 21 percentage points between 2021 and 2023",
    ),
    F(
        "food-bank.txt",
        "The Southside food bank opened a second site in September 2023.",
        "{S} {V} a {X} site in {P}",
        "the Southside food bank",
        "the Northside food bank",
        "opened",
        "second",
        "third",
        "September 2023",
        "September 2022",
    ),
    # admissions.pptx
    F(
        "admissions.pptx",
        "Applications to the engineering faculty rose 17% for the 2024 intake",
        "applications to {S} {V} {X} for {P}",
        "the engineering faculty",
        "the law faculty",
        "rose",
        "17%",
        "7%",
        "the 2024 intake",
        "the 2022 intake",
        opp_V="fell",
        rounded="about a sixth",
    ),
    F(
        "admissions.pptx",
        "The offer rate for international applicants was 38% in 2024",
        "the offer rate for {S} {V} {X} in {P}",
        "international applicants",
        "home applicants",
        "was",
        "38%",
        "83%",
        "2024",
        "2023",
    ),
    F(
        "admissions.pptx",
        "First-year retention reached 92% in 2023 after a mentoring scheme started",
        "first-year retention among {S} {V} {X} in {P}",
        "students",
        "staff",
        "reached",
        "92%",
        "82%",
        "2023",
        "2021",
        cause="a mentoring scheme started",
        wrong_cause="tuition fees were lowered",
    ),
    F(
        "admissions.pptx",
        "Applications to the law faculty fell 4% for the 2024 intake",
        "applications to {S} {V} {X} for {P}",
        "the law faculty",
        "the engineering faculty",
        "fell",
        "4%",
        "14%",
        "the 2024 intake",
        "the 2023 intake",
        opp_V="rose",
    ),
    # crop-trial.tex
    F(
        "crop-trial.tex",
        "Wheat on the irrigated plots yielded 7.9 tonnes per hectare in 2022.",
        "wheat on {S} {V} {X} tonnes per hectare in {P}",
        "the irrigated plots",
        "the rain-fed plots",
        "yielded",
        "7.9",
        "9.7",
        "2022",
        "2021",
        rounded="about 8",
        extra_ok="Wheat on the irrigated plots yielded 790 tonnes per square kilometre in 2022",
        extra_bad="Wheat on the irrigated plots yielded 79 tonnes per square kilometre in 2022",
    ),
    F(
        "crop-trial.tex",
        "Wheat on the rain-fed plots yielded 5.2 tonnes per hectare in 2022.",
        "wheat on {S} {V} {X} tonnes per hectare in {P}",
        "the rain-fed plots",
        "the irrigated plots",
        "yielded",
        "5.2",
        "2.5",
        "2022",
        "2020",
        extra_ok="Irrigation added 2.7 tonnes per hectare to wheat yields in 2022",
        extra_bad="Irrigation added 3.7 tonnes per hectare to wheat yields in 2022",
    ),
    F(
        "crop-trial.tex",
        "We sampled 40 fields across three counties.",
        "{S} {V} {X} fields across three counties in {P}",
        "the trial",
        "the follow-up survey",
        "sampled",
        "40",
        "14",
        "its first season",
        "its third season",
    ),
    F(
        "crop-trial.tex",
        "Nitrogen runoff fell 18% on plots with cover crops because roots held the soil over winter.",
        "nitrogen runoff on {S} {V} {X} in {P}",
        "plots with cover crops",
        "plots without cover crops",
        "fell",
        "18%",
        "8%",
        "the trial",
        "the pilot",
        opp_V="rose",
        cause="roots held the soil over winter",
        wrong_cause="less fertiliser was applied",
    ),
    # air-quality.ipynb
    F(
        "air-quality.ipynb",
        "Mean NO2 at the Market Street monitor was 38 micrograms per cubic metre in 2022.",
        "mean NO2 at {S} {V} {X} micrograms per cubic metre in {P}",
        "the Market Street monitor",
        "the Park Lane monitor",
        "was",
        "38",
        "28",
        "2022",
        "2019",
    ),
    F(
        "air-quality.ipynb",
        "Mean NO2 at the Park Lane monitor fell 21% between 2019 and 2022 after the low-traffic scheme began.",
        "mean NO2 at {S} {V} {X} between {P}",
        "the Park Lane monitor",
        "the Market Street monitor",
        "fell",
        "21%",
        "12%",
        "2019 and 2022",
        "2016 and 2019",
        opp_V="rose",
        cause="the low-traffic scheme began",
        wrong_cause="a factory closed",
    ),
    F(
        "air-quality.ipynb",
        "PM2.5 exceeded the daily limit on 9 days in 2022.",
        "PM2.5 exceeded the daily limit on {X} days at {S} in {P}",
        "the network's monitors",
        "the Park Lane monitor",
        "",
        "9",
        "19",
        "2022",
        "2021",
    ),
    F(
        "air-quality.ipynb",
        "Ozone peaked at 182 micrograms per cubic metre on 19 July 2022.",
        "ozone at {S} {V} {X} micrograms per cubic metre on {P}",
        "the network's monitors",
        "the Market Street monitor",
        "peaked at",
        "182",
        "128",
        "19 July 2022",
        "19 June 2022",
    ),
    # hospital-budget.xlsx — table
    F(
        "hospital-budget.xlsx",
        "Nursing staff costs rose 6.1% in 2024 because of the national pay award",
        "nursing staff costs at {S} {V} {X} in {P}",
        "the hospital",
        "the community trust",
        "rose",
        "6.1%",
        "16.1%",
        "2024",
        "2022",
        opp_V="fell",
        rounded="about 6%",
        cause="the national pay award",
        wrong_cause="more agency nurses were hired",
    ),
    F(
        "hospital-budget.xlsx",
        "Drug spending rose 3.4% in 2024",
        "drug spending at {S} {V} {X} in {P}",
        "the hospital",
        "the community trust",
        "rose",
        "3.4%",
        "4.3%",
        "2024",
        "2023",
        opp_V="fell",
    ),
    F(
        "hospital-budget.xlsx",
        "Energy costs fell 11.2% in 2024 after a new boiler was fitted",
        "energy costs at {S} {V} {X} in {P}",
        "the hospital",
        "the community trust",
        "fell",
        "11.2%",
        "21.2%",
        "2024",
        "2023",
        opp_V="rose",
        rounded="about 11%",
        cause="a new boiler was fitted",
        wrong_cause="wards were closed",
    ),
    F(
        "hospital-budget.xlsx",
        "Catering costs were flat at 0.0% change in 2024",
        "catering costs at {S} {V} {X} in {P}",
        "the hospital",
        "the community trust",
        "changed by",
        "0.0%",
        "2.0%",
        "2024",
        "2022",
    ),
    # road-maintenance.xls — table
    F(
        "road-maintenance.xls",
        "Potholes repaired in Ashby rose 27% in 2023 after the wet winter",
        "potholes repaired in {S} {V} {X} in {P}",
        "Ashby",
        "Barton",
        "rose",
        "27%",
        "72%",
        "2023",
        "2021",
        opp_V="fell",
        cause="the wet winter",
        wrong_cause="a new contractor started",
    ),
    F(
        "road-maintenance.xls",
        "Potholes repaired in Barton fell 8% in 2023",
        "potholes repaired in {S} {V} {X} in {P}",
        "Barton",
        "Ashby",
        "fell",
        "8%",
        "18%",
        "2023",
        "2022",
        opp_V="rose",
    ),
    F(
        "road-maintenance.xls",
        "Resurfacing in Carlow rose 40% in 2023 because a grant funded the ring road",
        "resurfacing in {S} {V} {X} in {P}",
        "Carlow",
        "Ashby",
        "rose",
        "40%",
        "4%",
        "2023",
        "2022",
        opp_V="fell",
        cause="a grant funded the ring road",
        wrong_cause="the depot moved",
    ),
    F(
        "road-maintenance.xls",
        "Gritting runs in Barton fell 15% in 2023 after a mild December",
        "gritting runs in {S} {V} {X} in {P}",
        "Barton",
        "Carlow",
        "fell",
        "15%",
        "51%",
        "2023",
        "2021",
        opp_V="rose",
        cause="a mild December",
        wrong_cause="fewer gritters were available",
    ),
    # museum-visitors.ods — table
    F(
        "museum-visitors.ods",
        "Visitors to the Maritime Museum rose 23% in 2023 because of the shipwreck exhibition",
        "visitors to {S} {V} {X} in {P}",
        "the Maritime Museum",
        "the Science Museum",
        "rose",
        "23%",
        "32%",
        "2023",
        "2021",
        opp_V="fell",
        rounded="nearly a quarter",
        cause="the shipwreck exhibition",
        wrong_cause="free entry on Sundays",
    ),
    F(
        "museum-visitors.ods",
        "Visitors to the Science Museum rose 5% in 2023",
        "visitors to {S} {V} {X} in {P}",
        "the Science Museum",
        "the Art Gallery",
        "rose",
        "5%",
        "15%",
        "2023",
        "2022",
        opp_V="fell",
    ),
    F(
        "museum-visitors.ods",
        "Visitors to the Art Gallery fell 9% in 2023 while the east wing was closed",
        "visitors to {S} {V} {X} in {P}",
        "the Art Gallery",
        "the Maritime Museum",
        "fell",
        "9%",
        "19%",
        "2023",
        "2022",
        opp_V="rose",
        cause="the east wing was closed",
        wrong_cause="ticket prices went up",
    ),
    F(
        "museum-visitors.ods",
        "School visits to the Science Museum rose 31% in 2023 after free coach travel began",
        "school visits to {S} {V} {X} in {P}",
        "the Science Museum",
        "the Art Gallery",
        "rose",
        "31%",
        "13%",
        "2023",
        "2021",
        opp_V="fell",
        rounded="nearly a third",
        cause="free coach travel began",
        wrong_cause="a new café opened",
    ),
    # solar-installs.csv — table
    F(
        "solar-installs.csv",
        "Rooftop solar installations in Dunmore rose 44% in 2023 because of a council grant",
        "rooftop solar installations in {S} {V} {X} in {P}",
        "Dunmore",
        "Elton",
        "rose",
        "44%",
        "14%",
        "2023",
        "2022",
        opp_V="fell",
        cause="a council grant",
        wrong_cause="panel prices doubled",
    ),
    F(
        "solar-installs.csv",
        "Rooftop solar installations in Elton rose 12% in 2023",
        "rooftop solar installations in {S} {V} {X} in {P}",
        "Elton",
        "Dunmore",
        "rose",
        "12%",
        "21%",
        "2023",
        "2021",
        opp_V="fell",
    ),
    F(
        "solar-installs.csv",
        "Rooftop solar installations in Fairley fell 6% in 2023 after the installer closed",
        "rooftop solar installations in {S} {V} {X} in {P}",
        "Fairley",
        "Elton",
        "fell",
        "6%",
        "16%",
        "2023",
        "2022",
        opp_V="rose",
        cause="the installer closed",
        wrong_cause="the grant ended",
    ),
    F(
        "solar-installs.csv",
        "Battery installations in Dunmore rose 61% in 2023",
        "battery installations in {S} {V} {X} in {P}",
        "Dunmore",
        "Fairley",
        "rose",
        "61%",
        "16%",
        "2023",
        "2022",
        opp_V="fell",
        rounded="about 60%",
    ),
    # fish-landings.tsv — table
    F(
        "fish-landings.tsv",
        "Cod landings at Greyhaven fell 18% in 2023 because a quota was cut",
        "cod landings at {S} {V} {X} in {P}",
        "Greyhaven",
        "Holmport",
        "fell",
        "18%",
        "81%",
        "2023",
        "2021",
        opp_V="rose",
        cause="a quota was cut",
        wrong_cause="the harbour was dredged",
    ),
    F(
        "fish-landings.tsv",
        "Mackerel landings at Holmport rose 9% in 2023",
        "mackerel landings at {S} {V} {X} in {P}",
        "Holmport",
        "Greyhaven",
        "rose",
        "9%",
        "19%",
        "2023",
        "2022",
        opp_V="fell",
    ),
    F(
        "fish-landings.tsv",
        "Crab landings at Greyhaven rose 26% in 2023 after new pots were trialled",
        "crab landings at {S} {V} {X} in {P}",
        "Greyhaven",
        "Holmport",
        "rose",
        "26%",
        "62%",
        "2023",
        "2021",
        opp_V="fell",
        rounded="about a quarter",
        cause="new pots were trialled",
        wrong_cause="prices fell",
    ),
    F(
        "fish-landings.tsv",
        "Herring landings at Holmport fell 3% in 2023",
        "herring landings at {S} {V} {X} in {P}",
        "Holmport",
        "Greyhaven",
        "fell",
        "3%",
        "13%",
        "2023",
        "2022",
        opp_V="rose",
    ),
]

TITLES = {
    "district-report.docx": "District annual report",
    "clinic-review.odt": "County clinics: annual review",
    "transit-memo.rtf": "Transit service memo",
    "water-history.epub": "A history of the regional water utility",
    "wind-farm.pdf": "Wind farm performance",
    "library-report.html": "Library service report",
    "lab-notes.md": "Laboratory notebook: buffer stability",
    "food-bank.txt": "Food bank winter update",
    "admissions.pptx": "Admissions briefing",
    "crop-trial.tex": "Irrigation and cover-crop trial",
    "air-quality.ipynb": "Air quality analysis",
    "hospital-budget.xlsx": "Hospital budget",
    "road-maintenance.xls": "Road maintenance",
    "museum-visitors.ods": "Museum visitors",
    "solar-installs.csv": "Solar installations",
    "fish-landings.tsv": "Fish landings",
}

PARENTHETICALS = [
    "the largest in the region",
    "which opened in 1962",
    "now run by a charity",
    "the only one with weekend hours",
    "rated best in the county",
]


# ── Rendering, one function per format ───────────────────────────────────────────


def _table_rows(facts: list[Fact]) -> list[list[str]]:
    """A spreadsheet-shaped document: one row per fact, its claim parts as columns, so the
    extractor's linearised row is the snippet."""
    rows = [["Subject", "Measure", "Change", "Period", "Reason"]]
    for f in facts:
        head, _, last = f.frame.split(" {S}")[0].rpartition(" ")
        measure = head if last in ("at", "in", "to", "on", "for", "of") else f"{head} {last}"
        rows.append([f.S, measure, f"{f.V} {f.X}".strip(), f.P, f.cause or ""])
    return rows


def _docx(title, paras):
    import docx

    d = docx.Document()
    d.add_heading(title, level=1)
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _odt(title, paras):
    from odf.opendocument import OpenDocumentText
    from odf.text import H, P

    doc = OpenDocumentText()
    doc.text.addElement(H(outlinelevel=1, text=title))
    for p in paras:
        doc.text.addElement(P(text=p))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _rtf(title, paras):
    body = "\\par\n".join([title, *paras])
    return ("{\\rtf1\\ansi\\deff0\n" + body + "\\par\n}").encode()


def _epub(title, paras):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        items, refs = [], []
        for i, p in enumerate(paras, start=1):
            z.writestr(
                f"OEBPS/ch{i}.xhtml",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter {i}</h1>'
                f"<p>{p}</p></body></html>",
            )
            items.append(f'<item id="c{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>')
            refs.append(f'<itemref idref="c{i}"/>')
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            f"<metadata><title>{title}</title></metadata><manifest>{''.join(items)}</manifest>"
            f"<spine>{''.join(refs)}</spine></package>",
        )
    return buf.getvalue()


def _pdf(title, paras):
    from tests.dataflow.test_corpus_store import _build_pdf

    return _build_pdf(paras)


def _html(title, paras):
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (
        f"<!doctype html><html><head><title>{title}</title></head>"
        f"<body><h1>{title}</h1>{body}</body></html>\n"
    ).encode()


def _md(title, paras):
    return (f"# {title}\n\n" + "\n\n".join(paras) + "\n").encode()


def _txt(title, paras):
    return (title + "\n\n" + "\n\n".join(paras) + "\n").encode()


def _pptx(title, paras):
    from pptx import Presentation

    deck = Presentation()
    for p in paras:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = p
    buf = io.BytesIO()
    deck.save(buf)
    return buf.getvalue()


def _tex(title, paras):
    return ("\\section{" + title + "}\n" + "\n\n".join(paras) + "\n").encode()


def _ipynb(title, paras):
    cells = [{"cell_type": "markdown", "metadata": {}, "source": [f"# {title}"]}]
    for p in paras:
        cells.append({"cell_type": "markdown", "metadata": {}, "source": [p]})
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(nb, indent=1).encode()


def _xlsx(title, rows):
    import xlsxwriter

    buf = io.BytesIO()
    book = xlsxwriter.Workbook(buf, {"in_memory": True})
    sheet = book.add_worksheet("Figures")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    book.close()
    return buf.getvalue()


def _xls(title, rows):
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Figures")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _ods(title, rows):
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    table = Table(name="Figures")
    for row in rows:
        tr = TableRow()
        for value in row:
            cell = TableCell(valuetype="string")
            cell.addElement(P(text=value))
            tr.addElement(cell)
        table.addElement(tr)
    doc.spreadsheet.addElement(table)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _delimited(sep):
    def render(title, rows):
        return ("\n".join(sep.join(row) for row in rows) + "\n").encode()

    return render


PROSE = {".docx": _docx, ".odt": _odt, ".rtf": _rtf, ".epub": _epub, ".pdf": _pdf,
         ".html": _html, ".md": _md, ".txt": _txt, ".pptx": _pptx, ".tex": _tex,
         ".ipynb": _ipynb}  # fmt: skip
TABLES = {".xlsx": _xlsx, ".xls": _xls, ".ods": _ods, ".csv": _delimited(","),
          ".tsv": _delimited("\t")}  # fmt: skip


def render(doc: str, facts: list[Fact]) -> bytes:
    ext = Path(doc).suffix
    if ext in TABLES:
        return TABLES[ext](TITLES[doc], _table_rows(facts))
    return PROSE[ext](TITLES[doc], [f.source for f in facts])


# ── Snippets and claims ──────────────────────────────────────────────────────────


def snippet_for(fact: Fact, text: str) -> str:
    """The line of extracted text that states this fact: it names the subject and the value."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if fact.source[:30] in ln]
    if not hits:  # a table: the linearised row names the subject and the change
        change = f"{fact.V} {fact.X}".strip()
        hits = [ln for ln in lines if fact.S.lower() in ln.lower() and change in ln]
    if len(hits) != 1:
        raise SystemExit(
            f"{fact.doc}: expected one line stating '{fact.source[:50]}', found {len(hits)}"
        )
    return hits[0]


def items_for(fact: Fact, snippet: str, rng: random.Random) -> list[tuple[str, str, str]]:
    """(claim, category, intended label) for one fact."""
    pos = [(fact.claim(), "paraphrase", "supported")]
    if fact.rounded:
        pos.append((fact.claim(X=fact.rounded), "rounding", "supported"))
    if fact.cause:
        pos.append((fact.claim()[:-1] + f" after {fact.cause}.", "stated_cause", "supported"))
    if fact.extra_ok:
        pos.append((fact.extra_ok + ".", "computed_or_unit", "supported"))

    neg = [
        (fact.claim(X=fact.wrong_X), "wrong_number", "contradicted"),
        (fact.claim(S=fact.alt_S), "wrong_subject", "not_supported"),
        (
            fact.claim()[:-1] + f" and {fact.alt_S} {fact.V} {fact.wrong_X}.".replace("  ", " "),
            "compound_invented_clause",
            "not_supported",
        ),
        (
            fact.claim()[:-1] + f" because of {fact.wrong_cause}.",
            "added_inference",
            "not_supported",
        ),
        (
            fact.claim(S=f"{fact.S} ({rng.choice(PARENTHETICALS)})"),
            "parenthetical",
            "not_supported",
        ),
    ]
    if fact.alt_P and fact.P:
        neg.append((fact.claim(P=fact.alt_P), "wrong_period", "not_supported"))
    if fact.opp_V:
        neg.append((fact.claim(V=fact.opp_V), "opposite_direction", "contradicted"))
    if fact.extra_bad:
        neg.append((fact.extra_bad + ".", "wrong_computation", "not_supported"))
    return pos + rng.sample(neg, k=min(4, len(neg)))


def build() -> dict:
    rng = random.Random(SEED)
    docs = OUT / "documents"
    docs.mkdir(parents=True, exist_ok=True)
    by_doc: dict[str, list[Fact]] = {}
    for f in FACTS:
        by_doc.setdefault(f.doc, []).append(f)

    snippets: dict[int, dict] = {}
    for doc, facts in by_doc.items():
        data = render(doc, facts)
        (docs / doc).write_bytes(data)
        result = extract(doc, data)
        for f in facts:
            snippets[FACTS.index(f)] = {"document": doc, "kind": result.kind,
                                        "mode": result.mode, "text": snippet_for(f, result.text)}  # fmt: skip

    rows: list[dict] = []
    for i, f in enumerate(FACTS):
        for claim, category, label in items_for(f, snippets[i]["text"], rng):
            rows.append(
                {"claim": claim, "snippets": [snippets[i]], "category": category, "label": label}
            )

    # The citation cases need two snippets: two facts from different documents.
    order = list(range(len(FACTS)))
    rng.shuffle(order)
    for a, b in list(zip(order[0::2], order[1::2], strict=True))[:12]:
        fa, fb = FACTS[a], FACTS[b]
        both = fa.claim()[:-1] + ", and " + fb.claim()[0].lower() + fb.claim()[1:]
        rows.append({"claim": both, "snippets": [snippets[a], snippets[b]],
                     "category": "needs_both_sources", "label": "supported"})  # fmt: skip
        rows.append({"claim": both, "snippets": [snippets[a]],
                     "category": "one_of_two_missing", "label": "not_supported"})  # fmt: skip
        rows.append({"claim": fa.claim(), "snippets": [snippets[a], snippets[b]],
                     "category": "one_of_two_enough", "label": "supported"})  # fmt: skip
    # A relevant citation that does not support: same document, a different fact.
    for facts in list(by_doc.values())[:12]:
        b = FACTS.index(facts[1])
        rows.append({"claim": facts[0].claim(), "snippets": [snippets[b]],
                     "category": "relevant_not_supporting", "label": "not_supported"})  # fmt: skip

    rng.shuffle(rows)
    items, authoring = [], {}
    for n, row in enumerate(rows, start=1):
        item_id = f"g{n:03d}"
        items.append({"id": item_id, "claim": row["claim"], "snippets": row["snippets"]})
        authoring[item_id] = {"category": row["category"], "written_as": row["label"]}

    (OUT / "items.json").write_text(
        json.dumps({"version": 1, "seed": SEED, "items": items}, indent=1, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (OUT / "authoring.json").write_text(json.dumps(authoring, indent=1) + "\n", encoding="utf-8")
    labels = [a["written_as"] for a in authoring.values()]
    return {
        "items": len(items),
        "written_as": {k: labels.count(k) for k in ("supported", "not_supported", "contradicted")},
        "formats": sorted({s["kind"] for s in snippets.values()}),
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
