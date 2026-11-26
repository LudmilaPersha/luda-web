"""Збірка пілота 2 з текстів у папці content/.

content/  →  _src/pilot2.html (шаблон)  →  index.html (головна адреса сайту; фото — з pilot2/images/)
Старі адреси pilot2/ і pilot2/footer/ — сторінки-переадресації на головну.
Після збірки сторінку відкриває Chrome без вікна і зберігає готовий HTML з текстами
(«попередній рендер»): текст видно одразу, навіть без JavaScript.

Запуск з кореня репозиторію:  python _src/build.py
Тільки стандартна бібліотека Python. Chrome: змінна CHROME або стандартний шлях.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
SRC = ROOT / "_src"
OUT = ROOT / "pilot2"
# адреса сайту (для Google і прев'ю посилань)
SITE = "https://segolo.github.io/luda-web/"


# ── Файли з текстами: «шапка» між рядками --- (поле: "значення") + текст ──

def read_md(path):
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    meta, body = {}, text
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).split("\n"):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            k = re.match(r"([A-Za-z_]+):\s*(.*)$", line)
            if not k:
                raise ValueError(f"{path}: незрозумілий рядок у шапці: {line!r}")
            v = k.group(2).strip()
            if v.startswith('"'):
                v = json.loads(v)
            elif v in ("true", "false"):
                v = v == "true"
            meta[k.group(1)] = v
    return meta, body.strip("\n")


# ── Текст → HTML. Правила (як у content/README.md):
#   порожній рядок = новий абзац; новий рядок в абзаці = перенос рядка
#   **жирний**;  "- " = пункт списку;  "> " = рамка з цінами
#   [текст](go:2,4) = посилання на рубрику 2, підрубрику 4;  [текст](open:2,1,0) = на програму
#   рядок, що починається з "<", — HTML як є

def inline(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    def link(m):
        t, u = m.group(1), m.group(2)
        if u.startswith("go:"):
            p = u[3:].split(",")
            return f'<a href="#" data-go="{p[0]}"' + (f' data-sub="{p[1]}"' if len(p) > 1 else "") + f">{t}</a>"
        if u.startswith("open:"):
            return f'<a href="#" data-open="{u[5:]}">{t}</a>'
        return f'<a href="{u}" target="_blank" rel="noopener">{t}</a>'
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)


def md_to_html(text):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if lines[i].startswith(">"):
            j = i
            while j < len(lines) and lines[j].startswith(">"):
                j += 1
            inner = "\n".join(re.sub(r"^> ?", "", l) for l in lines[i:j])
            out.append(f'<div class="pr">{md_to_html(inner).replace(chr(10), "")}</div>')
        elif lines[i].startswith("- "):
            j = i
            while j < len(lines) and lines[j].startswith("- "):
                j += 1
            out.append("<ul>" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines[i:j]) + "</ul>")
        elif lines[i].startswith("<"):
            j = i
            while j < len(lines) and lines[j].strip():
                j += 1
            out.append("\n".join(lines[i:j]))
        else:
            j = i
            while j < len(lines) and lines[j].strip() and not lines[j].startswith(("- ", ">")):
                j += 1
            out.append("<p>" + "<br>".join(inline(l) for l in lines[i:j]) + "</p>")
        i = j
    return "\n".join(out)


# ── Каталог: content/catalog/<рубрика>/<підрубрика>/<програма>.md (порядок — за номером у назві) ──

def load_catalog():
    cats = []
    for cdir in sorted(p for p in (CONTENT / "catalog").iterdir() if p.is_dir()):
        meta, _ = read_md(cdir / "_rubryka.md")
        cat = {k: meta[k] for k in ("title", "photo", "lang") if k in meta}
        if meta.get("pending"):
            cat["pending"] = True
        cat["subs"] = []
        for sdir in sorted(p for p in cdir.iterdir() if p.is_dir()):
            smeta, _ = read_md(sdir / "_pidrubryka.md")
            items = []
            for f in sorted(sdir.glob("*.md")):
                if f.name.startswith("_"):
                    continue
                m, body = read_md(f)
                it = {k: m[k] for k in ("title", "photo", "price") if k in m}
                if body.strip():
                    it["body"] = md_to_html(body)
                items.append(it)
            cat["subs"].append({"title": smeta["title"], "items": items})
        cats.append(cat)
    return cats


def load_featured():
    _, body = read_md(CONTENT / "holovna.md")
    return [l[2:].strip() for l in body.split("\n") if l.startswith("- ")]


def load_page():
    page, _ = read_md(CONTENT / "storinka.md")
    about, about_body = read_md(CONTENT / "pro-nas.md")
    contacts, contacts_body = read_md(CONTENT / "kontakty.md")
    return {
        "h1": page["title"],
        "about_title": about["title"], "about_kicker": about["kicker"],
        "about_body": md_to_html(about_body).replace("\n", "\n    "),
        "contacts_title": contacts["title"],
        "contacts_hint": "<br>".join(contacts_body.split("\n")),
    }


def js(data):
    return json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/")


def assemble():
    cats, featured = load_catalog(), load_featured()
    titles = {it["title"] for c in cats for s in c["subs"] for it in s["items"]}
    missing = [t for t in featured if t not in titles]
    if missing:
        raise SystemExit(f"holovna.md: немає програми з такою назвою: {missing}")
    html = (SRC / "pilot2.html").read_text(encoding="utf-8")
    html = html.replace("/*CATALOG*/", js(cats)).replace("/*FEATURED*/", js(featured))
    for k, v in load_page().items():
        html = html.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{\w+\}\}", html)
    if left:
        raise SystemExit(f"не заповнено: {left}")
    return (SRC / "head.html").read_text(encoding="utf-8").replace("{{site}}", SITE) + html


def chrome():
    for c in (os.environ.get("CHROME"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    raise SystemExit("Chrome не знайдено (задайте змінну CHROME)")


def prerender(path):
    """Відкриває сторінку в Chrome без вікна і повертає HTML після виконання скриптів."""
    with tempfile.TemporaryDirectory() as prof:
        r = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
                            "--allow-file-access-from-files", f"--user-data-dir={prof}", "--window-size=1280,900",
                            "--virtual-time-budget=5000", "--dump-dom", path.resolve().as_uri()],
                           capture_output=True, timeout=120)
    dom = r.stdout.decode("utf-8")
    if 'id="content"' not in dom or "card" not in dom:
        raise SystemExit("попередній рендер не вдався:\n" + r.stderr.decode("utf-8", "replace")[-2000:])
    return dom if dom.lstrip().lower().startswith("<!doctype") else "<!doctype html>\n" + dom


REDIRECT = """<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<!-- Стара адреса пілота 2: сайт тепер на головній адресі -->
<meta name="robots" content="noindex">
<link rel="canonical" href="{site}">
<meta http-equiv="refresh" content="0; url={up}">
<title>Перший магазин вражень</title>
</head>
<body>
<a href="{up}">Перший магазин вражень</a>
<script>location.replace(new URL("{up}", location.href) + location.hash);</script>
</body>
</html>
"""


def main():
    raw = assemble()
    # рендеримо тимчасову копію поруч із фото (pilot2/), потім кладемо на головну з шляхом pilot2/images/
    tmp = OUT / "_prerender.html"
    tmp.write_text(raw, encoding="utf-8", newline="\n")
    try:
        full = raw if "--no-prerender" in sys.argv else prerender(tmp)
    finally:
        tmp.unlink()
    (ROOT / "index.html").write_text(full.replace("images/", "pilot2/images/"), encoding="utf-8", newline="\n")
    for old in (OUT / "index.html", OUT / "footer" / "index.html"):
        old.write_text(REDIRECT, encoding="utf-8", newline="\n")
    print("OK: index.html (+ redirects pilot2/, pilot2/footer/)")


if __name__ == "__main__":
    main()
