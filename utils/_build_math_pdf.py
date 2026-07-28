"""Build a polished PDF from gurobi_solver_grouped_math.md via HTML + MathJax."""
from __future__ import annotations

import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
MD_PATH = ROOT / "gurobi_solver_grouped_math.md"
HTML_PATH = ROOT / "gurobi_solver_grouped_math.html"
PDF_PATH = ROOT / "gurobi_solver_grouped_math.pdf"

CSS = """
@page {
  size: letter;
  margin: 0.7in 0.75in 0.75in 0.75in;
}
:root {
  --ink: #1a1a1a;
  --muted: #4a5568;
  --rule: #d0d5dd;
  --accent: #0b3d5c;
  --soft: #f4f7fa;
}
* { box-sizing: border-box; }
html { font-size: 10.5pt; }
body {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: var(--ink);
  line-height: 1.45;
  margin: 0;
  padding: 0;
}
header.doc-header {
  border-bottom: 2.5px solid var(--accent);
  padding-bottom: 0.55rem;
  margin-bottom: 1.1rem;
}
header.doc-header .eyebrow {
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin: 0 0 0.25rem 0;
}
h1 {
  font-size: 1.55rem;
  font-weight: 700;
  color: var(--accent);
  margin: 0 0 0.35rem 0;
  line-height: 1.25;
}
.subtitle {
  color: var(--muted);
  font-size: 0.92rem;
  margin: 0;
}
h2 {
  font-size: 1.15rem;
  color: var(--accent);
  border-bottom: 1px solid var(--rule);
  padding-bottom: 0.25rem;
  margin: 1.35rem 0 0.65rem 0;
  page-break-after: avoid;
}
h3 {
  font-size: 1.0rem;
  color: #243447;
  margin: 1.0rem 0 0.45rem 0;
  page-break-after: avoid;
}
p { margin: 0.45rem 0 0.55rem 0; }
code {
  font-family: Consolas, "Courier New", monospace;
  background: var(--soft);
  padding: 0.05rem 0.28rem;
  border-radius: 3px;
  font-size: 0.9em;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.55rem 0 0.9rem 0;
  font-size: 0.92rem;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid var(--rule);
  padding: 0.35rem 0.45rem;
  vertical-align: top;
  text-align: left;
}
th {
  background: var(--soft);
  color: var(--accent);
  font-weight: 650;
}
tr:nth-child(even) td { background: #fafbfc; }
.MathJax, mjx-container {
  page-break-inside: avoid;
}
mjx-container[display="true"] {
  margin: 0.7rem 0 !important;
  overflow-x: auto;
}
hr {
  border: none;
  border-top: 1px solid var(--rule);
  margin: 1.1rem 0;
}
strong { font-weight: 650; }
footer.doc-footer {
  margin-top: 1.4rem;
  padding-top: 0.55rem;
  border-top: 1px solid var(--rule);
  color: var(--muted);
  font-size: 0.78rem;
}
"""

# Placeholders must not contain markdown-significant characters (_, *, `, etc.).
DISP_TOKEN = "MATHDISPTOKEN{:04d}ZZ"
INL_TOKEN = "MATHINLTOKEN{:04d}ZZ"


def protect_math(text: str) -> tuple[str, list[str], list[str]]:
    """Pull LaTeX out before markdown so '_' / '\\[' are not mangled."""
    displays: list[str] = []
    inlines: list[str] = []

    def _disp(m: re.Match[str]) -> str:
        displays.append(m.group(1))
        return DISP_TOKEN.format(len(displays) - 1)

    def _inl(m: re.Match[str]) -> str:
        inlines.append(m.group(1))
        return INL_TOKEN.format(len(inlines) - 1)

    # Display math first (greedy across lines), then inline.
    text = re.sub(r"\\\[(.*?)\\\]", _disp, text, flags=re.DOTALL)
    text = re.sub(r"\\\((.*?)\\\)", _inl, text, flags=re.DOTALL)
    return text, displays, inlines


def restore_math(html_body: str, displays: list[str], inlines: list[str]) -> str:
    """Put MathJax-ready TeX back into the HTML."""
    for i, tex in enumerate(displays):
        token = DISP_TOKEN.format(i)
        block = f'<div class="math-display">\\[{tex}\\]</div>'
        # Prefer replacing a whole paragraph wrapper from markdown.
        html_body = html_body.replace(f"<p>{token}</p>", block)
        html_body = html_body.replace(token, block)
    for i, tex in enumerate(inlines):
        token = INL_TOKEN.format(i)
        span = f'<span class="math-inline">\\({tex}\\)</span>'
        html_body = html_body.replace(token, span)
    return html_body


def md_to_html(md_text: str) -> str:
    # Drop the first H1 and its lead paragraph; we render a custom header.
    body_md = re.sub(r"^# .+\n+", "", md_text, count=1)
    body_md = re.sub(
        r"^This document states the full Integer Linear Program[\s\S]*?\n\n---\n+",
        "",
        body_md,
        count=1,
    )

    protected, displays, inlines = protect_math(body_md)
    html_body = markdown.markdown(
        protected,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    html_body = restore_math(html_body, displays, inlines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Mathematical Formulation — gurobi_solver_grouped.py</title>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)']],
        displayMath: [['\\\\[', '\\\\]']],
        processEscapes: true
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }}
    }};
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
  <style>{CSS}</style>
</head>
<body>
  <header class="doc-header">
    <p class="eyebrow">SDS-ATP · Room Allocation ILP</p>
    <h1>Mathematical Formulation</h1>
    <p class="subtitle">
      Full Integer Linear Program for <code>utils/gurobi_solver_grouped.py</code>
      (<code>allot_rooms</code>): sets, variables, constraints, and lexicographic objectives.
    </p>
  </header>
  {html_body}
  <footer class="doc-footer">
    SDS Alternative Testing Program (ATP) · Cohort-aware Gurobi room allocation model
  </footer>
</body>
</html>
"""


def build_pdf() -> None:
    md_text = MD_PATH.read_text(encoding="utf-8")
    body_preview = re.sub(r"^# .+\n+", "", md_text, count=1)
    body_preview = re.sub(
        r"^This document states the full Integer Linear Program[\s\S]*?\n\n---\n+",
        "",
        body_preview,
        count=1,
    )
    _, displays, inlines = protect_math(body_preview)

    html = md_to_html(md_text)
    HTML_PATH.write_text(html, encoding="utf-8")

    # Sanity: markdown must not have eaten subscripts inside restored math.
    if re.search(r'class="math-(?:display|inline)"[^>]*>[\s\S]*?<em>', html):
        raise RuntimeError("Math still contains <em> — subscript protection failed")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML_PATH.as_uri(), wait_until="networkidle")
        page.wait_for_function(
            """() => window.MathJax
                 && window.MathJax.startup
                 && window.MathJax.startup.promise"""
        )
        page.evaluate(
            "() => MathJax.startup.promise.then(() => MathJax.typesetPromise())"
        )
        page.wait_for_function(
            "() => document.querySelectorAll('mjx-container').length > 20"
        )
        page.wait_for_timeout(500)

        raw_left = page.evaluate(
            """() => {
              const t = document.body.innerText;
              return /\\\\mathrm\\{gap\\}/.test(t) || /\\\\sum_/.test(t);
            }"""
        )
        if raw_left:
            raise RuntimeError(
                "MathJax did not typeset; raw TeX still visible in page text"
            )

        page.pdf(
            path=str(PDF_PATH),
            format="Letter",
            print_background=True,
            margin={
                "top": "0.65in",
                "bottom": "0.7in",
                "left": "0.7in",
                "right": "0.7in",
            },
            display_header_footer=True,
            header_template=(
                '<div style="font-size:8px; width:100%; text-align:right; '
                'color:#667085; padding-right:0.6in;">'
                "gurobi_solver_grouped · mathematical formulation</div>"
            ),
            footer_template=(
                '<div style="font-size:8px; width:100%; text-align:center; '
                'color:#667085;">'
                '<span class="pageNumber"></span> / '
                '<span class="totalPages"></span></div>'
            ),
        )
        browser.close()

    print(f"Wrote {PDF_PATH}")
    print(f"Math blocks: {len(displays)} display, {len(inlines)} inline")


if __name__ == "__main__":
    build_pdf()
