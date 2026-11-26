"""Перевірка зібраного сайту dist/ (після _src/build.py, перед комітом).

  1. JavaScript без помилок; усі блоки, які заповнює скрипт, заповнені; текст є в HTML і без скрипта
  2. знімки екрана: телефон 390px і комп'ютер 1366px → _check/shot-*.png (подивитися!)
  3. усі локальні файли (фото, іконки) існують
  4. каталог: програми без фото / тексту / ціни; посилання go:/open: ведуть на існуючу рубрику/програму
  5. зовнішні посилання відповідають (соцмережі часто блокують роботів — тоді перевірити вручну)
  6. валідатор W3C (сторінка надсилається на validator.w3.org)

Запуск з кореня репозиторію:  python _src/check.py        код виходу 1 = щось не так
"""
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from build import ROOT, DIST, chrome, load_catalog  # noqa: E402

CHK = ROOT / "_check"
PAGE = DIST / "index.html"
fail = False


def ok(s): print("  OK   " + s)
def warn(s): print("  WARN " + s)
def bad(s):
    global fail
    fail = True
    print("  FAIL " + s)


def headless(*args):
    with tempfile.TemporaryDirectory() as prof:
        return subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
                               "--hide-scrollbars", "--allow-file-access-from-files", f"--user-data-dir={prof}", *args],
                              capture_output=True, timeout=120)


CHK.mkdir(exist_ok=True)
html = PAGE.read_text(encoding="utf-8")
url = PAGE.resolve().as_uri()

print("1. JavaScript")
r = headless("--enable-logging=stderr", "--v=0", "--window-size=1280,900", "--virtual-time-budget=5000", "--dump-dom", url)
dom = r.stdout.decode("utf-8")
log = r.stderr.decode("utf-8", "replace")
errs = [l for l in log.splitlines() if re.search(r"CONSOLE.*(error|uncaught)|Uncaught", l, re.I)]
ok("no console errors") if not errs else bad("console errors:\n    " + "\n    ".join(errs[:5]))
for el in ("tabs", "cat", "content", "drop", "sky"):
    filled = re.search(rf'id="{el}"[^>]*>\s*<[a-z]', dom)
    ok(f"#{el} filled") if filled else bad(f"#{el} empty")
static = html.split("<script>")[0]
n = len(re.findall(r'class="card[ "]', static))
ok(f"text without JavaScript: {n} cards in HTML") if n else bad("no cards in HTML before the script (pre-render missing?)")

print("2. Screenshots")
phone = CHK / "phone.html"
phone.write_text(f'<body style="margin:0"><iframe src="{url}" width="390" height="844" style="border:0"></iframe>',
                 encoding="utf-8")
headless("--window-size=390,844", "--virtual-time-budget=5000", f"--screenshot={CHK / 'shot-phone.png'}", phone.as_uri())
headless("--window-size=1366,900", "--virtual-time-budget=5000", f"--screenshot={CHK / 'shot-desktop.png'}", url)
shots = list(CHK.glob("shot-*.png"))
ok(f"saved {CHK}\\shot-*.png") if len(shots) == 2 else bad("screenshots missing")

print("3. Local files")
code = re.sub(r"<!--.*?-->", "", html, flags=re.S)
code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
refs = set(re.findall(r'(?:src|href)="([^"#:$]+)"', code)) | set(re.findall(r'"(pilot2/images/[^"]+)"', code))
missing = []
for f in sorted(refs):
    p = DIST / f
    if not p.is_file():
        missing.append(f)
ok(f"all {len(refs)} local files exist") if not missing else bad("missing: " + ", ".join(missing))

print("4. Catalog")
cats = load_catalog()
for key, label in (("photo", "photo"), ("body", "text"), ("price", "price")):
    lack = [it["title"] for c in cats for s in c["subs"] for it in s["items"] if not it.get(key)]
    ok(f"every tour has a {label}") if not lack else warn(f"{len(lack)} tours without {label}: " + "; ".join(lack))
broken = []
for c in cats:
    for s in c["subs"]:
        for it in s["items"]:
            body = it.get("body", "")
            for g, sub in re.findall(r'data-go="(\d+)"(?: data-sub="(\d+)")?', body):
                g = int(g)
                if g >= len(cats) or (sub and int(sub) >= len(cats[g]["subs"])):
                    broken.append(f"{it['title']} → go:{g},{sub}")
            for o in re.findall(r'data-open="(\d+),(\d+),(\d+)"', body):
                a, b, k = map(int, o)
                try:
                    cats[a]["subs"][b]["items"][k]
                except IndexError:
                    broken.append(f"{it['title']} → open:{a},{b},{k}")
ok("all links inside tour texts lead somewhere") if not broken else bad("broken links: " + "; ".join(broken))

print("5. External links")
for u in sorted(set(re.findall(r'href="(https?://[^"]+)"', static))):
    if "fonts.g" in u:
        continue
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        st = urllib.request.urlopen(req, timeout=15).status
        ok(f"{st} {u}")
    except Exception as e:
        warn(f"{getattr(e, 'code', e)} {u}  (check by hand: social sites often block robots)")

print("6. W3C validator")
try:
    req = urllib.request.Request("https://validator.w3.org/nu/?out=json", data=html.encode("utf-8"),
                                 headers={"Content-Type": "text/html; charset=utf-8", "User-Agent": "Mozilla/5.0"})
    msgs = json.load(urllib.request.urlopen(req, timeout=60))["messages"]
    errs = [m for m in msgs if m["type"] == "error"]
    nwarn = sum(1 for m in msgs if m.get("subType") == "warning")
    ok(f"0 HTML errors, {nwarn} warnings") if not errs else \
        bad(f"{len(errs)} HTML errors:\n    " + "\n    ".join(f"line {m.get('lastLine')}: {m['message']}" for m in errs[:10]))
except Exception as e:
    warn(f"validator did not answer: {e}")

print("\nALL CHECKS PASSED" if not fail else "\nSOME CHECKS FAILED")
sys.exit(1 if fail else 0)
