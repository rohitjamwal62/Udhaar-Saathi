"""Collect every translatable string into locale/<lang>/LC_MESSAGES/django.po without GNU gettext.

A stand-in for `manage.py makemessages` on machines that do not have gettext (for example Windows). It finds:
  * Python:    gettext / gettext_lazy / _ / ngettext(_lazy) / pgettext(_lazy) / gettext_noop calls (via `ast`)
  * Templates: {% trans %}, {% translate %}, {% blocktrans %} / {% blocktranslate %} (with trimmed, count, context, plural)
and merges them into the existing .po: translations already written are kept, new strings are added with an empty
msgstr (the test-suite fails until you translate them), strings no longer used are dropped.

Usage (from backend/):  python tools/extract_messages.py [-l hi]  &&  python tools/compile_messages.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_messages import BASE, compile_file, parse_po, quote  # noqa: E402

PY_FUNCS = {"gettext", "gettext_lazy", "_", "gettext_noop", "ngettext", "ngettext_lazy", "pgettext", "pgettext_lazy", "npgettext"}
SCAN_DIRS = ["apps", "config", "templates"]
SKIP_PARTS = {"migrations", "__pycache__", "tests"}

TRANS_RE = re.compile(r"""\{%\s*(?:trans|translate)\s+(?P<q>["'])(?P<s>.*?)(?P=q)(?P<rest>[^%]*?)%\}""", re.S)
BLOCK_RE = re.compile(r"\{%\s*(?:blocktrans|blocktranslate)\b(?P<opts>[^%]*?)%\}(?P<body>.*?)\{%\s*endblocktrans(?:late)?\s*%\}", re.S)
CTX_RE = re.compile(r"""context\s+(["'])(.*?)\1""")


def _trim(s: str) -> str:
    return re.sub(r"\s*\n\s*", " ", s.strip())


def _block_msg(body: str, trimmed: bool) -> str:
    if trimmed:
        body = _trim(body)
    body = body.replace("%", "%%")
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", r"%(\1)s", body)


def from_template(path: Path, rel: str, found: list) -> None:
    text = path.read_text(encoding="utf-8")
    line_of = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    for m in TRANS_RE.finditer(text):
        ctx = CTX_RE.search(m.group("rest"))
        found.append((ctx.group(2) if ctx else None, m.group("s"), None, f"{rel}:{line_of(m.start())}"))
    for m in BLOCK_RE.finditer(text):
        opts, body = m.group("opts"), m.group("body")
        trimmed = "trimmed" in opts.split()
        ctx = CTX_RE.search(opts)
        parts = re.split(r"\{%\s*plural\s*%\}", body)
        singular = _block_msg(parts[0], trimmed)
        plural = _block_msg(parts[1], trimmed) if len(parts) > 1 else None
        found.append((ctx.group(2) if ctx else None, singular, plural, f"{rel}:{line_of(m.start())}"))


def from_python(path: Path, rel: str, found: list) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if fn not in PY_FUNCS:
            continue
        strs = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not strs:
            continue
        where = f"{rel}:{node.lineno}"
        if fn in ("pgettext", "pgettext_lazy"):
            if len(strs) >= 2:
                found.append((strs[0], strs[1], None, where))
        elif fn in ("ngettext", "ngettext_lazy"):
            if len(strs) >= 2:
                found.append((None, strs[0], strs[1], where))
        else:
            found.append((None, strs[0], None, where))


def collect() -> list:
    found: list = []
    for d in SCAN_DIRS:
        for p in sorted((BASE / d).rglob("*")):
            if not p.is_file() or SKIP_PARTS & set(p.parts):
                continue
            rel = p.relative_to(BASE).as_posix()
            if p.suffix == ".py":
                from_python(p, rel, found)
            elif p.suffix in (".html", ".txt"):
                from_template(p, rel, found)
    return found


HEADER = """# Hindi translation for UdhaarSaathi.
# Written for small shopkeepers in India: simple, everyday Hindi.
msgid ""
msgstr ""
"Project-Id-Version: UdhaarSaathi\\n"
"Report-Msgid-Bugs-To: \\n"
"Language: hi\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=(n > 1);\\n"
"""


def write_po(lang: str, found: list) -> Path:
    po = BASE / "locale" / lang / "LC_MESSAGES" / "django.po"
    po.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    if po.exists():
        for e in parse_po(po.read_text(encoding="utf-8")):
            old[(e["ctxt"], e["id"])] = e
    merged: dict = {}
    for ctxt, msgid, plural, where in found:
        k = (ctxt, msgid)
        if k not in merged:
            merged[k] = {"plural": plural, "refs": []}
        if where not in merged[k]["refs"]:
            merged[k]["refs"].append(where)
    out = [HEADER]
    new = 0
    for (ctxt, msgid), info in merged.items():
        prev = old.get((ctxt, msgid))
        out.append("")
        out.append("#: " + " ".join(info["refs"][:4]))
        if re.search(r"%\(\w+\)s", msgid):
            out.append("#, python-format")
        if prev and "fuzzy" in prev["flags"]:
            out.append("#, fuzzy")
        if ctxt is not None:
            out.append("msgctxt " + quote(ctxt))
        out.append("msgid " + quote(msgid))
        if info["plural"] is not None:
            out.append("msgid_plural " + quote(info["plural"]))
            for i in range(2):
                out.append(f"msgstr[{i}] " + quote((prev["str"].get(i, "") if prev else "")))
        else:
            out.append("msgstr " + quote(prev["str"].get(0, "") if prev else ""))
        if prev is None:
            new += 1
    po.write_text("\n".join(out) + "\n", encoding="utf-8")
    gone = [k for k in old if k not in merged and k[1]]
    print(f"{po.relative_to(BASE)}: {len(merged)} messages ({new} new, {len(gone)} no longer used)")
    return po


def main(argv: list[str]) -> int:
    lang = argv[argv.index("-l") + 1] if "-l" in argv else "hi"
    po = write_po(lang, collect())
    if "--no-compile" not in argv:
        compile_file(po)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
