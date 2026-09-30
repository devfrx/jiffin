"""The pages with the real texts, for the owner: static HTML in the data folder, in Italian.

Every text is escaped: titles and addresses come from any window and any web page.
"""

from pathlib import Path

import jinja2

_PAGES = jinja2.Environment(
    loader=jinja2.PackageLoader("jiffin.harness", "pages"),
    autoescape=True,
    undefined=jinja2.StrictUndefined,
)


def page(template: str, path: Path, **values: object) -> Path:
    path.write_text(_PAGES.get_template(template).render(**values), encoding="utf-8")
    return path
