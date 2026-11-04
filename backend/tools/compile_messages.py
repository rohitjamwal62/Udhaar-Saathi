"""Compile .po files to .mo without GNU gettext (pure Python, standard library only).

Usage (from backend/):  python tools/compile_messages.py            # every locale/*/LC_MESSAGES/django.po
                        python tools/compile_messages.py path/to/file.po

Handles msgctxt, plural forms (msgid_plural / msgstr[N]), multi-line strings and escapes. Fuzzy and untranslated
(empty msgstr) entries are left out, exactly like `msgfmt`. The compiled django.mo is committed to git, so the
server (Render) does not need gettext installed.
"""
from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def unquote(s: str) -> str:
    s = s.strip()
    if not (s.startswith('"') and s.endswith('"')):
        raise ValueError(f"bad po string: {s!r}")
    return ast.literal_eval(s) if "\\x" in s or "\\u" in s else _simple_unescape(s[1:-1])


def _simple_unescape(body: str) -> str:
    out, i = [], 0
    esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append(esc.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r") + '"'


def parse_po(text: str) -> list[dict]:
    """Return entries: {ctxt, id, id_plural, str: {index: text}, flags: set, refs: [str], comments: [str], obsolete}."""
    entries: list[dict] = []
    cur: dict | None = None
    field: tuple[str, int] | None = None

    def new():
        return {"ctxt": None, "id": None, "id_plural": None, "str": {}, "flags": set(), "refs": [], "comments": [], "obsolete": False}

    def finish():
        nonlocal cur, field
        if cur is not None and cur["id"] is not None:
            entries.append(cur)
        cur, field = None, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            finish()
            continue
        if line.startswith("#~"):
            continue                                    # obsolete entries are ignored
        if line.startswith("#"):
            if cur is not None and cur["id"] is not None:
                finish()                                # a comment after the msgstr starts a new entry
            cur = cur or new()
            if line.startswith("#,"):
                cur["flags"].update(f.strip() for f in line[2:].split(",") if f.strip())
            elif line.startswith("#:"):
                cur["refs"].extend(line[2:].split())
            elif line.startswith("#."):
                cur["comments"].append(line[2:].strip())
            continue
        if line.startswith('"'):
            if field is None or cur is None:
                raise ValueError(f"string continuation without a keyword: {raw!r}")
            key, idx = field
            piece = unquote(line)
            if key == "ctxt":
                cur["ctxt"] += piece
            elif key == "id":
                cur["id"] += piece
            elif key == "id_plural":
                cur["id_plural"] += piece
            else:
                cur["str"][idx] += piece
            continue
        kw, _, rest = line.partition(" ")
        if kw == "msgctxt":
            if cur is not None and cur["id"] is not None:
                finish()
            cur = cur or new()
            cur["ctxt"] = unquote(rest)
            field = ("ctxt", 0)
        elif kw == "msgid":
            if cur is not None and cur["id"] is not None:
                finish()
            cur = cur or new()
            cur["id"] = unquote(rest)
            field = ("id", 0)
        elif kw == "msgid_plural":
            cur["id_plural"] = unquote(rest)
            field = ("id_plural", 0)
        elif kw.startswith("msgstr"):
            idx = int(kw[7:-1]) if kw.startswith("msgstr[") else 0
            cur["str"][idx] = unquote(rest)
            field = ("str", idx)
        else:
            raise ValueError(f"unknown po line: {raw!r}")
    finish()
    return entries


def _header(entries: list[dict]) -> dict[str, str]:
    for e in entries:
        if e["id"] == "" and e["ctxt"] is None:
            return {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in e["str"].get(0, "").split("\n") if ":" in ln)}
    return {}


def build_mo(entries: list[dict]) -> bytes:
    messages: dict[bytes, bytes] = {}
    for e in entries:
        is_header = e["id"] == "" and e["ctxt"] is None
        if "fuzzy" in e["flags"] and not is_header:
            continue
        if e["id_plural"] is not None:
            forms = [e["str"].get(i, "") for i in range(max(e["str"]) + 1)] if e["str"] else []
            if not forms or any(not f for f in forms):
                continue
            key = e["id"] + "\0" + e["id_plural"]
            val = "\0".join(forms)
        else:
            val = e["str"].get(0, "")
            if not val and not is_header:
                continue
            key = e["id"]
        if e["ctxt"] is not None:
            key = e["ctxt"] + "\x04" + key
        messages[key.encode("utf-8")] = val.encode("utf-8")
    keys = sorted(messages)
    n = len(keys)
    ids = b"".join(k + b"\0" for k in keys)
    strs = b"".join(messages[k] + b"\0" for k in keys)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets, voffsets, off = [], [], 0
    for k in keys:
        koffsets += [len(k), keystart + off]
        off += len(k) + 1
    off = 0
    for k in keys:
        v = messages[k]
        voffsets += [len(v), valuestart + off]
        off += len(v) + 1
    out = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    out += struct.pack(f"{len(koffsets)}i", *koffsets) + struct.pack(f"{len(voffsets)}i", *voffsets)
    return out + ids + strs


def compile_file(po: Path) -> Path:
    entries = parse_po(po.read_text(encoding="utf-8"))
    mo = po.with_suffix(".mo")
    mo.write_bytes(build_mo(entries))
    done = sum(1 for e in entries if e["id"] and "fuzzy" not in e["flags"] and any(e["str"].values()))
    print(f"{po.relative_to(BASE) if po.is_relative_to(BASE) else po}: {done} translated of {sum(1 for e in entries if e['id'])} -> {mo.name}")
    return mo


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted((BASE / "locale").glob("*/LC_MESSAGES/*.po"))
    if not files:
        print("no .po files found")
        return 1
    for f in files:
        compile_file(f.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
