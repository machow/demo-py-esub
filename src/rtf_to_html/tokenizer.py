"""Lexer for RTF byte streams.

Produces a flat stream of :class:`Token` objects. Text is kept as raw bytes
because the correct decoding depends on the code page in effect, which only
the parser knows.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

_CONTROL_WORD = re.compile(rb"([A-Za-z]+)(-?[0-9]+)?")
_TEXT_RUN = re.compile(rb"[^\\{}\r\n]+")


@dataclass(frozen=True)
class Token:
    kind: str  # "open" | "close" | "control" | "symbol" | "hex" | "text"
    value: object = None
    param: int | None = None


def tokenize(data: bytes) -> Iterator[Token]:
    """Yield tokens from an RTF byte string."""
    i = 0
    n = len(data)
    while i < n:
        c = data[i : i + 1]
        if c == b"{":
            yield Token("open")
            i += 1
        elif c == b"}":
            yield Token("close")
            i += 1
        elif c == b"\\":
            i += 1
            if i >= n:
                break
            m = _CONTROL_WORD.match(data, i)
            if m:
                word = m.group(1).decode("ascii")
                param = int(m.group(2)) if m.group(2) is not None else None
                i = m.end()
                if i < n and data[i : i + 1] == b" ":
                    i += 1  # the delimiting space is part of the control word
                yield Token("control", word, param)
                continue
            sym = data[i : i + 1]
            i += 1
            if sym == b"'":
                yield Token(
                    "hex", bytes.fromhex(data[i : i + 2].decode("ascii", "replace"))
                )
                i += 2
            elif sym in (b"{", b"}", b"\\"):
                yield Token("text", sym)
            elif sym in (b"\r", b"\n"):
                yield Token("control", "par", None)
            else:
                yield Token("symbol", sym.decode("latin-1"))
        elif c in (b"\r", b"\n"):
            i += 1
        else:
            m = _TEXT_RUN.match(data, i)
            assert m is not None  # the character is not a delimiter, so it matches
            yield Token("text", m.group(0))
            i = m.end()
