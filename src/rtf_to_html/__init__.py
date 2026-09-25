"""rtf_to_html: render RTF documents (tables, listings, figures) to HTML.

No third-party dependencies. Typical use::

    import rtf_to_html
    html = rtf_to_html.convert("output/tlf_baseline.rtf")
    rtf_to_html.convert_file("output/tlf_baseline.rtf")   # writes tlf_baseline.html

In a Jupyter notebook or Quarto document, return ``rtf_to_html.display(...)``
from a cell to show the rendered table inline. It accepts a path or an
``rtflite.RTFDocument`` directly::

    doc = rtflite.RTFDocument(df=..., rtf_title=...)
    rtf_to_html.display(doc)
"""

from __future__ import annotations

import os
from pathlib import Path

from .html import render
from .model import Document
from .parser import Source, parse

__version__ = "0.1.0"
__all__ = [
    "Document",
    "RTFHtml",
    "__version__",
    "convert",
    "convert_file",
    "display",
    "parse",
    "render",
]


def convert(source: Source, *, fragment: bool = False, title: str | None = None) -> str:
    """Convert RTF to an HTML string.

    ``source`` may be a path, raw RTF text, RTF bytes, or an object with an
    ``rtf_encode()`` method such as ``rtflite.RTFDocument``. With ``fragment=True``
    the result is a ``<div class="rtf-doc">`` (with its own scoped ``<style>``)
    that can be embedded in another page; otherwise a complete HTML document.
    """
    if title is None and _is_path(source):
        title = _stem(source)
    return render(parse(source), fragment=fragment, title=title)


def convert_file(
    src: str | os.PathLike,
    dst: str | os.PathLike | None = None,
    *,
    fragment: bool = False,
) -> Path:
    """Convert an RTF file and write the HTML next to it (or to ``dst``)."""
    src_path = Path(src)
    out = Path(dst) if dst is not None else src_path.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(convert(src_path, fragment=fragment), encoding="utf-8")
    return out


class RTFHtml:
    """Rendered RTF that displays itself in Jupyter/Quarto via ``_repr_html_``."""

    def __init__(self, source: Source):
        self.document = parse(source)
        self.title = _stem(source) if _is_path(source) else None

    def _repr_html_(self) -> str:
        return render(self.document, fragment=True, title=self.title)

    def html(self, fragment: bool = False) -> str:
        return render(self.document, fragment=fragment, title=self.title)

    def __str__(self) -> str:
        return f"<RTFHtml pages={len(self.document.pages)}>"

    __repr__ = __str__


def display(source: Source) -> RTFHtml:
    """Return an object that renders inline in notebooks and Quarto output.

    ``source`` may be a path, RTF text/bytes, or an ``rtflite.RTFDocument``::

        rtf_to_html.display("output/tlf_baseline.rtf")
        rtf_to_html.display(doc)   # doc = rtflite.RTFDocument(...)
    """
    return RTFHtml(source)


def _stem(source: Source) -> str:
    return Path(os.fsdecode(source)).stem  # type: ignore[arg-type]


def _is_path(source: Source) -> bool:
    if isinstance(source, bytes) or hasattr(source, "rtf_encode"):
        return False
    if isinstance(source, str):
        return not source.lstrip().startswith("{\\rtf")
    return isinstance(source, os.PathLike)
