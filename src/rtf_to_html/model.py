"""Document model produced by the parser and consumed by the HTML emitter."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Font:
    name: str = ""
    family: str = ""  # roman | swiss | modern | script | decor | tech | nil
    charset: int | None = None


@dataclass(frozen=True)
class CharStyle:
    font: int | None = None
    size: int = 24  # half-points
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    hidden: bool = False
    caps: bool = False
    color: int = 0  # index into Document.colors (0 = auto)
    background: int = 0
    link: str | None = None


@dataclass
class Run:
    text: str = ""
    style: CharStyle = field(default_factory=CharStyle)
    field: str | None = None  # "PAGE" | "NUMPAGES" for substituted fields


@dataclass
class Picture:
    data: bytes
    format: str  # png | jpeg | emf | wmf | unknown
    width: int = 0  # twips
    height: int = 0  # twips


@dataclass(frozen=True)
class ParaStyle:
    align: str = "left"  # left | center | right | justify
    space_before: int = 0  # twips
    space_after: int = 0
    first_indent: int = 0
    left_indent: int = 0
    right_indent: int = 0
    line_spacing: int = 0  # \sl value; 0 = auto
    line_spacing_mult: bool = False
    in_table: bool = False
    nesting: int = 0  # \itap
    page_break_before: bool = False


@dataclass
class Paragraph:
    items: list[Run | Picture] = field(default_factory=list)
    style: ParaStyle = field(default_factory=ParaStyle)

    def text(self) -> str:
        return "".join(i.text for i in self.items if isinstance(i, Run))


@dataclass(frozen=True)
class Border:
    style: str | None = None  # single | double | thick | dotted | dashed | triple | ...
    width: int = 0  # twips
    color: int = 0

    @property
    def visible(self) -> bool:
        return self.style is not None and self.style != "none"


@dataclass
class CellDef:
    right: int = 0  # twips, right edge of the cell
    borders: dict[str, Border] = field(default_factory=dict)  # top/left/bottom/right
    valign: str = "top"
    background: int = 0
    shading: int = 0  # \clshdng, percent * 100
    vmerge: str | None = None  # first | rest
    hmerge: str | None = None  # first | rest


@dataclass
class Cell:
    paragraphs: list[Paragraph] = field(default_factory=list)
    definition: CellDef = field(default_factory=CellDef)

    def text(self) -> str:
        return "\n".join(p.text() for p in self.paragraphs)


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)
    left: int = 0  # \trleft
    align: str = "left"  # left | center | right
    gap: int = 108  # \trgaph, half the cell horizontal padding
    header: bool = False  # \trhdr


@dataclass
class Table:
    rows: list[Row] = field(default_factory=list)


Block = Paragraph | Table


@dataclass
class PageSetup:
    width: int = 12240
    height: int = 15840
    margin_left: int = 1800
    margin_right: int = 1800
    margin_top: int = 1440
    margin_bottom: int = 1440
    header_y: int = 720
    footer_y: int = 720
    landscape: bool = False

    @property
    def printable_width(self) -> int:
        return max(self.width - self.margin_left - self.margin_right, 1)


@dataclass
class Page:
    blocks: list[Block] = field(default_factory=list)
    setup: PageSetup = field(default_factory=PageSetup)
    header: list[Block] | None = None
    footer: list[Block] | None = None


@dataclass
class Document:
    pages: list[Page] = field(default_factory=list)
    fonts: dict[int, Font] = field(default_factory=dict)
    colors: list[str | None] = field(default_factory=list)  # "#rrggbb"; index 0 = auto
    default_font: int = 0

    def text(self) -> str:
        """Plain text of the document body, for tests and debugging."""
        out: list[str] = []
        for page in self.pages:
            for block in page.blocks:
                if isinstance(block, Paragraph):
                    out.append(block.text())
                else:
                    for row in block.rows:
                        out.append("\t".join(c.text() for c in row.cells))
        return "\n".join(out)


__all__ = [
    "Block",
    "Border",
    "Cell",
    "CellDef",
    "CharStyle",
    "Document",
    "Font",
    "Page",
    "PageSetup",
    "ParaStyle",
    "Paragraph",
    "Picture",
    "Row",
    "Run",
    "Table",
    "replace",
]
