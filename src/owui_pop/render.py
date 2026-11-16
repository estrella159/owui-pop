"""Answers as Open WebUI shows them, in Qt's stricter Markdown.

Open WebUI keeps a single line break as a new line, while CommonMark (and Qt) join such lines into one,
so a model's step-by-step working ran together. It also renders maths with KaTeX, which Qt can't; maths
blocks become readable text instead. Plain ``$`` is left alone, so prices stay prices.
"""
from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(```|~~~)")
_BLOCK_START = re.compile(r"^\s*([-*+]\s|\d+[.)]\s|#{1,6}\s|>|\|)")

_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\approx": "≈", r"\neq": "≠", r"\ne": "≠", r"\leq": "≤",
    r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\pm": "±", r"\infty": "∞", r"\degree": "°", r"\circ": "°",
    r"\to": "→", r"\rightarrow": "→", r"\Rightarrow": "⇒", r"\leftarrow": "←", r"\pi": "π", r"\alpha": "α",
    r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\Delta": "Δ", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ",
    r"\sigma": "σ", r"\Sigma": "Σ", r"\sum": "Σ", r"\%": "%", r"\,": " ", r"\;": " ", r"\quad": "  ", r"\ ": " ",
}


def _math(tex: str) -> str:
    t = tex.strip()
    for _ in range(3):  # nested \frac and \text
        t = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\{([^{}]*)\}", r"\1", t)
        t = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", lambda m: f"{_group(m[1])}/{_group(m[2])}", t)
        t = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", t)
    t = re.sub(r"\^\{?\\circ\}?", "°", t)
    for k in sorted(_SYMBOLS, key=len, reverse=True):
        t = t.replace(k, _SYMBOLS[k])
    t = re.sub(r"\\(left|right)\b", "", t)
    t = t.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _group(s: str) -> str:
    s = s.strip()
    return s if re.fullmatch(r"[\w.]+", s) else f"({s})"


def maths(md: str) -> str:
    md = re.sub(r"\$\$(.+?)\$\$", lambda m: _math(m[1]), md, flags=re.DOTALL)
    md = re.sub(r"\\\[(.+?)\\\]", lambda m: _math(m[1]), md, flags=re.DOTALL)
    return re.sub(r"\\\((.+?)\\\)", lambda m: _math(m[1]), md, flags=re.DOTALL)


def line_breaks(md: str) -> str:
    """A single line break stays a line break (Markdown's two trailing spaces), outside code, lists,
    headings, quotes and tables, where it would change the meaning."""
    lines = md.split("\n")
    out, code = [], False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            code = not code
            out.append(line)
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (not code and line.strip() and nxt.strip() and not _FENCE.match(nxt)
                and not _BLOCK_START.match(line) and not _BLOCK_START.match(nxt) and not line.endswith("  ")):
            line += "  "
        out.append(line)
    return "\n".join(out)


def for_display(md: str) -> str:
    """What the pop-up shows for an answer."""
    return line_breaks(maths(md))
