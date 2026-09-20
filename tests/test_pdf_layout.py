"""PDF layout: decorative page breaks must not spill pages.

Regression: a 1-page question paper shipped as 3 near-empty pages
because the model framed it with decorative `---` lines and every one
paginated. Mid-content breaks still paginate (documented contract);
leading/trailing/doubled breaks collapse to nothing.
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.make_tool import _build_pdf, _parse_blocks


def _pages(data: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


QUESTION_PAPER = """4. Select the most appropriate option: 4 x 0.5 = 2; [CLO1]
(Don't write any sentence; only mention the correct numbering of your choice)
i) Electric flux through a closed surface can be calculated by:
A) Gauss' law.
B) Principle of superposition.
C) Coulomb's law.
D) Increasing the amount of charge.
ii) Electric field lines are:
A) Not close to each other at all.
B) Not continuous.
C) Always perpendicular to each other.
D) Are always independent of any charge.
iii) Divergence of a vector field:
A) Cannot be determined.
B) Can have magnitude and direction.
C) Is always a scalar.
D) Has always a direction.
iv) Which one is not correct?
A) Matter and energy are interconvertible under special conditions.
B) Two positive charges can exert force on a single charge.
C) Coulomb's law in electrostatics is an experimental law.
D) Electric potential is a vector quantity.
THE END."""


def test_short_paper_without_breaks_is_one_page():
    data = _build_pdf("Physics Question Paper", _parse_blocks(QUESTION_PAPER))
    assert _pages(data) == 1


def test_edge_and_doubled_breaks_collapse():
    md = "---\n\n" + QUESTION_PAPER + "\n\n---\n\n---\n"
    data = _build_pdf("Physics Question Paper", _parse_blocks(md))
    assert _pages(data) == 1


def test_mid_content_break_still_paginates():
    md = QUESTION_PAPER + "\n\n---\n\nAppendix: formulas.\n"
    data = _build_pdf("Physics Question Paper", _parse_blocks(md))
    assert _pages(data) == 2


def test_pdf_description_warns_on_decorative_breaks():
    from tools.make_tool import create_pdf

    assert "never as" in str(create_pdf.description or "").lower()
    assert "decoration" in str(create_pdf.description or "")
