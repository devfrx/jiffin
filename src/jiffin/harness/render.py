"""The pages with the real texts, for the owner, in Italian: static HTML in the data folder, and
the labelling page. Their own texts are those of `harness.toml` (ADR-0026), as `t`.

Every text is escaped: titles and addresses come from any window and any web page.
"""

from pathlib import Path

import jinja2

from jiffin.lang.harness import HARNESS

_PAGES = jinja2.Environment(
    loader=jinja2.PackageLoader("jiffin.harness", "pages"),
    autoescape=True,
    undefined=jinja2.StrictUndefined,
)
_PAGES.globals["t"] = HARNESS


def page(template: str, path: Path, **values: object) -> Path:
    path.write_text(text(template, **values), encoding="utf-8")
    return path


def text(template: str, **values: object) -> str:
    return _PAGES.get_template(template).render(**values)
