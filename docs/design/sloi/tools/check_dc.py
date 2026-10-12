"""Static checks for .dc.html artboards: skeleton, holes, sc-if/sc-for hints, tag balance, JS syntax, blobs."""
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

BLOBS = set("""
0d6e85834c67424ae54a52bafe5d8181 d331ce5caad9824e7e1b348e424378f3 d467e38cc12111ad26a428ff8e19ff4f
a42230ee9ee0732d731d992e8f213a12 6c09a69a8e2638087c2368085b443d0b 9d3bcdec98f61bbf1f44527b585a6d6b
9d0f9548be072420b3dbc97d359c5bd0 18db92cfee0ef754b120d6e4356e1466 600406289118a423fc5df75a99ffc237
7881adf9929cebbcc11c820411d96c4e a4709492f9d6643420ae86dcf42c92ee c70b746e3433f21d6e6fbe47d95693b7
3a65dd36fb256725b6220c8e2348b214 bb6e83990419cf1d61392e723e53bc08 5254188d67a8bd743a5ca31ad8a4aca7
3b92d2f49ff4c421015045369ec75374 79d18dbbe116fd6672a8e0db0b051c68 a6711f28fa01480a29f24df59e7d7986
8fad1e28cda9ce8a515a803326acdc37 8e1e57319f58a678a924e37123698f07 807a4699eb3cb3c48ad856f37c547035
7953287926135bab39a7e6a05d5dbb21 440fd7bac0c461795841fadc4c854440 a2941a07e7d538c66c90a1673382aba4
55dc095b1e619531e47ed4893002f79d
""".split())
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
        "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "stop", "use"}
HOLE = re.compile(r"\{\{(.*?)\}\}", re.S)
PATH = re.compile(r"^\s*[A-Za-z_$][\w$]*(\.[\w$]+)*\s*$")


class Balance(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"line {self.getpos()[0]}: stray </{tag}>")
            return
        top, line = self.stack[-1]
        if top == tag:
            self.stack.pop()
            return
        names = [t for t, _ in self.stack]
        if tag in names:
            while self.stack and self.stack[-1][0] != tag:
                t, l = self.stack.pop()
                self.errors.append(f"line {l}: <{t}> not closed before </{tag}> (line {self.getpos()[0]})")
            self.stack.pop()
        else:
            self.errors.append(f"line {self.getpos()[0]}: stray </{tag}> (open: <{top}> line {line})")


def check(path: Path) -> list[str]:
    s = path.read_text(encoding="utf-8")
    errs = []
    low = s.lower()
    for need in ("<!doctype html>", '<script src="./support.js"></script>', "<x-dc>", "</x-dc>",
                 "data-dc-script", "extends dclogic"):
        if need not in low:
            errs.append(f"missing {need}")
    if "fonts.googleapis.com" in s and re.search(r"fonts\.googleapis\.com[^\"']*&(?!amp;)", s):
        errs.append("google fonts href has raw &")
    m = re.search(r"<x-dc>(.*)</x-dc>", s, re.S)
    markup = m.group(1) if m else ""
    for h in HOLE.findall(markup):
        if not PATH.match(h):
            errs.append(f"hole is not a dotted path: {{{{{h.strip()[:60]}}}}}")
    for tag in re.findall(r"<sc-if\b[^>]*>", markup):
        if "value=" not in tag or "hint-placeholder-val" not in tag:
            errs.append(f"sc-if without value/hint: {tag[:90]}")
    for tag in re.findall(r"<sc-for\b[^>]*>", markup):
        if "list=" not in tag or " as=" not in tag or "hint-placeholder-count" not in tag:
            errs.append(f"sc-for without list/as/hint: {tag[:90]}")
    body = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    b = Balance()
    b.feed(body)
    b.close()
    errs += b.errors[:8]
    for t, l in b.stack[:5]:
        errs.append(f"line {l}: <{t}> never closed")
    for bad in ("<iframe", "<object", "<embed", "innerHTML", "appendChild", "document.", "addEventListener('key",
                'addEventListener("key'):
        if bad in s:
            errs.append(f"forbidden: {bad}")
    for blob in re.findall(r"/_blob/([0-9a-f]+)", s):
        if blob not in BLOBS:
            errs.append(f"unknown blob {blob}")
    js = re.search(r'<script type="text/x-dc"[^>]*>(.*?)</script>', s, re.S)
    if not js:
        errs.append("no x-dc script")
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write("class DCLogic{}\n" + js.group(1))
            name = f.name
        r = subprocess.run(["node", "--check", name], capture_output=True, text=True)
        if r.returncode:
            lines = r.stderr.strip().splitlines()
            msg = next((x for x in lines if "Error" in x), lines[-1] if lines else "?")
            where = next((x for x in lines if x.startswith(name)), "")
            errs.append("JS syntax: " + msg[:160] + (" @" + where.split(":")[-1] if where else ""))
        if not re.search(r"data-props='([^']*)'", s):
            errs.append("no data-props")
    return errs


if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        e = check(Path(p))
        print(("OK   " if not e else "FAIL ") + Path(p).name)
        for x in e:
            print("     - " + x)
        bad += bool(e)
    sys.exit(1 if bad else 0)
