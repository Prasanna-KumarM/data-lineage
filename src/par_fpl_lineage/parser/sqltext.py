"""Small SQL text helpers shared by the baseline parsers (not a SQL parser)."""
from __future__ import annotations


def split_top_level(text: str) -> list[str]:
    """Split on top-level commas (parenthesis- and quote-aware)."""
    out, cur, depth, in_quote = [], "", 0, False
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def split_insert_values(text: str) -> list[str | None]:
    """Split an INSERT values tuple into Python values ('x' → x, null → None)."""
    out: list[str | None] = []
    for value in split_top_level(text):
        v = value.strip()
        if v.lower() == "null":
            out.append(None)
        elif v.startswith("'") and v.endswith("'"):
            out.append(v[1:-1].replace("''", "'"))
        else:
            out.append(v)
    return out
