"""Parser: RTF tokens -> :class:`~rtf_to_html.model.Document`.

The parser is a single pass over the token stream with a stack of group
states. It understands the subset of RTF needed for tables, listings and
figures (see the package README for the supported control words). Unknown
control words are ignored, and unknown ``\\*`` destinations are skipped.
"""

from __future__ import annotations

import codecs
import os
from dataclasses import dataclass, field, replace
from typing import Protocol, Union, cast

from .model import (
    Border,
    Cell,
    CellDef,
    CharStyle,
    Document,
    Font,
    Page,
    PageSetup,
    Paragraph,
    ParaStyle,
    Picture,
    Row,
    Run,
    Table,
)
from .tokenizer import Token, tokenize

Source = Union[str, bytes, "os.PathLike[str]", "RTFEncodable"]


class RTFEncodable(Protocol):
    """Anything with an ``rtf_encode()`` method, e.g. ``rtflite.RTFDocument``."""

    def rtf_encode(self) -> str: ...


# \fcharset -> Python codec
CHARSET_CODECS = {
    0: "cp1252",
    1: "cp1252",
    2: "symbol",
    77: "mac_roman",
    128: "cp932",
    129: "cp949",
    130: "johab",
    134: "gbk",
    136: "big5",
    161: "cp1253",
    162: "cp1254",
    163: "cp1258",
    177: "cp1255",
    178: "cp1256",
    186: "cp1257",
    204: "cp1251",
    222: "cp874",
    238: "cp1250",
    254: "cp437",
    255: "cp850",
}

# Glyph codes of the Windows "Symbol" font -> Unicode (Greek letters and the
# handful of operators that clinical tables use).
_SYMBOL_FONT = {
    0x41: "Α",
    0x42: "Β",
    0x43: "Χ",
    0x44: "Δ",
    0x45: "Ε",
    0x46: "Φ",
    0x47: "Γ",
    0x48: "Η",
    0x49: "Ι",
    0x4A: "ϑ",
    0x4B: "Κ",
    0x4C: "Λ",
    0x4D: "Μ",
    0x4E: "Ν",
    0x4F: "Ο",
    0x50: "Π",
    0x51: "Θ",
    0x52: "Ρ",
    0x53: "Σ",
    0x54: "Τ",
    0x55: "Υ",
    0x56: "ς",
    0x57: "Ω",
    0x58: "Ξ",
    0x59: "Ψ",
    0x5A: "Ζ",
    0x61: "α",
    0x62: "β",
    0x63: "χ",
    0x64: "δ",
    0x65: "ε",
    0x66: "φ",
    0x67: "γ",
    0x68: "η",
    0x69: "ι",
    0x6A: "ϕ",
    0x6B: "κ",
    0x6C: "λ",
    0x6D: "μ",
    0x6E: "ν",
    0x6F: "ο",
    0x70: "π",
    0x71: "θ",
    0x72: "ρ",
    0x73: "σ",
    0x74: "τ",
    0x75: "υ",
    0x76: "ϖ",
    0x77: "ω",
    0x78: "ξ",
    0x79: "ψ",
    0x7A: "ζ",
    0xA3: "≤",
    0xB3: "≥",
    0xB1: "±",
    0xB4: "×",
    0xB8: "÷",
    0xB9: "≠",
    0xBB: "≈",
    0xA5: "∞",
    0xD6: "√",
    0xE5: "∑",
    0xB6: "∂",
    0xAE: "→",
    0xAC: "←",
    0xAB: "↔",
    0xB7: "•",
    0xB0: "°",
    0xB5: "∝",
    0xCE: "∈",
    0xCF: "∉",
}

SYMBOL_CHARS = {"~": chr(0xA0), "_": chr(0x2011), "-": "", "|": "", ":": ""}

CONTROL_CHARS = {
    "tab": "\t",
    "line": "\n",
    "lbr": "\n",
    "emdash": chr(0x2014),
    "endash": chr(0x2013),
    "bullet": chr(0x2022),
    "lquote": chr(0x2018),
    "rquote": chr(0x2019),
    "ldblquote": chr(0x201C),
    "rdblquote": chr(0x201D),
    "emspace": chr(0x2003),
    "enspace": chr(0x2002),
    "qmspace": chr(0x2005),
    "zwj": chr(0x200D),
    "zwnj": chr(0x200C),
    "zwbo": chr(0x200B),
    "ltrmark": chr(0x200E),
    "rtlmark": chr(0x200F),
}

# Destinations whose content is never rendered.
SKIP_DESTINATIONS = {
    "info",
    "stylesheet",
    "listtable",
    "listoverridetable",
    "revtbl",
    "rsidtbl",
    "xmlnstbl",
    "themedata",
    "colorschememapping",
    "latentstyles",
    "datastore",
    "object",
    "nonshppict",
    "footnote",
    "nonesttables",
    "pntxta",
    "pntxtb",
    "wgrffmtfilter",
    "filetbl",
    "template",
    "docvar",
    "mmathPr",
    "pgdsctbl",
    "atnid",
    "atnauthor",
    "annotation",
    "ftnsep",
    "ftnsepc",
    "aftnsep",
    "pgp",
    "pgptbl",
    "passwordhash",
    "sp",
    "sn",
    "sv",
    "shpinst",
}

# Destinations introduced with ``\*`` that we still want to read.
KEEP_STAR = {"ud", "shppict", "fldinst"}

BORDER_STYLES = {
    "brdrs": "single",
    "brdrdb": "double",
    "brdrth": "thick",
    "brdrdot": "dotted",
    "brdrdash": "dashed",
    "brdrdashsm": "dashed",
    "brdrdashd": "dashed",
    "brdrdashdd": "dashed",
    "brdrtriple": "triple",
    "brdrwavy": "single",
    "brdrwavydb": "double",
    "brdrengrave": "single",
    "brdremboss": "single",
    "brdrframe": "single",
    "brdrhair": "single",
    "brdrsh": "single",
    "brdrtnthsg": "single",
    "brdrthtnsg": "single",
    "brdrtnthtnsg": "triple",
    "brdrinset": "single",
    "brdroutset": "single",
    "brdrnone": "none",
    "brdrnil": "none",
}


@dataclass
class _State:
    """Per-group state, copied on ``{`` and discarded on ``}``."""

    char: CharStyle
    para: ParaStyle
    dest: str = "body"  # body|header|footer|fonttbl|colortbl|pict|field|fldinst|fldrslt|skip|upr
    uc: int = 1
    codec: str = "cp1252"


@dataclass
class _Context:
    """Where blocks/runs currently go (document body, or a header/footer)."""

    blocks: list
    items: list = field(default_factory=list)  # current paragraph items
    cell_paras: list = field(default_factory=list)
    row_cells: list = field(default_factory=list)
    table: Table | None = None


@dataclass
class _Field:
    inst: str = ""
    result_start: int = 0
    style: CharStyle | None = None


@dataclass
class _Pict:
    hex: list = field(default_factory=list)
    format: str = "unknown"
    width: int = 0
    height: int = 0
    px_width: int = 0
    px_height: int = 0


class Parser:
    def __init__(self) -> None:
        self.doc = Document()
        self.codec = "cp1252"
        self.doc_setup = PageSetup()
        self.section_setup = PageSetup()
        self.section_header: list | None = None
        self.section_footer: list | None = None
        self.page: Page | None = None
        self.body = _Context(blocks=[])
        self.ctx = self.body
        self.ctx_stack: list[_Context] = []
        # run buffering
        self.run_text: list[str] = []
        self.run_bytes = bytearray()
        self.run_codec = "cp1252"
        self.run_style: CharStyle | None = None
        self.skip_chars = 0
        # tables
        self.cell_defs: list[CellDef] = []
        self.pending_def = CellDef()
        self.border_target: str | None = None
        self.row = Row()
        # font/color tables
        self.font_id: int | None = None
        self.font_name: list[str] = []
        self.font_family = ""
        self.font_charset: int | None = None
        self.color_rgb: dict[str, int] = {}
        # misc destinations
        self.fields: list[_Field] = []
        self.pict: _Pict | None = None
        self.star_pending = False
        self.upr_outer = "body"

    # ------------------------------------------------------------------ driver
    def parse(self, data: bytes) -> Document:
        stack: list[_State] = []
        state = _State(char=CharStyle(), para=ParaStyle())
        for tok in tokenize(data):
            kind = tok.kind
            if kind == "open":
                stack.append(state)
                state = replace(state)
                self.star_pending = False
            elif kind == "close":
                if not stack:
                    break
                prev = state
                state = stack.pop()
                if prev.dest != state.dest:
                    self._close_destination(prev, state)
                self.star_pending = False
                # style changes are flushed lazily by _emit_text
            elif kind == "control":
                self.skip_chars = 0
                state = self._control(state, tok)
            elif kind == "symbol":
                self._symbol(state, str(tok.value))
            elif kind == "hex":
                if self.skip_chars:
                    self.skip_chars -= 1
                    continue
                self._emit_bytes(state, cast(bytes, tok.value))
            elif kind == "text":
                raw = cast(bytes, tok.value)
                if self.skip_chars:
                    k = min(self.skip_chars, len(raw))
                    self.skip_chars -= k
                    raw = raw[k:]
                if raw:
                    self._emit_raw_text(state, raw)
        self._flush_run()
        if self.ctx.items:
            self._end_paragraph(state)
        self.doc.pages = self.doc.pages or []
        return self.doc

    # ---------------------------------------------------------------- controls
    def _control(self, st: _State, tok: Token) -> _State:
        word: str = tok.value  # type: ignore[assignment]
        param = tok.param
        star = self.star_pending
        self.star_pending = False

        if star:
            if word not in KEEP_STAR:
                return replace(st, dest="skip")
            if word == "ud":
                return replace(st, dest=self.upr_outer)
            if word == "fldinst":
                return replace(st, dest="fldinst")
            return st  # shppict: read the contained \pict normally

        dest = st.dest
        if dest == "skip" or dest == "upr":
            return st
        if dest == "fonttbl":
            return self._fonttbl_control(st, word, param)
        if dest == "colortbl":
            if word in ("red", "green", "blue"):
                self.color_rgb[word] = param or 0
            return st
        if dest == "pict":
            return self._pict_control(st, word, param)
        if dest == "fldinst":
            if word in CONTROL_CHARS and self.fields:
                self.fields[-1].inst += CONTROL_CHARS[word]
            return st

        # --- destinations
        if word in SKIP_DESTINATIONS:
            return replace(st, dest="skip")
        if word == "fonttbl":
            return replace(st, dest="fonttbl")
        if word == "colortbl":
            self.color_rgb = {}
            return replace(st, dest="colortbl")
        if word in (
            "header",
            "headerl",
            "headerr",
            "headerf",
            "footer",
            "footerl",
            "footerr",
            "footerf",
        ):
            return self._open_header_footer(st, word)
        if word == "pict":
            self.pict = _Pict()
            return replace(st, dest="pict")
        if word == "field":
            self._flush_run()
            self.fields.append(_Field(result_start=len(self.ctx.items), style=st.char))
            return replace(st, dest="field")
        if word == "fldrslt":
            self._flush_run()
            if self.fields:
                self.fields[-1].result_start = len(self.ctx.items)
            return replace(st, dest="fldrslt")
        if word == "upr":
            self.upr_outer = st.dest
            return replace(st, dest="upr")

        # --- document header
        if word == "deff":
            self.doc.default_font = param or 0
            return replace(st, char=replace(st.char, font=param or 0))
        if word == "ansicpg":
            self.codec = self._codec(f"cp{param}")
            return replace(st, codec=self.codec)
        if word == "mac":
            self.codec = "mac_roman"
            return replace(st, codec=self.codec)
        if word == "pc":
            self.codec = "cp437"
            return replace(st, codec=self.codec)
        if word == "pca":
            self.codec = "cp850"
            return replace(st, codec=self.codec)
        if word == "uc":
            return replace(st, uc=param if param is not None else 1)

        # --- page setup
        if self._page_setup(word, param):
            return st

        # --- special characters
        if word in CONTROL_CHARS:
            self._emit_text(st, CONTROL_CHARS[word])
            return st
        if word == "u":
            self._emit_text(st, chr((param or 0) % 65536))
            self.skip_chars = st.uc
            return st
        if (
            word == "chpgn" or word == "pagenumber"
        ):  # \pagenumber is an rtflite extension
            self._emit_field(st, "PAGE")
            return st
        if word == "pagefield" or word == "totalpage":  # rtflite extensions
            self._emit_field(st, "NUMPAGES")
            return st

        # --- structure
        if word == "par":
            self._end_paragraph(st)
            return st
        if word == "nestcell":
            self._end_paragraph(st)
            return st
        if word == "page" or word == "sect":
            self._page_break(st)
            return st
        if word == "sectd":
            self.section_setup = replace(self.doc_setup)
            return st
        if word == "cell":
            self._end_cell(st)
            return st
        if word == "row":
            self._end_row(st)
            return st
        if word == "trowd":
            self.cell_defs = []
            self.pending_def = CellDef()
            self.border_target = None
            self.row = Row()
            return st
        if word == "nestrow":
            return st
        if self._table_control(word, param):
            return st

        # --- paragraph formatting
        if word == "pard":
            return replace(st, para=ParaStyle())
        para = self._para_control(st.para, word, param)
        if para is not None:
            return replace(st, para=para)

        # --- character formatting
        char = self._char_control(st, word, param)
        if char is not None:
            codec = st.codec
            if word == "f":
                codec = self._font_codec(param)
            return replace(st, char=char, codec=codec)
        return st

    # ------------------------------------------------------------- sub-tables
    def _fonttbl_control(self, st: _State, word: str, param: int | None) -> _State:
        if word == "f":
            self._finish_font()
            self.font_id = param
            return st
        if word in (
            "froman",
            "fswiss",
            "fmodern",
            "fscript",
            "fdecor",
            "ftech",
            "fnil",
            "fbidi",
        ):
            self.font_family = word[1:]
        elif word == "fcharset":
            self.font_charset = param
        elif word == "falt":
            return replace(st, dest="skip")
        return st

    def _finish_font(self) -> None:
        if self.font_id is None:
            return
        name = "".join(self.font_name).strip().rstrip(";").strip()
        self.doc.fonts[self.font_id] = Font(
            name=name, family=self.font_family, charset=self.font_charset
        )
        self.font_id = None
        self.font_name = []
        self.font_family = ""
        self.font_charset = None

    def _finish_color(self) -> None:
        rgb = self.color_rgb
        if rgb:
            r, g, b = (rgb.get(k, 0) for k in ("red", "green", "blue"))
            self.doc.colors.append(f"#{r:02x}{g:02x}{b:02x}")
        else:
            self.doc.colors.append(None)
        self.color_rgb = {}

    def _pict_control(self, st: _State, word: str, param: int | None) -> _State:
        p = self.pict
        if p is None:
            return st
        if word == "pngblip":
            p.format = "png"
        elif word == "jpegblip":
            p.format = "jpeg"
        elif word == "emfblip":
            p.format = "emf"
        elif word in ("wmetafile", "pmmetafile"):
            p.format = "wmf"
        elif word in ("dibitmap", "wbitmap"):
            p.format = "bmp"
        elif word == "picwgoal":
            p.width = param or 0
        elif word == "pichgoal":
            p.height = param or 0
        elif word == "picw":
            p.px_width = param or 0
        elif word == "pich":
            p.px_height = param or 0
        return st

    # ------------------------------------------------------------ page setup
    def _page_setup(self, word: str, param: int | None) -> bool:
        doc_attrs = {
            "paperw": "width",
            "paperh": "height",
            "margl": "margin_left",
            "margr": "margin_right",
            "margt": "margin_top",
            "margb": "margin_bottom",
            "headery": "header_y",
            "footery": "footer_y",
        }
        sect_attrs = {
            "pgwsxn": "width",
            "pghsxn": "height",
            "marglsxn": "margin_left",
            "margrsxn": "margin_right",
            "margtsxn": "margin_top",
            "margbsxn": "margin_bottom",
        }
        if word in doc_attrs:
            setattr(self.doc_setup, doc_attrs[word], param or 0)
            setattr(self.section_setup, doc_attrs[word], param or 0)
            return True
        if word == "landscape":
            self.doc_setup.landscape = True
            self.section_setup.landscape = True
            return True
        if word in sect_attrs:
            setattr(self.section_setup, sect_attrs[word], param or 0)
            return True
        if word == "lndscpsxn":
            self.section_setup.landscape = True
            return True
        return False

    # ----------------------------------------------------------- formatting
    @staticmethod
    def _para_control(p: ParaStyle, word: str, param: int | None) -> ParaStyle | None:
        align = {
            "ql": "left",
            "qc": "center",
            "qr": "right",
            "qj": "justify",
            "qd": "justify",
        }
        if word in align:
            return replace(p, align=align[word])
        attrs = {
            "sb": "space_before",
            "sa": "space_after",
            "fi": "first_indent",
            "li": "left_indent",
            "ri": "right_indent",
            "lin": "left_indent",
            "rin": "right_indent",
        }
        if word in attrs:
            return replace(p, **{attrs[word]: param or 0})  # type: ignore[arg-type]
        if word == "sl":
            return replace(p, line_spacing=param or 0)
        if word == "slmult":
            return replace(p, line_spacing_mult=bool(param))
        if word == "intbl":
            return replace(p, in_table=True)
        if word == "itap":
            return replace(p, nesting=param or 0, in_table=p.in_table or bool(param))
        if word == "pagebb":
            return replace(p, page_break_before=True)
        return None

    @staticmethod
    def _flag(param: int | None) -> bool:
        return param is None or param != 0

    def _char_control(
        self, st: _State, word: str, param: int | None
    ) -> CharStyle | None:
        c = st.char
        if word == "plain":
            return CharStyle(font=self.doc.default_font)
        if word == "f":
            return replace(c, font=param)
        if word == "fs":
            return replace(c, size=param if param is not None else 24)
        if word == "b":
            return replace(c, bold=self._flag(param))
        if word == "i":
            return replace(c, italic=self._flag(param))
        if word == "ulnone":
            return replace(c, underline=False)
        if word.startswith("ul") and word[2:].isalpha() or word == "ul":
            return replace(c, underline=self._flag(param))
        if word == "strike" or word == "striked":
            return replace(c, strike=self._flag(param))
        if word == "super":
            return replace(c, superscript=self._flag(param), subscript=False)
        if word == "sub":
            return replace(c, subscript=self._flag(param), superscript=False)
        if word == "nosupersub":
            return replace(c, superscript=False, subscript=False)
        if word == "v":
            return replace(c, hidden=self._flag(param))
        if word == "caps":
            return replace(c, caps=self._flag(param))
        if word == "cf":
            return replace(c, color=param or 0)
        if word in ("cb", "chcbpat", "highlight"):
            return replace(c, background=param or 0)
        return None

    def _table_control(self, word: str, param: int | None) -> bool:
        d = self.pending_def
        if word == "cellx":
            d.right = param or 0
            self.cell_defs.append(d)
            self.pending_def = CellDef()
            self.border_target = None
            return True
        if word in ("clbrdrt", "clbrdrl", "clbrdrb", "clbrdrr"):
            side = {"t": "top", "l": "left", "b": "bottom", "r": "right"}[word[-1]]
            self.border_target = side
            d.borders[side] = Border()
            return True
        if word in BORDER_STYLES or word in ("brdrw", "brdrcf"):
            if self.border_target:
                b = d.borders[self.border_target]
                if word == "brdrw":
                    b = replace(b, width=param or 0)
                elif word == "brdrcf":
                    b = replace(b, color=param or 0)
                else:
                    b = replace(b, style=BORDER_STYLES[word])
                d.borders[self.border_target] = b
            return True
        if word in (
            "brdrt",
            "brdrl",
            "brdrb",
            "brdrr",
            "brdrbtw",
            "brdrbar",
            "box",
            "trbrdrt",
            "trbrdrl",
            "trbrdrb",
            "trbrdrr",
            "trbrdrh",
            "trbrdrv",
        ):
            self.border_target = None  # paragraph/row borders: ignored
            return True
        if word == "clvertalt":
            d.valign = "top"
        elif word == "clvertalc":
            d.valign = "middle"
        elif word == "clvertalb":
            d.valign = "bottom"
        elif word == "clvmgf":
            d.vmerge = "first"
        elif word == "clvmrg":
            d.vmerge = "rest"
        elif word == "clmgf":
            d.hmerge = "first"
        elif word == "clmrg":
            d.hmerge = "rest"
        elif word == "clcbpat":
            d.background = param or 0
        elif word == "clshdng":
            d.shading = param or 0
        elif word == "trgaph":
            self.row.gap = param or 0
        elif word == "trleft":
            self.row.left = param or 0
        elif word == "trqc":
            self.row.align = "center"
        elif word == "trql":
            self.row.align = "left"
        elif word == "trqr":
            self.row.align = "right"
        elif word == "trhdr":
            self.row.header = True
        else:
            return False
        return True

    # ------------------------------------------------------------ text runs
    def _codec(self, name: str) -> str:
        try:
            codecs.lookup(name)
            return name
        except LookupError:
            return "cp1252"

    def _font_codec(self, font_id: int | None) -> str:
        font = self.doc.fonts.get(font_id) if font_id is not None else None
        if font is None or font.charset is None:
            return self.codec
        name = CHARSET_CODECS.get(font.charset)
        if name is None:
            return self.codec
        if name == "symbol":
            return name
        return self._codec(name)

    def _decode(self, raw: bytes, codec: str) -> str:
        if codec == "symbol":
            return "".join(_SYMBOL_FONT.get(b, chr(b)) for b in raw)
        return raw.decode(codec, errors="replace")

    def _emit_raw_text(self, st: _State, raw: bytes) -> None:
        """Unescaped text. Writers such as rtflite put UTF-8 straight into an
        ``\\ansi`` file, so valid UTF-8 wins over the code page (as in LibreOffice)."""
        renderable = st.dest in ("body", "fldrslt") or st.dest.startswith(
            ("header", "footer")
        )
        if renderable and any(b >= 0x80 for b in raw):
            try:
                self._emit_text(st, raw.decode("utf-8"))
                return
            except UnicodeDecodeError:
                pass
        self._emit_bytes(st, raw)

    def _emit_bytes(self, st: _State, raw: bytes) -> None:
        dest = st.dest
        if dest in ("skip", "upr", "field"):
            return
        if dest == "fonttbl":
            segments = raw.decode(self.codec, errors="replace").split(";")
            for segment in segments[:-1]:
                self.font_name.append(segment)
                self._finish_font()
            self.font_name.append(segments[-1])
            return
        if dest == "colortbl":
            for ch in raw.decode("ascii", errors="ignore"):
                if ch == ";":
                    self._finish_color()
            return
        if dest == "pict":
            if self.pict is not None:
                self.pict.hex.append(raw.decode("ascii", errors="ignore").strip())
            return
        if dest == "fldinst":
            if self.fields:
                self.fields[-1].inst += raw.decode(self.codec, errors="replace")
            return
        # body / header / footer / fldrslt
        self._prepare_run(st)
        if self.run_bytes and self.run_codec != st.codec:
            self.run_text.append(self._decode(bytes(self.run_bytes), self.run_codec))
            self.run_bytes.clear()
        self.run_codec = st.codec
        self.run_bytes += raw

    def _emit_text(self, st: _State, text: str) -> None:
        dest = st.dest
        if dest in ("skip", "upr", "field", "fonttbl", "colortbl", "pict"):
            return
        if dest == "fldinst":
            if self.fields:
                self.fields[-1].inst += text
            return
        self._prepare_run(st)
        if self.run_bytes:
            self.run_text.append(self._decode(bytes(self.run_bytes), self.run_codec))
            self.run_bytes.clear()
        self.run_text.append(text)

    def _prepare_run(self, st: _State) -> None:
        if self.run_style is not None and self.run_style != st.char:
            self._flush_run()
        self.run_style = st.char

    def _flush_run(self) -> None:
        if self.run_bytes:
            self.run_text.append(self._decode(bytes(self.run_bytes), self.run_codec))
            self.run_bytes.clear()
        text = "".join(self.run_text)
        self.run_text = []
        if text and self.run_style is not None:
            self.ctx.items.append(Run(text=text, style=self.run_style))
        self.run_style = None

    def _emit_field(self, st: _State, name: str) -> None:
        if st.dest in ("skip", "upr", "fonttbl", "colortbl", "pict", "fldinst"):
            return
        self._flush_run()
        self.ctx.items.append(Run(text="", style=st.char, field=name))

    def _symbol(self, st: _State, sym: str) -> None:
        if sym == "*":
            self.star_pending = True
            return
        if SYMBOL_CHARS.get(sym):
            self._emit_text(st, SYMBOL_CHARS[sym])
        # other control symbols are ignored

    # ------------------------------------------------------------ structure
    def _end_paragraph(self, st: _State) -> None:
        self._flush_run()
        ctx = self.ctx
        para = Paragraph(items=ctx.items, style=st.para)
        ctx.items = []
        in_cell = st.para.in_table or ctx.row_cells or ctx.cell_paras
        if in_cell:
            ctx.cell_paras.append(para)
            return
        ctx.table = None
        if (
            st.para.page_break_before
            and ctx is self.body
            and self.page is not None
            and self.page.blocks
        ):
            self.page = None
        self._append_block(para)

    def _end_cell(self, st: _State) -> None:
        self._flush_run()
        ctx = self.ctx
        if ctx.items or not ctx.cell_paras:
            ctx.cell_paras.append(Paragraph(items=ctx.items, style=st.para))
            ctx.items = []
        i = len(ctx.row_cells)
        if i < len(self.cell_defs):
            definition = self.cell_defs[i]
        else:
            prev = self.cell_defs[-1].right if self.cell_defs else 0
            definition = CellDef(right=prev)
        ctx.row_cells.append(Cell(paragraphs=ctx.cell_paras, definition=definition))
        ctx.cell_paras = []

    def _end_row(self, st: _State) -> None:
        self._flush_run()
        ctx = self.ctx
        if ctx.items or ctx.cell_paras:
            self._end_cell(st)
        if not ctx.row_cells:
            return
        # Word repeats the row definition right before \row; re-zip with the
        # latest definitions so that late definitions win.
        for i, cell in enumerate(ctx.row_cells):
            if i < len(self.cell_defs):
                cell.definition = self.cell_defs[i]
        row = replace(self.row, cells=ctx.row_cells)
        ctx.row_cells = []
        if ctx.table is None:
            ctx.table = Table()
            self._append_block(ctx.table)
        ctx.table.rows.append(row)
        self.row = Row(
            left=self.row.left,
            align=self.row.align,
            gap=self.row.gap,
            header=self.row.header,
        )

    def _page_break(self, st: _State) -> None:
        if self.ctx is not self.body:
            return
        self._flush_run()
        if self.ctx.items:
            self._end_paragraph(st)
        self.ctx.table = None
        self.page = None

    def _ensure_page(self) -> Page:
        if self.page is None:
            self.page = Page(
                setup=replace(self.section_setup),
                header=self.section_header,
                footer=self.section_footer,
            )
            self.doc.pages.append(self.page)
        return self.page

    def _append_block(self, block) -> None:
        if self.ctx is self.body:
            self._ensure_page().blocks.append(block)
        else:
            self.ctx.blocks.append(block)

    def _open_header_footer(self, st: _State, word: str) -> _State:
        self._flush_run()
        self.ctx_stack.append(self.ctx)
        self.ctx = _Context(blocks=[])
        return replace(st, dest=word, para=ParaStyle())

    def _close_destination(self, prev: _State, new: _State) -> None:
        dest = prev.dest
        if dest == "fonttbl":
            self._finish_font()
        elif dest == "colortbl":
            pass
        elif dest in (
            "header",
            "headerl",
            "headerr",
            "headerf",
            "footer",
            "footerl",
            "footerr",
            "footerf",
        ):
            self._flush_run()
            if self.ctx.items:
                self._end_paragraph(prev)
            if self.ctx.row_cells or self.ctx.cell_paras:
                self._end_row(prev)
            blocks = self.ctx.blocks
            self.ctx = self.ctx_stack.pop()
            is_header = dest.startswith("header")
            first_only = dest.endswith("f")
            current = self.section_header if is_header else self.section_footer
            if first_only and current is not None:
                return
            if is_header:
                self.section_header = blocks
                if self.page is not None:
                    self.page.header = blocks
            else:
                self.section_footer = blocks
                if self.page is not None:
                    self.page.footer = blocks
        elif dest == "pict":
            self._finish_pict(new)
        elif dest == "field":
            self._finish_field(new)
        # skip / upr / fldinst / fldrslt need nothing

    def _finish_pict(self, st: _State) -> None:
        p = self.pict
        self.pict = None
        if p is None or st.dest in ("skip", "upr"):
            return
        try:
            data = bytes.fromhex("".join(p.hex))
        except ValueError:
            return
        if not data:
            return
        width = p.width or p.px_width * 15
        height = p.height or p.px_height * 15
        self._flush_run()
        self.ctx.items.append(
            Picture(data=data, format=p.format, width=width, height=height)
        )

    def _finish_field(self, st: _State) -> None:
        self._flush_run()
        if not self.fields:
            return
        f = self.fields.pop()
        inst = f.inst.strip()
        words = inst.split()
        kind = words[0].upper() if words else ""
        items = self.ctx.items
        result = items[f.result_start :]
        style = f.style or CharStyle()
        if kind in ("PAGE", "NUMPAGES", "SECTIONPAGES"):
            for r in result:
                if isinstance(r, Run):
                    style = r.style
                    break
            del items[f.result_start :]
            items.append(
                Run(
                    text="", style=style, field="NUMPAGES" if kind != "PAGE" else "PAGE"
                )
            )
        elif kind == "HYPERLINK":
            url = ""
            if '"' in inst:
                url = inst.split('"')[1]
            elif len(words) > 1:
                url = words[1]
            for r in result:
                if isinstance(r, Run):
                    r.style = replace(r.style, link=url or None)


def _to_bytes(source: Source) -> bytes:
    if isinstance(source, bytes):
        return source
    if hasattr(source, "rtf_encode"):  # rtflite.RTFDocument or similar
        return _to_bytes(source.rtf_encode())  # type: ignore[union-attr]
    if isinstance(source, str):
        if source.lstrip().startswith("{\\rtf"):
            try:
                return source.encode("latin-1")
            except UnicodeEncodeError:
                return source.encode("utf-8")
        return open(source, "rb").read()
    return open(os.fspath(source), "rb").read()


def parse(source: Source) -> Document:
    """Parse RTF from a path, a byte string, an RTF string, or an object with
    an ``rtf_encode()`` method (such as ``rtflite.RTFDocument``)."""
    return Parser().parse(_to_bytes(source))
