"""HTML emitter: :class:`~rtf_to_html.model.Document` -> HTML string.

Every RTF page becomes a ``div.rtf-page`` sized from the paper settings (in
points) and scaled down to fit narrower containers. Tables use a shared
``colgroup`` computed from all cell edges so rows with different column
layouts (e.g. a full-width footnote row) line up like they do in Word.
"""

from __future__ import annotations

import base64
import html as _html
import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from .model import (
    Block,
    Border,
    Cell,
    CharStyle,
    Document,
    Font,
    Page,
    PageSetup,
    Paragraph,
    Picture,
    Row,
    Run,
    Table,
)

CSS = """\
.rtf-doc { background: #e9e9e9; padding: 16px; box-sizing: border-box; color: #000;
  font-family: "Times New Roman", Times, serif; font-size: 12pt; line-height: 1.2; }
.rtf-doc * { box-sizing: border-box; }
.rtf-doc .rtf-page { background: #fff; color: #000; max-width: 100%; margin: 0 auto 16px auto;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3); display: flex; flex-direction: column;
  overflow-x: auto; }
.rtf-doc .rtf-page:last-child { margin-bottom: 0; }
.rtf-doc .rtf-body { flex: 1 0 auto; }
.rtf-doc .rtf-footer { display: flex; flex-direction: column; justify-content: flex-end; }
.rtf-doc p { margin: 0; white-space: pre-wrap; tab-size: 8; overflow-wrap: break-word; }
.rtf-doc table { border-collapse: collapse; table-layout: fixed; border: 0; margin-top: 0;
  margin-bottom: 0; background: transparent; }
.rtf-doc tr, .rtf-doc td { background: transparent; box-shadow: none; border: 0; }
.rtf-doc td { padding: 0; vertical-align: top; overflow-wrap: break-word; }
.rtf-doc img { max-width: 100%; height: auto; vertical-align: bottom; }
.rtf-doc sup, .rtf-doc sub { line-height: 0; font-size: 0.65em; }
.rtf-doc a { color: inherit; }
.rtf-doc .rtf-picture-unsupported { display: inline-block; border: 1px dashed #999;
  color: #666; font-size: 9pt; padding: 4px; vertical-align: middle; }
"""

GENERIC_FAMILY = {
    "roman": "serif",
    "swiss": "sans-serif",
    "modern": "monospace",
    "script": "cursive",
    "decor": "fantasy",
    "tech": "serif",
    "bidi": "serif",
    "nil": "serif",
}

_TWIP = 20.0  # twips per point


def pt(twips: float) -> str:
    v = round(twips / _TWIP, 2)
    return f"{int(v) if v == int(v) else v}pt"


def pct(value: float) -> str:
    v = round(value, 3)
    return f"{int(v) if v == int(v) else v}%"


def escape(text: str) -> str:
    return _html.escape(text, quote=False)


def render(doc: Document, *, fragment: bool = False, title: str | None = None) -> str:
    """Render a parsed document to HTML."""
    body = Renderer(doc).render()
    if fragment:
        return f'<div class="rtf-doc"><style>{CSS}</style>\n{body}</div>\n'
    t = escape(title or "RTF document")
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{t}</title>\n<style>\nbody {{ margin: 0; }}\n{CSS}</style>\n</head>\n"
        f'<body>\n<div class="rtf-doc">\n{body}</div>\n</body>\n</html>\n'
    )


@dataclass
class _Base:
    """Font/size that the enclosing paragraph already sets."""

    font: int | None
    size: int


class Renderer:
    def __init__(self, doc: Document):
        self.doc = doc
        self.page_no = 0
        self.page_total = max(len(doc.pages), 1)

    # ------------------------------------------------------------------ pages
    def render(self) -> str:
        pages = self.doc.pages or [Page()]
        self.page_total = len(pages)
        out = []
        for i, page in enumerate(pages, start=1):
            self.page_no = i
            out.append(self.render_page(page))
        return "".join(out)

    def render_page(self, page: Page) -> str:
        s = page.setup
        pad_top = min(s.margin_top, s.header_y)
        pad_bottom = min(s.margin_bottom, s.footer_y)
        style = (
            f"width: {pt(s.width)}; min-height: {pt(s.height)}; "
            f"padding: {pt(pad_top)} {pt(s.margin_right)} {pt(pad_bottom)} {pt(s.margin_left)};"
        )
        header_min = max(s.margin_top - s.header_y, 0)
        footer_min = max(s.margin_bottom - s.footer_y, 0)
        parts = [f'<div class="rtf-page" style="{style}">\n']
        parts.append(f'<div class="rtf-header" style="min-height: {pt(header_min)};">')
        parts.append(self.render_blocks(page.header or [], s))
        parts.append("</div>\n")
        parts.append('<div class="rtf-body">\n')
        parts.append(self.render_blocks(page.blocks, s))
        parts.append("</div>\n")
        parts.append(f'<div class="rtf-footer" style="min-height: {pt(footer_min)};">')
        parts.append(self.render_blocks(page.footer or [], s))
        parts.append("</div>\n</div>\n")
        return "".join(parts)

    def render_blocks(self, blocks: Iterable[Block], setup: PageSetup) -> str:
        out = []
        for block in blocks:
            if isinstance(block, Table):
                out.append(self.render_table(block, setup))
            else:
                out.append(self.render_paragraph(block))
        return "".join(out)

    # ------------------------------------------------------------- paragraphs
    def _font_css(self, font_id: int | None) -> str:
        font: Font | None = self.doc.fonts.get(font_id) if font_id is not None else None
        if font is None:
            font = self.doc.fonts.get(self.doc.default_font)
        if font is None:
            return ""
        generic = GENERIC_FAMILY.get(font.family, "")
        name = font.name.strip()
        if not name and not generic:
            return ""
        if not name:
            return generic
        if not generic:
            generic = _guess_generic(name)
        quoted = f'"{name}"' if " " in name else name
        return f"{quoted}, {generic}" if generic else quoted

    def _base_of(self, items: list) -> _Base:
        for item in items:
            if (
                isinstance(item, Run)
                and (item.text or item.field)
                and not item.style.hidden
            ):
                return _Base(item.style.font, item.style.size)
        return _Base(self.doc.default_font, 24)

    def render_paragraph(self, para: Paragraph, *, in_cell: bool = False) -> str:
        st = para.style
        base = self._base_of(para.items)
        css = []
        if st.align != "left":
            css.append(f"text-align: {st.align}")
        if st.space_before or st.space_after:
            css.append(f"margin: {pt(st.space_before)} 0 {pt(st.space_after)} 0")
        if st.left_indent:
            css.append(f"padding-left: {pt(st.left_indent)}")
        if st.right_indent:
            css.append(f"padding-right: {pt(st.right_indent)}")
        if st.first_indent:
            css.append(f"text-indent: {pt(st.first_indent)}")
        if st.line_spacing:
            if st.line_spacing_mult:
                css.append(f"line-height: {round(st.line_spacing / 240, 3)}")
            else:
                css.append(f"line-height: {pt(abs(st.line_spacing))}")
        family = self._font_css(base.font)
        if family:
            css.append(f"font-family: {family}")
        css.append(f"font-size: {pt(base.size * 10)}")
        inner = self.render_items(para.items, base)
        if not inner.strip():
            inner = "<br>"
        style = "; ".join(css)
        return f'<p style="{style};">{inner}</p>\n'

    def render_items(self, items: list, base: _Base) -> str:
        out = []
        pending: Run | None = None
        for item in items:
            if isinstance(item, Picture):
                if pending is not None:
                    out.append(self.render_run(pending, base))
                    pending = None
                out.append(self.render_picture(item))
                continue
            if item.style.hidden:
                continue
            if (
                pending is not None
                and pending.style == item.style
                and item.field is None
                and pending.field is None
            ):
                pending = Run(text=pending.text + item.text, style=pending.style)
            else:
                if pending is not None:
                    out.append(self.render_run(pending, base))
                pending = item
        if pending is not None:
            out.append(self.render_run(pending, base))
        return "".join(out)

    def render_run(self, run: Run, base: _Base) -> str:
        s: CharStyle = run.style
        if run.field == "PAGE":
            text = str(self.page_no)
        elif run.field == "NUMPAGES":
            text = str(self.page_total)
        else:
            text = run.text
        if s.caps:
            text = text.upper()
        content = escape(text).replace("\n", "<br>")
        css = []
        if s.font != base.font:
            family = self._font_css(s.font)
            if family:
                css.append(f"font-family: {family}")
        if s.size != base.size:
            css.append(f"font-size: {pt(s.size * 10)}")
        color = self._color(s.color)
        if color:
            css.append(f"color: {color}")
        bg = self._color(s.background)
        if bg:
            css.append(f"background-color: {bg}")
        deco = []
        if s.underline:
            deco.append("underline")
        if s.strike:
            deco.append("line-through")
        if deco:
            css.append("text-decoration: " + " ".join(deco))
        if css:
            content = f'<span style="{"; ".join(css)};">{content}</span>'
        if s.bold:
            content = f"<b>{content}</b>"
        if s.italic:
            content = f"<i>{content}</i>"
        if s.superscript:
            content = f"<sup>{content}</sup>"
        elif s.subscript:
            content = f"<sub>{content}</sub>"
        if s.link:
            content = f'<a href="{_html.escape(s.link, quote=True)}">{content}</a>'
        return content

    def _color(self, index: int) -> str | None:
        if index <= 0 or index >= len(self.doc.colors):
            return None
        return self.doc.colors[index]

    def render_picture(self, pic: Picture) -> str:
        size = []
        if pic.width:
            size.append(f"width: {pt(pic.width)}")
        if pic.height:
            size.append(f"height: {pt(pic.height)}")
        style = "; ".join(size)
        mime = {"png": "image/png", "jpeg": "image/jpeg"}.get(pic.format)
        if mime is None:
            label = f"[{pic.format.upper()} image not supported]"
            return (
                f'<span class="rtf-picture-unsupported" style="{style};">{label}</span>'
            )
        data = base64.b64encode(pic.data).decode("ascii")
        return f'<img src="data:{mime};base64,{data}" style="{style};" alt="">'

    # ----------------------------------------------------------------- tables
    def render_table(self, table: Table, setup: PageSetup) -> str:
        rows = table.rows
        if not rows:
            return ""
        edges: set[int] = set()
        for row in rows:
            left = row.left
            edges.add(left)
            for cell in row.cells:
                left = max(left, cell.definition.right)
                edges.add(left)
        xs = sorted(edges)
        if len(xs) < 2:
            return ""
        table_left, table_right = xs[0], xs[-1]
        table_width = table_right - table_left
        printable = setup.printable_width
        width_pct = min(table_width / printable * 100, 100)
        first = rows[0]
        margins = "margin-left: auto; margin-right: auto"
        if first.align == "right":
            margins = "margin-left: auto; margin-right: 0"
        elif first.align == "left":
            margins = f"margin-left: {pct(max(table_left, 0) / printable * 100)}"
        # data-quarto-disable-processing keeps Quarto from rewriting the table.
        out = [
            f'<table data-quarto-disable-processing="true" style="width: {pct(width_pct)}; {margins};">\n<colgroup>'
        ]
        for a, b in pairwise(xs):
            out.append(f'<col style="width: {pct((b - a) / table_width * 100)}">')
        out.append("</colgroup>\n")

        spans = self._cell_spans(rows, xs)
        rowspans = self._rowspans(rows, spans)
        for r, row in enumerate(rows):
            out.append("<tr>")
            for c, cell in enumerate(row.cells):
                span = spans[r][c]
                if span is None:
                    continue  # merged into a neighbour
                colspan, rowspan = span, rowspans[r][c]
                attrs = []
                if colspan > 1:
                    attrs.append(f' colspan="{colspan}"')
                if rowspan > 1:
                    attrs.append(f' rowspan="{rowspan}"')
                out.append(f'<td{"".join(attrs)} style="{self._cell_css(cell, row)};">')
                out.append(
                    "".join(
                        self.render_paragraph(p, in_cell=True) for p in cell.paragraphs
                    )
                )
                out.append("</td>")
            out.append("</tr>\n")
        out.append("</table>\n")
        return "".join(out)

    @staticmethod
    def _cell_spans(rows: list[Row], xs: list[int]) -> list[list[int | None]]:
        """Colspan per cell (None = horizontally merged into the previous cell)."""
        index = {x: i for i, x in enumerate(xs)}
        result: list[list[int | None]] = []
        for row in rows:
            spans: list[int | None] = []
            left = row.left
            anchor = None  # index (in spans) of the cell absorbing \clmrg cells
            for cell in row.cells:
                right = max(left, cell.definition.right)
                n = max(index.get(right, index.get(left, 0)) - index.get(left, 0), 1)
                if cell.definition.hmerge == "rest" and anchor is not None:
                    spans[anchor] = (spans[anchor] or 0) + n
                    spans.append(None)
                else:
                    spans.append(n)
                    anchor = len(spans) - 1
                left = right
            result.append(spans)
        return result

    @staticmethod
    def _rowspans(rows: list[Row], spans: list[list[int | None]]) -> list[list[int]]:
        """Rowspan per cell; cells continuing a vertical merge get span None."""
        # column position (start index) of each cell
        starts: list[list[int]] = []
        for r, row in enumerate(rows):
            pos = 0
            row_starts = []
            for c, cell in enumerate(row.cells):
                row_starts.append(pos)
                pos += spans[r][c] or 0
            starts.append(row_starts)
        result = [[1] * len(row.cells) for row in rows]
        for r, row in enumerate(rows):
            for c, cell in enumerate(row.cells):
                if spans[r][c] is None or cell.definition.vmerge == "rest":
                    continue
                n = 1
                for r2 in range(r + 1, len(rows)):
                    found = False
                    for c2, cell2 in enumerate(rows[r2].cells):
                        if (
                            spans[r2][c2] is not None
                            and starts[r2][c2] == starts[r][c]
                            and spans[r2][c2] == spans[r][c]
                            and cell2.definition.vmerge == "rest"
                        ):
                            spans[r2][c2] = None
                            found = True
                            break
                    if not found:
                        break
                    n += 1
                result[r][c] = n
        return result

    def _cell_css(self, cell: Cell, row: Row) -> str:
        d = cell.definition
        css = [f"padding: 0 {pt(row.gap)}"]
        for side in ("top", "right", "bottom", "left"):
            border = d.borders.get(side)
            if border is not None and border.visible:
                css.append(f"border-{side}: {self._border_css(border)}")
            elif border is not None and border.style == "none":
                css.append(f"border-{side}: none")
        if d.valign != "top":
            css.append(f"vertical-align: {d.valign}")
        bg = self._color(d.background)
        if bg:
            css.append(f"background-color: {bg}")
        return "; ".join(css)

    def _border_css(self, b: Border) -> str:
        width = b.width / _TWIP if b.width else 0.75
        style = b.style or "single"
        if style == "double":
            css = f"{max(round(width * 3, 2), 2.25)}pt double"
        elif style == "triple":
            css = f"{max(round(width * 5, 2), 3.75)}pt double"
        elif style == "thick":
            css = f"{max(round(width, 2), 1.5)}pt solid"
        elif style in ("dotted", "dashed"):
            css = f"{max(round(width, 2), 0.75)}pt {style}"
        else:
            css = f"{max(round(width, 2), 0.5)}pt solid"
        color = self._color(b.color)
        return f"{css} {color}" if color else css


def _guess_generic(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("courier", "mono", "consolas", "menlo")):
        return "monospace"
    if any(
        k in n
        for k in ("arial", "helvetica", "calibri", "verdana", "tahoma", "segoe", "sans")
    ):
        return "sans-serif"
    return "serif"


_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<style>.*?</style>|<head>.*?</head>", re.DOTALL)


def visible_text(html: str) -> str:
    """Plain text of rendered HTML (for tests): tags removed, entities unescaped."""
    text = _STYLE.sub("", html)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|td|tr|div)>", "\n", text)
    text = _TAG.sub("", text)
    return _html.unescape(text)
