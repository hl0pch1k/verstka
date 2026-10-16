"""Сборка примера брендбука VK Cloud: логотипы (SVG + PNG), три примера слайдов (PNG), гайдлайн (PDF) и токены (JSON).

Все файлы собираются из одних данных (палитра, шрифты, правила ниже), поэтому PDF, токены и картинки не расходятся.
Запуск из корня репозитория:

    python3 examples/brandbook-vk-cloud/source/build.py

Нужны: Python 3.9+ с fontTools (контуры букв логотипа из шрифта Play), rsvg-convert (SVG → PNG) и Google Chrome
или Chromium (HTML → PDF и PNG; путь — в переменной CHROME, если он нестандартный). Шрифт Play лежит в `verstka/fonts/` (SIL Open Font License). Шрифтов VK Sans в примере нет: образцы
набраны их заменой — Play, о чём сказано в самом гайдлайне."""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = OUT.parent.parent
FONTS = REPO / "verstka" / "fonts"
DATA = REPO / "examples" / "data-sales-2026"
CHROME = os.environ.get("CHROME") or next(
    (c for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome") or "",
                 shutil.which("chromium") or "", shutil.which("chromium-browser") or "") if c and Path(c).exists()),
    "google-chrome",
)

BRAND = "VK Cloud"
# роль, подпись роли, имя, HEX, RGB, CMYK, где используется
PALETTE = [
    ("primary", "Основной", "VK Blue", "#0077FF", (0, 119, 255), (100, 53, 0, 0), "Фирменные плашки, кнопки, первая серия диаграмм"),
    ("secondary", "Дополнительный", "Cloud Blue", "#2787F5", (39, 135, 245), (84, 45, 0, 4), "Вторая серия диаграмм, подложки иконок"),
    ("text", "Текст", "Night", "#0B1220", (11, 18, 32), (66, 44, 0, 87), "Заголовки и основной текст"),
    ("background", "Фон", "White", "#FFFFFF", (255, 255, 255), (0, 0, 0, 0), "Фон слайдов"),
    ("accent", "Акцент", "Pink", "#FF3985", (255, 57, 133), (0, 78, 48, 0), "Только для главного числа на слайде"),
    ("chart", "Графики", "Sky", "#00C2FF", (0, 194, 255), (100, 24, 0, 0), "Третья серия диаграмм, тонкие линии"),
]
HEX = {p[0]: p[3] for p in PALETTE}
BLUE, CLOUD, NIGHT, WHITE, PINK, SKY = (HEX[k] for k in ("primary", "secondary", "text", "background", "accent", "chart"))
MARGIN = 48
COLUMNS, GUTTER = 12, 24


# ---- логотип ------------------------------------------------------------------------------------------------------------------
def _cross(c1, c2):
    """Верхняя точка пересечения двух окружностей (x, y, r)."""
    (x1, y1, r1), (x2, y2, r2) = c1, c2
    d = math.hypot(x2 - x1, y2 - y1)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0))
    xm, ym = x1 + a * (x2 - x1) / d, y1 + a * (y2 - y1) / d
    pts = [(xm + h * (y2 - y1) / d, ym - h * (x2 - x1) / d), (xm - h * (y2 - y1) / d, ym + h * (x2 - x1) / d)]
    return min(pts, key=lambda p: p[1])


def _arc(c, p, q):
    cx, cy, r = c
    a1 = math.atan2(p[1] - cy, p[0] - cx)
    a2 = math.atan2(q[1] - cy, q[0] - cx)
    span = (a2 - a1) % (2 * math.pi)
    return f"A{r:g} {r:g} 0 {1 if span > math.pi else 0} 1 {q[0]:.2f} {q[1]:.2f}"


def cloud_path() -> str:
    """Облако из трёх дуг и прямого низа в квадрате 120 × 120 (знак логотипа)."""
    a, b, c = (41, 70, 14), (60, 57, 19), (80, 71, 13)
    start, end = (a[0], a[1] + a[2]), (c[0], c[1] + c[2])
    pab, pbc = _cross(a, b), _cross(b, c)
    return f"M{start[0]} {start[1]} {_arc(a, start, pab)} {_arc(b, pab, pbc)} {_arc(c, pbc, end)} Z"


SQUARE = "M28 0H92A28 28 0 0 1 120 28V92A28 28 0 0 1 92 120H28A28 28 0 0 1 0 92V28A28 28 0 0 1 28 0Z"


def wordmark(text: str = BRAND, size: float = 77.0, x0: float = 148.0, baseline: float = 85.0) -> tuple[str, float]:
    """Контуры надписи шрифтом Play Bold (без зависимости от установленных шрифтов) и правый край надписи."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    font = TTFont(str(FONTS / "Play-Bold.ttf"))
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    k = size / font["head"].unitsPerEm
    pen = SVGPathPen(gs)
    x = x0
    for ch in text:
        g = cmap[ord(ch)]
        gs[g].draw(TransformPen(pen, (k, 0, 0, -k, x, baseline)))
        x += hmtx[g][0] * k
    return pen.getCommands(), x


def logo_svg(variant: str) -> str:
    cloud = cloud_path()
    if variant == "mark":
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">'
                f'<title>{BRAND} — знак</title><path d="{SQUARE}" fill="{BLUE}"/><path d="{cloud}" fill="{WHITE}"/></svg>')
    text, right = wordmark()
    w = math.ceil(right + 4)
    if variant == "primary":
        mark = f'<path d="{SQUARE}" fill="{BLUE}"/><path d="{cloud}" fill="{WHITE}"/>'
        ink = NIGHT
    else:
        ink = WHITE if variant == "white" else NIGHT
        mark = f'<path d="{SQUARE} {cloud}" fill="{ink}" fill-rule="evenodd"/>'
    titles = {"primary": "основной", "white": "белый", "mono": "монохром"}
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 120" width="{w}" height="120">'
            f'<title>{BRAND} — {titles[variant]}</title>{mark}<path d="{text}" fill="{ink}"/></svg>')


def build_logos() -> None:
    d = OUT / "logos"
    d.mkdir(exist_ok=True)
    for v in ("primary", "white", "mark", "mono"):
        svg = d / f"{v}.svg"
        svg.write_text(logo_svg(v), encoding="utf-8")
        size = ["-w", "512", "-h", "512"] if v == "mark" else ["-h", "240"]
        subprocess.run(["rsvg-convert", *size, "-o", str(d / f"{v}.png"), str(svg)], check=True)


def inline_logo(variant: str, height: int, extra: str = "") -> str:
    svg = logo_svg(variant)
    return svg.replace("<svg ", f'<svg style="height:{height}px;width:auto;display:block{";" + extra if extra else ""}" ', 1)


# ---- общий стиль --------------------------------------------------------------------------------------------------------------
def font_css() -> str:
    return f"""
@font-face {{ font-family: 'Play'; font-weight: 400; src: url('{(FONTS / "Play-Regular.ttf").as_uri()}'); }}
@font-face {{ font-family: 'Play'; font-weight: 700; src: url('{(FONTS / "Play-Bold.ttf").as_uri()}'); }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ font-family: 'Play', sans-serif; color: {NIGHT}; background: {WHITE}; -webkit-font-smoothing: antialiased; }}
"""


def chrome(args: list[str]) -> None:
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                        f"--user-data-dir={prof}", "--virtual-time-budget=4000", *args], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---- примеры слайдов ----------------------------------------------------------------------------------------------------------
def revenue() -> list[tuple[str, float]]:
    with open(DATA / "Выручка по месяцам.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))[1:]
    return [(r[0], float(r[1])) for r in rows]


MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def line_chart(w: int, h: int, *, big: bool = True) -> str:
    """Линейный график выручки: линия — основной цвет, последняя точка и главное число — акцент; у оси значений — единица
    «млн ₽» (правило брендбука: оси и единицы подписаны всегда)."""
    pts = revenue()
    pad_l, pad_r, pad_t, pad_b = (88, 150, 52, 56) if big else (44, 80, 28, 30)
    lo, hi = 280, 440
    xs = [pad_l + i * (w - pad_l - pad_r) / (len(pts) - 1) for i in range(len(pts))]
    ys = [pad_t + (hi - v) * (h - pad_t - pad_b) / (hi - lo) for _, v in pts]
    fs = 22 if big else 12
    grid = ""
    for v in range(lo, hi + 1, 40):
        y = pad_t + (hi - v) * (h - pad_t - pad_b) / (hi - lo)
        grid += f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y:.1f}" y2="{y:.1f}" stroke="{NIGHT}" stroke-opacity=".08" stroke-width="{2 if big else 1}"/>'
        grid += f'<text x="{pad_l - 16}" y="{y + fs * .35:.1f}" font-size="{fs}" text-anchor="end" fill="{NIGHT}" fill-opacity=".55">{v}</text>'
    unit = (f'<text x="{0 if not big else pad_l - 16}" y="{pad_t - fs * 1.1:.1f}" font-size="{fs}" text-anchor="{"start" if not big else "end"}" '
            f'fill="{NIGHT}" fill-opacity=".55">млн ₽</text>')
    labels = ""
    for i, (d, _) in enumerate(pts):
        y, m = int(d[:4]), int(d[5:7])
        if m in (1, 4, 7, 10):
            lab = f"{MONTHS[m - 1]} {str(y)[2:]}" if m == 1 else MONTHS[m - 1]
            labels += f'<text x="{xs[i]:.1f}" y="{h - pad_b + fs * 1.6:.1f}" font-size="{fs}" text-anchor="middle" fill="{NIGHT}" fill-opacity=".55">{lab}</text>'
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    year_ago = xs[-13], ys[-13]
    r = 9 if big else 5
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" font-family="Play">'
            f'{grid}{unit}{labels}'
            f'<polyline points="{line}" fill="none" stroke="{BLUE}" stroke-width="{5 if big else 3}" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{year_ago[0]:.1f}" cy="{year_ago[1]:.1f}" r="{r - 2}" fill="{WHITE}" stroke="{BLUE}" stroke-width="{3 if big else 2}"/>'
            f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="{r}" fill="{PINK}"/>'
            f'<text x="{xs[-1] + (18 if big else 10):.1f}" y="{ys[-1] + (14 if big else 7):.1f}" font-size="{48 if big else 26}" font-weight="700" fill="{PINK}">+23%</text>'
            f'</svg>')


def quarter_strip() -> str:
    """Нижняя треть слайда «Ключевые показатели»: выручка по кварталам (сумма трёх месяцев из той же таблицы), последний
    квартал — основным цветом, прежние — светлым тоном; значения подписаны над столбцами, единица — в заголовке."""
    q: dict[tuple[int, int], float] = {}
    for d, v in revenue():
        key = (int(d[:4]), (int(d[5:7]) - 1) // 3 + 1)
        q[key] = q.get(key, 0) + v
    keys = sorted(q)
    top = max(q.values())
    roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
    cols = ""
    for k in keys:
        last = k == keys[-1]
        value = f"{q[k]:,.0f}".replace(",", "&nbsp;")
        fill = BLUE if last else "rgba(39,135,245,.26)"
        cols += (f'<div class="qc"><span class="qv" style="color:{BLUE if last else NIGHT}">{value}</span>'
                 f'<i style="height:{round(120 * q[k] / top)}px;background:{fill}"></i>'
                 f'<span class="ql">{roman[k[1]]} кв. {str(k[0])[2:]}</span></div>')
    return (f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:716px">'
            f'<div style="font-size:30px;opacity:.6;margin-bottom:22px">Выручка по кварталам, млн ₽</div>'
            f'<div class="qs">{cols}</div></div>')


def slide_html(body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>{font_css()}
body {{ width: 1920px; height: 1080px; overflow: hidden; position: relative; }}
.logo {{ position: absolute; right: {MARGIN}px; bottom: {MARGIN}px; }}
.src {{ position: absolute; left: {MARGIN}px; bottom: {MARGIN}px; font-size: 22px; opacity: .55; }}
h1 {{ font-weight: 700; letter-spacing: -0.01em; }}
.qs {{ display: flex; align-items: flex-end; gap: {GUTTER * 2}px; height: 204px; border-bottom: 2px solid rgba(11,18,32,.12); padding: 0 8px; }}
.qc {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 10px; position: relative; padding-bottom: 44px; }}
.qc i {{ display: block; width: 100%; max-width: 150px; border-radius: 10px 10px 0 0; }}
.qv {{ font-size: 30px; font-weight: 700; }}
.ql {{ position: absolute; bottom: 10px; font-size: 24px; opacity: .6; }}
</style></head><body>{body}</body></html>"""


def build_slides(tmp: Path) -> None:
    d = OUT / "slides"
    d.mkdir(exist_ok=True)
    cover = slide_html(f"""
<div style="position:absolute;left:0;top:0;width:1152px;height:1080px;padding:{MARGIN}px">
  <div style="font-size:28px;color:{BLUE};font-weight:700">VK Cloud · Правление · 2026</div>
  <h1 style="position:absolute;left:{MARGIN}px;top:380px;width:980px;font-size:104px;line-height:1.05">Продажи VK Cloud в&nbsp;2026 году</h1>
  <div style="position:absolute;left:{MARGIN}px;top:640px;font-size:40px;opacity:.7">Итоги девяти месяцев для правления</div>
</div>
<div style="position:absolute;left:1152px;top:0;width:768px;height:1080px;background:{BLUE}">
  <svg viewBox="0 0 120 120" style="position:absolute;left:150px;top:240px;width:520px;height:520px;opacity:.14"><path d="{cloud_path()}" fill="{WHITE}"/></svg>
</div>
<div class="logo">{inline_logo("white", 56)}</div>""")
    chart = slide_html(f"""
<h1 style="position:absolute;left:{MARGIN}px;top:{MARGIN + 24}px;font-size:72px;line-height:1.1">Выручка выросла на 23% к сентябрю</h1>
<div style="position:absolute;left:{MARGIN}px;top:200px;font-size:30px;opacity:.6">Выручка по месяцам, млн ₽ · январь 2025 — сентябрь 2026</div>
<div style="position:absolute;left:{MARGIN}px;top:290px">{line_chart(1824, 640)}</div>
<div class="src">Источник: Выручка по месяцам.csv</div>
<div class="logo">{inline_logo("primary", 44)}</div>""")
    cards = [("1,24 млрд ₽", "выручка за квартал", "+23% к III кв. 2025", True), ("3 480", "активных клиентов", "+18%", False),
             ("356 тыс. ₽", "средний чек", "+4%", False), ("52", "NPS", "+6 пунктов", False)]
    cells = "".join(
        f'<div style="padding:40px 36px;border-radius:24px;background:{"#F2F7FF" if main else "#F6F7F9"};height:340px;position:relative">'
        f'<div style="height:96px;display:flex;align-items:flex-end;font-size:{76 if main else 64}px;line-height:1;font-weight:700;color:{PINK if main else NIGHT};white-space:nowrap">{v}</div>'
        f'<div style="font-size:30px;margin-top:20px;opacity:.7">{lab}</div>'
        f'<div style="position:absolute;left:36px;bottom:40px;font-size:30px;font-weight:700;color:{BLUE}">{chg}</div></div>'
        for v, lab, chg, main in cards)
    numbers = slide_html(f"""
<h1 style="position:absolute;left:{MARGIN}px;top:{MARGIN + 24}px;font-size:72px;line-height:1.1">Выручка растёт быстрее клиентской базы</h1>
<div style="position:absolute;left:{MARGIN}px;top:200px;font-size:30px;opacity:.6">III квартал 2026 года, сравнение с III кварталом 2025 года</div>
<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:300px;display:grid;grid-template-columns:1.35fr 1fr 1fr 1fr;gap:{GUTTER}px">{cells}</div>
{quarter_strip()}
<div class="src">Источник: Итоги квартала.txt, Выручка по месяцам.csv</div>
<div class="logo">{inline_logo("primary", 44)}</div>""")
    for name, html in (("01-oblozhka", cover), ("02-grafik", chart), ("03-pokazateli", numbers)):
        src = tmp / f"{name}.html"
        src.write_text(html, encoding="utf-8")
        chrome([f"--screenshot={d / (name + '.png')}", "--window-size=1920,1080", "--force-device-scale-factor=1", src.as_uri()])


# ---- гайдлайн PDF -------------------------------------------------------------------------------------------------------------
PAGES_TOTAL = 12


def page(n: int, section: str, title: str, body: str, *, dark: bool = False) -> str:
    return f"""<section class="page{' dark' if dark else ''}">
<header><span>{BRAND} · Брендбук</span><span>{section}</span></header>
<h2><b>{n:02d}</b>{title}</h2>
{body}
<footer><span>{n} / {PAGES_TOTAL}</span>{inline_logo("mark", 28)}</footer>
</section>"""


def guideline_html(slides_dir: Path, logos_dir: Path) -> str:
    rows = "".join(
        f'<div class="row"><i style="background:{hx}"></i><span class="role">{rl}</span><span class="nm">{nm}</span>'
        f'<span class="hx">{hx}</span><span>{" ".join(map(str, rgb))}</span><span>{" ".join(map(str, cmyk))}</span><span class="use">{use}</span></div>'
        for _, rl, nm, hx, rgb, cmyk, use in PALETTE)
    big = "".join(f'<div class="sw" style="background:{hx};flex:{fl}"><span style="color:{ink}">{nm} · {fl} %</span></div>'
                  for nm, hx, fl, ink in (("White", WHITE, 56, NIGHT), ("Night", NIGHT, 20, WHITE), ("VK Blue", BLUE, 14, WHITE),
                                          ("Cloud Blue", CLOUD, 5, WHITE), ("Sky", SKY, 4, NIGHT), ("Pink", PINK, 1, WHITE)))
    pairs = "".join(f'<div class="pair" style="background:{bg};color:{fg}"><b>Аа</b><span>{t}</span></div>'
                    for bg, fg, t in ((WHITE, NIGHT, "Night на White — контраст 18,7 : 1"), (BLUE, WHITE, "White на VK Blue — 4,1 : 1"),
                                      (NIGHT, WHITE, "White на Night — 18,7 : 1"), (WHITE, PINK, "Pink на White — 3,4 : 1, для крупных чисел")))
    logo_cards = "".join(
        f'<div class="lgc"><figure style="background:{bg}"><img src="{(logos_dir / (f + ".png")).as_uri()}" style="height:{hgt}px"></figure>'
        f'<figcaption><b>{t}</b><span>{d}</span><code>logos/{f}.svg · .png</code></figcaption></div>'
        for f, bg, hgt, t, d in (("primary", WHITE, 64, "Основной", "на белом и светлом фоне"),
                                 ("white", BLUE, 64, "Белый", "на синем и тёмном фоне, на фото"),
                                 ("mark", "#F6F7F9", 84, "Знак", "когда места мало: аватар, иконка"),
                                 ("mono", WHITE, 64, "Монохром", "для печати в один цвет")))
    order = "".join(f'<div class="ord"><i style="background:{hx}"></i><span>{i}</span><b>{nm}</b><span class="hx">{hx}</span></div>'
                    for i, (nm, hx) in enumerate((("VK Blue", BLUE), ("Cloud Blue", CLOUD), ("Sky", SKY), ("Night", NIGHT)), 1))
    bars = [("Москва", 41), ("Санкт-Петербург", 17), ("Казань", 11), ("Новосибирск", 9), ("Краснодар", 8)]
    x0, k = 150, 7  # начало осей и масштаб: 1 % = 7 px
    axis = "".join(f'<line x1="{x0 + t * k}" x2="{x0 + t * k}" y1="0" y2="142" stroke="{NIGHT}" stroke-opacity=".08"/>'
                   f'<text x="{x0 + t * k}" y="160" font-size="13" text-anchor="middle" fill="{NIGHT}" fill-opacity=".55">{t}</text>' for t in (0, 10, 20, 30, 40))
    bar_svg = axis + "".join(f'<text x="0" y="{19 + i * 28}" font-size="15" fill="{NIGHT}">{c}</text>'
                             f'<rect x="{x0}" y="{4 + i * 28}" width="{v * k}" height="20" rx="4" fill="{BLUE}"/>'
                             f'<text x="{x0 + 10 + v * k}" y="{19 + i * 28}" font-size="15" fill="{NIGHT}" fill-opacity=".7">{v}%</text>'
                             for i, (c, v) in enumerate(bars))
    bar_svg += f'<text x="{x0}" y="180" font-size="13" fill="{NIGHT}" fill-opacity=".55">Доля выручки, % от итога</text>'
    cols = "".join(f'<i style="left:{48 + k * (1824 + GUTTER) / COLUMNS}px;width:{(1824 - GUTTER * (COLUMNS - 1)) / COLUMNS}px"></i>'
                   for k in range(COLUMNS))

    def mini(ok: bool, kind: str) -> str:
        """Схема «как правильно / как нельзя» векторами (не картинками)."""
        frame = '<rect x="1" y="1" width="318" height="178" rx="10" fill="#FFFFFF" stroke="#0B1220" stroke-opacity=".12"/>'
        logo_ok = f'<g transform="translate(262 148) scale(.2)"><path d="{SQUARE}" fill="{BLUE}"/><path d="{cloud_path()}" fill="{WHITE}"/></g>'
        lines = (f'<rect x="16" y="18" width="190" height="14" rx="3" fill="{NIGHT}"/>'
                 f'<rect x="16" y="42" width="140" height="8" rx="3" fill="{NIGHT}" fill-opacity=".3"/>')
        if kind == "logo":
            body = (lines + logo_ok if ok else lines +
                    f'<g transform="translate(110 70) scale(.7 .32) rotate(-8)"><path d="{SQUARE}" fill="{PINK}"/><path d="{cloud_path()}" fill="{WHITE}"/></g>')
        elif kind == "accent":
            nums = [("1,24", PINK if ok else PINK), ("3 480", NIGHT if ok else PINK), ("356", NIGHT if ok else PINK)]
            body = lines + "".join(f'<text x="{16 + i * 102}" y="120" font-size="30" font-weight="700" fill="{c}" font-family="Play">{t}</text>'
                                   for i, (t, c) in enumerate(nums)) + logo_ok
        else:
            pad = 16 if ok else 2
            body = (f'<rect x="{pad}" y="{pad + 2}" width="190" height="14" rx="3" fill="{NIGHT}"/>'
                    f'<rect x="{pad}" y="{pad + 26}" width="140" height="8" rx="3" fill="{NIGHT}" fill-opacity=".3"/>'
                    f'<rect x="{pad}" y="70" width="{320 - 2 * pad}" height="60" rx="6" fill="{BLUE}" fill-opacity=".16"/>'
                    + (logo_ok if ok else f'<g transform="translate(290 152) scale(.24)"><path d="{SQUARE}" fill="{BLUE}"/><path d="{cloud_path()}" fill="{WHITE}"/></g>'))
            if ok:
                body += '<rect x="16" y="16" width="288" height="148" fill="none" stroke="#00C2FF" stroke-dasharray="4 4"/>'
        return f'<svg viewBox="0 0 320 180" width="320" height="180">{frame}{body}</svg>'

    dos = [
        (True, "logo", "Логотип — в правом нижнем углу, на расстоянии 48 px от краёв слайда."),
        (False, "logo", "Не растягивайте, не поворачивайте и не перекрашивайте логотип."),
        (True, "accent", "Акцентом выделено одно главное число, остальные цифры — цветом Night."),
        (False, "accent", "Не выделяйте акцентом несколько чисел: акцент теряет силу."),
        (True, "grid", "Текст и диаграммы держите внутри полей 48 px."),
        (False, "grid", "Не ставьте текст и логотип вплотную к краю слайда."),
    ]
    do_cards = "".join(f'<div class="do {"ok" if ok else "no"}">{mini(ok, k)}<b>{"Так правильно" if ok else "Так нельзя"}</b><p>{t}</p></div>'
                       for ok, k, t in dos)
    shots = "".join(f'<figure class="shot"><img src="{(slides_dir / f).as_uri()}"><figcaption><b>{t}</b><span>{d}</span></figcaption></figure>'
                    for f, t, d in (("01-oblozhka.png", "Обложка", "заголовок слева, фирменный блок справа"),
                                    ("02-grafik.png", "График с выводом", "заголовок — вывод, главное число — акцентом"),
                                    ("03-pokazateli.png", "Ключевые показатели", "одна карточка главная, остальные спокойные")))

    pages = [
        f"""<section class="page cover">
<div class="cv-l">
  <div class="kicker">Правила оформления презентаций</div>
  <h1>Брендбук VK Cloud</h1>
  <p class="lead">Цвета, шрифты, логотип, сетка и диаграммы для презентаций компании</p>
  <p class="ver">Версия 1.0 · октябрь 2026</p>
  <p class="note">Учебный пример для проверки Verstka. Бренд, цвета, логотипы и правила условные — это не официальный брендбук VK Cloud.</p>
</div>
<div class="cv-r"><svg viewBox="0 0 120 120" style="position:absolute;left:820px;top:150px;width:340px;height:340px;opacity:.14"><path d="{cloud_path()}" fill="{WHITE}"/></svg>{inline_logo("white", 72)}</div>
</section>""",
        page(2, "Введение", "Как пользоваться брендбуком", f"""
<div class="two">
<div>
<p class="lead">Брендбук описывает, как выглядят презентации VK Cloud. Им пользуются дизайнеры, авторы презентаций и Verstka — генератор презентаций, который читает этот файл и применяет правила к шаблону.</p>
<ol class="toc"><li><b>03</b>Палитра</li><li><b>04</b>Пропорции и сочетания</li><li><b>05</b>Шрифты</li><li><b>06</b>Логотип</li>
<li><b>07</b>Охранное поле и место логотипа</li><li><b>08</b>Сетка и поля</li><li><b>09</b>Диаграммы</li><li><b>10</b>Как правильно и как нельзя</li>
<li><b>11</b>Примеры слайдов</li><li><b>12</b>Файлы брендбука</li></ol>
</div>
<div class="box">
<div class="cap">Главное на одной странице</div>
<p>Логотип — в правом нижнем углу.</p>
<p>Поля — 48 px.</p>
<p>Акцент — только для главного числа.</p>
</div>
</div>"""),
        page(3, "Цвет", "Палитра", f"""
<p class="lead">Шесть цветов. Первым узнаётся VK Blue, текст набирается цветом Night, акцента Pink на слайде очень мало.</p>
<div class="tbl"><div class="row head"><i></i><span>Роль</span><span>Имя</span><span>HEX</span><span>RGB</span><span>CMYK</span><span>Где используется</span></div>{rows}</div>
<p class="small">Значения CMYK даны для печати без цветового профиля.</p>"""),
        page(4, "Цвет", "Пропорции и сочетания", f"""
<p class="lead">Слайд в основном белый. Синий — там, где нужно узнавание, акцент — точечно.</p>
<div class="prop">{big}</div>
<div class="pairs">{pairs}</div>"""),
        page(5, "Типографика", "Шрифты", f"""
<div class="two">
<div class="spec"><div class="cap">Заголовки</div><div class="face" style="font-weight:700">Аа Бб Вв</div>
<p class="fl">Заголовки — VK Sans Display, Bold 700</p><p class="small">Заголовки слайдов, крупные числа, обложки.</p></div>
<div class="spec"><div class="cap">Основной текст</div><div class="face">Аа Бб Вв</div>
<p class="fl">Основной текст — VK Sans Text, Regular 400</p><p class="small">Текст, подписи, таблицы и диаграммы.</p></div>
</div>
<div class="box wide"><p>Замена — Play. Если шрифтов VK Sans нет на компьютере, заголовки набирайте Play Bold, текст — Play Regular. Образцы на этой странице набраны Play.</p></div>
<div class="scale"><span><b style="font-size:40px">Заголовок слайда</b><em>40 pt</em></span><span><b style="font-size:24px;font-weight:400">Подзаголовок</b><em>24 pt</em></span>
<span><b style="font-size:18px;font-weight:400">Основной текст</b><em>18 pt</em></span><span><b style="font-size:14px;font-weight:400">Подписи и сноски</b><em>14 pt</em></span></div>"""),
        page(6, "Логотип", "Логотип", f"""
<p class="lead">Четыре версии логотипа. Берите готовые файлы из папки logos и не перерисовывайте логотип.</p>
<div class="logos">{logo_cards}</div>"""),
        page(7, "Логотип", "Охранное поле и место логотипа", f"""
<div class="two">
<div class="clear">
  <div class="cs"><div class="lgbox">{inline_logo("primary", 64)}</div><span class="x" style="left:0;top:0">x</span><span class="x" style="right:0;bottom:0">x</span></div>
  <p class="xcap">x — высота знака</p>
</div>
<div>
<p class="lead">Охранное поле — не меньше высоты знака со всех сторон: в нём нет текста и других элементов.</p>
<p>Минимальная высота логотипа на слайде 1920 × 1080 — 32 px, на обложке и в финале — 64 px.</p>
<div class="spot"><div class="mini"><span class="ln"></span><span class="ln s"></span><div class="lgpos">{inline_logo("mark", 18)}</div></div>
<p>Место логотипа на слайде — правый нижний угол, на расстоянии 48 px от краёв.</p></div>
</div>
</div>"""),
        page(8, "Сетка", "Сетка и поля", f"""
<div class="two">
<div class="gridpic"><div class="sl">{cols}<div class="m"></div><span class="t48">48</span><span class="t24">24</span></div></div>
<div>
<p>Слайд — 1920 × 1080 px (16:9).</p>
<p class="lead strong">Поля — 48 px со всех сторон.</p>
<p class="lead strong">Сетка — 12 колонок, промежуток 24 px.</p>
<p>Заголовок — в верхней строке сетки, логотип — в правом нижнем углу внутри полей.</p>
</div>
</div>"""),
        page(9, "Данные", "Диаграммы", f"""
<div class="two">
<div>
<p class="ordcap">Используйте цвета диаграмм по порядку палитры:</p>
<div class="order">{order}</div>
<p class="lead strong">Акцент — только для главного числа.</p>
<p>На графике это одна точка или один столбец с выводом.</p>
<p>Всегда подписывайте оси и единицы; источник данных — под диаграммой.</p>
<p>Не больше шести долей в кольцевой диаграмме, остальное — в «Другое».</p>
</div>
<div class="charts">
<div class="ch"><div class="cap">Выручка выросла на 23% к сентябрю</div>{line_chart(560, 146, big=False)}<div class="srcl">Источник: Выручка по месяцам.csv</div></div>
<div class="ch"><div class="cap">Доля выручки по регионам</div><svg viewBox="0 0 520 186" width="520" height="186" font-family="Play">{bar_svg}</svg><div class="srcl">Источник: Регионы.xlsx</div></div>
</div>
</div>"""),
        page(10, "Правила", "Как правильно и как нельзя", f'<div class="dos">{do_cards}</div>'),
        page(11, "Примеры", "Примеры слайдов", f'<div class="shots">{shots}</div>'),
        page(12, "Файлы", "Файлы брендбука", """
<div class="two">
<div class="files">
<p><code>guideline.pdf</code>этот документ</p>
<p><code>tokens.json</code>токены в формате W3C Design Tokens</p>
<p><code>tokens-studio.json</code>экспорт Tokens Studio для Figma</p>
<p><code>logos/</code>четыре логотипа, SVG и PNG</p>
<p><code>slides/</code>три примера слайдов, PNG</p>
</div>
<div class="box">
<div class="cap">Как Verstka читает брендбук</div>
<p>Из PDF — по тексту: цвета с ролями, шрифты, поля, место логотипа и правила. Модель, если включена, смотрит страницы и уточняет роли.</p>
<p>Из токенов JSON — точно, по именам токенов.</p>
<p>Из папки или архива — всё сразу: токены, PDF, логотипы и примеры слайдов.</p>
</div>
</div>"""),
    ]
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Брендбук VK Cloud</title><style>{font_css()}
@page {{ size: 1280px 720px; margin: 0; }}
.page {{ width: 1280px; height: 720px; position: relative; padding: 48px 64px 0; page-break-after: always; overflow: hidden; }}
.page:last-child {{ page-break-after: auto; }}
header {{ display: flex; justify-content: space-between; font-size: 13px; opacity: .5; letter-spacing: .02em; }}
footer {{ position: absolute; left: 64px; right: 48px; bottom: 40px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }}
footer span {{ opacity: .5; }}
h2 {{ font-size: 40px; font-weight: 700; margin: 28px 0 24px; letter-spacing: -0.01em; display: flex; align-items: baseline; gap: 20px; }}
h2 b {{ font-size: 18px; color: {BLUE}; }}
p {{ font-size: 18px; line-height: 1.45; margin-bottom: 12px; }}
.lead {{ font-size: 22px; line-height: 1.4; max-width: 980px; }}
.strong {{ font-weight: 700; }}
.small {{ font-size: 14px; opacity: .6; }}
.cap {{ font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: {BLUE}; font-weight: 700; margin-bottom: 14px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 48px; }}
.box {{ background: #F2F7FF; border-radius: 16px; padding: 28px 32px; }}
.box p {{ font-size: 22px; font-weight: 700; margin-bottom: 10px; }}
.box.wide {{ margin: 20px 0; padding: 18px 28px; }}
.box.wide p {{ font-size: 18px; font-weight: 400; margin: 0; }}
code {{ font-family: 'Play'; font-size: 14px; color: {BLUE}; }}
.cover {{ padding: 0; display: grid; grid-template-columns: 700px 580px; }}
.cv-l {{ padding: 64px; position: relative; }}
.cv-r {{ background: {BLUE}; display: flex; align-items: flex-end; justify-content: flex-end; padding: 48px; }}
.kicker {{ font-size: 16px; color: {BLUE}; font-weight: 700; letter-spacing: .04em; margin-top: 150px; }}
.cover h1 {{ font-size: 64px; line-height: 1.05; margin: 18px 0 20px; letter-spacing: -0.015em; }}
.cover .lead {{ font-size: 22px; opacity: .75; max-width: 520px; }}
.ver {{ font-size: 16px; opacity: .55; }}
.note {{ position: absolute; left: 64px; bottom: 40px; width: 560px; font-size: 13px; opacity: .55; line-height: 1.4; margin: 0; }}
.toc {{ list-style: none; columns: 2; margin-top: 24px; }}
.toc li {{ font-size: 17px; margin-bottom: 12px; }}
.toc b {{ color: {BLUE}; margin-right: 10px; font-size: 14px; }}
.tbl {{ margin-top: 8px; }}
.row {{ display: grid; grid-template-columns: 56px 150px 120px 110px 120px 130px 1fr; align-items: center; gap: 0 12px; padding: 6px 0; border-bottom: 1px solid rgba(11,18,32,.08); font-size: 16px; }}
.row i {{ display: block; width: 44px; height: 40px; border-radius: 10px; box-shadow: inset 0 0 0 1px rgba(11,18,32,.12); }}
.row.head {{ font-size: 12px; text-transform: uppercase; letter-spacing: .06em; opacity: .5; padding: 0 0 6px; }}
.row.head i {{ height: 0; box-shadow: none; }}
.row .role {{ font-weight: 700; }}
.row .use {{ opacity: .7; font-size: 15px; }}
.prop {{ display: flex; height: 190px; border-radius: 16px; overflow: hidden; box-shadow: inset 0 0 0 1px rgba(11,18,32,.1); margin: 8px 0 28px; }}
.sw {{ display: flex; align-items: flex-end; padding: 14px; font-size: 14px; white-space: nowrap; overflow: hidden; }}
.sw:nth-child(n+4) span {{ display: none; }}
.pairs {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
.pair {{ height: 150px; border-radius: 14px; padding: 18px; box-shadow: inset 0 0 0 1px rgba(11,18,32,.1); display: flex; flex-direction: column; justify-content: space-between; }}
.pair b {{ font-size: 40px; }}
.pair span {{ font-size: 14px; }}
.spec {{ border-radius: 16px; padding: 24px 28px; box-shadow: inset 0 0 0 1px rgba(11,18,32,.1); }}
.face {{ font-size: 72px; line-height: 1; margin: 4px 0 16px; }}
.fl {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
.scale {{ display: flex; gap: 40px; align-items: baseline; }}
.scale span {{ display: flex; flex-direction: column; gap: 4px; }}
.scale em {{ font-style: normal; font-size: 13px; opacity: .5; }}
.logos {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
.lgc figure {{ height: 220px; border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: inset 0 0 0 1px rgba(11,18,32,.1); padding: 16px; }}
.lgc img {{ max-width: 100%; }}
.lgc figcaption {{ margin-top: 14px; display: flex; flex-direction: column; gap: 4px; font-size: 15px; }}
.lgc figcaption b {{ font-size: 18px; }}
.clear {{ display: flex; align-items: center; justify-content: center; height: 470px; background: #F6F7F9; border-radius: 16px; }}
.clear {{ flex-direction: column; }}
.cs {{ position: relative; padding: 64px; background: rgba(0,194,255,.14); outline: 1px dashed rgba(0,119,255,.6); }}
.cs .lgbox {{ background: {WHITE}; }}
.cs .x {{ position: absolute; width: 64px; height: 64px; display: flex; align-items: center; justify-content: center; font-size: 18px; color: {BLUE}; }}
.xcap {{ font-size: 14px; opacity: .6; margin: 18px 0 0; }}
.spot {{ display: flex; gap: 20px; align-items: center; margin-top: 18px; }}
.spot p {{ margin: 0; }}
.mini {{ flex: none; width: 192px; height: 108px; border-radius: 8px; box-shadow: inset 0 0 0 1px rgba(11,18,32,.15); position: relative; }}
.mini .ln {{ position: absolute; left: 5px; top: 8px; width: 110px; height: 8px; border-radius: 2px; background: {NIGHT}; }}
.mini .ln.s {{ top: 22px; width: 70px; opacity: .3; }}
.mini .lgpos {{ position: absolute; right: 5px; bottom: 5px; }}
.gridpic {{ display: flex; align-items: center; }}
.sl {{ width: 1920px; height: 1080px; transform: scale(.29); transform-origin: 0 0; position: relative; box-shadow: inset 0 0 0 3px rgba(11,18,32,.2); border-radius: 24px; margin-bottom: -767px; margin-right: -1363px; }}
.sl i {{ position: absolute; top: 48px; bottom: 48px; background: rgba(0,119,255,.12); }}
.sl .m {{ position: absolute; inset: 48px; outline: 4px dashed rgba(255,57,133,.6); }}
.sl .t48, .sl .t24 {{ position: absolute; font-size: 48px; font-weight: 700; color: {PINK}; }}
.sl .t48 {{ left: 60px; top: 60px; }}
.sl .t24 {{ left: 180px; bottom: 70px; color: {BLUE}; }}
.ordcap {{ font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
.order {{ margin: 0 0 22px; }}
.ord {{ display: grid; grid-template-columns: 36px 24px 140px 1fr; align-items: center; gap: 10px; padding: 6px 0; font-size: 17px; }}
.ord i {{ width: 28px; height: 28px; border-radius: 6px; display: block; }}
.ord .hx {{ opacity: .6; }}
.charts {{ display: flex; flex-direction: column; gap: 14px; margin-top: -8px; }}
.ch {{ border-radius: 16px; padding: 12px 18px; box-shadow: inset 0 0 0 1px rgba(11,18,32,.1); }}
.ch .cap {{ color: {NIGHT}; text-transform: none; letter-spacing: 0; font-size: 16px; margin-bottom: 6px; }}
.srcl {{ font-size: 12px; opacity: .55; margin-top: 2px; }}
.dos {{ display: grid; grid-template-columns: repeat(3, 1fr); grid-auto-flow: column; grid-template-rows: auto auto; gap: 16px 40px; margin-top: -6px; }}
.do svg {{ display: block; width: 256px; height: 144px; }}
.do b {{ display: block; font-size: 14px; margin: 8px 0 2px; }}
.do.ok b {{ color: {BLUE}; }}
.do.no b {{ color: {PINK}; }}
.do p {{ font-size: 14px; line-height: 1.35; margin: 0; max-width: 330px; }}
.shots {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }}
.shot img {{ width: 100%; border-radius: 10px; box-shadow: 0 0 0 1px rgba(11,18,32,.12); display: block; }}
.shot figcaption {{ margin-top: 12px; display: flex; flex-direction: column; gap: 4px; font-size: 15px; }}
.shot figcaption b {{ font-size: 18px; }}
.files p {{ display: grid; grid-template-columns: 200px 1fr; font-size: 18px; margin-bottom: 14px; }}
.files code {{ font-size: 18px; }}
</style></head><body>{''.join(pages)}</body></html>"""


def build_pdf(tmp: Path) -> None:
    src = tmp / "guideline.html"
    src.write_text(guideline_html(OUT / "slides", OUT / "logos"), encoding="utf-8")
    chrome(["--no-pdf-header-footer", f"--print-to-pdf={OUT / 'guideline.pdf'}", src.as_uri()])


# ---- токены -------------------------------------------------------------------------------------------------------------------
RULES = ["Логотип — в правом нижнем углу", "Поля — 48 px", "Акцент — только для главного числа"]


def w3c_tokens() -> dict:
    pal = {nm.lower().replace(" ", "-"): {"$value": hx, "$description": nm} for _, _, nm, hx, *_ in PALETTE}
    ref = {p[0]: "{color.palette." + p[2].lower().replace(" ", "-") + "}" for p in PALETTE}
    return {
        "$description": "Дизайн-токены бренда VK Cloud (учебный пример Verstka, бренд условный)",
        "$extensions": {"ru.verstka": {"name": BRAND, "rules": RULES}},
        "color": {
            "$type": "color",
            "palette": pal,
            "role": {
                "primary": {"$value": ref["primary"], "$description": "Основной цвет: фирменные плашки, первая серия диаграмм"},
                "secondary": {"$value": ref["secondary"], "$description": "Дополнительный цвет: вторая серия диаграмм"},
                "text": {"$value": ref["text"], "$description": "Заголовки и основной текст"},
                "background": {"$value": ref["background"], "$description": "Фон слайдов"},
                "accent": {"$value": ref["accent"], "$description": "Только для главного числа на слайде"},
            },
            "chart": {str(i): {"$value": ref[k]} for i, k in enumerate(("primary", "secondary", "chart", "text"), 1)},
        },
        "font": {
            "family": {
                "$type": "fontFamily",
                "heading": {"$value": ["VK Sans Display", "Play", "sans-serif"]},
                "body": {"$value": ["VK Sans Text", "Play", "sans-serif"]},
            },
            "weight": {"$type": "fontWeight", "heading": {"$value": 700}, "body": {"$value": 400}},
        },
        "typography": {
            "$type": "typography",
            "heading": {"$value": {"fontFamily": "{font.family.heading}", "fontWeight": "{font.weight.heading}",
                                   "fontSize": {"value": 40, "unit": "px"}, "lineHeight": 1.1}},
            "body": {"$value": {"fontFamily": "{font.family.body}", "fontWeight": "{font.weight.body}",
                                "fontSize": {"value": 18, "unit": "px"}, "lineHeight": 1.3}},
        },
        "layout": {
            "$type": "dimension",
            "slide": {"width": {"$value": {"value": 1920, "unit": "px"}}, "height": {"$value": {"value": 1080, "unit": "px"}}},
            "margin": {"$value": {"value": MARGIN, "unit": "px"}, "$description": "Поля слайда со всех сторон"},
            "grid": {"columns": {"$type": "number", "$value": COLUMNS}, "gutter": {"$value": {"value": GUTTER, "unit": "px"}}},
        },
        "logo": {"position": {"$value": "bottom-right", "$description": "Логотип — в правом нижнем углу слайда"}},
    }


def studio_tokens() -> dict:
    pal = {nm.lower().replace(" ", "-"): {"value": hx, "type": "color", "description": nm} for _, _, nm, hx, *_ in PALETTE}
    ref = {p[0]: "{palette." + p[2].lower().replace(" ", "-") + "}" for p in PALETTE}
    return {
        "global": {
            "palette": pal,
            "fontFamilies": {"heading": {"value": "VK Sans Display", "type": "fontFamilies"}, "body": {"value": "VK Sans Text", "type": "fontFamilies"},
                             "fallback": {"value": "Play", "type": "fontFamilies"}},
            "fontWeights": {"heading": {"value": "Bold", "type": "fontWeights"}, "body": {"value": "Regular", "type": "fontWeights"}},
            "fontSizes": {"heading": {"value": "40", "type": "fontSizes"}, "body": {"value": "18", "type": "fontSizes"}},
            "spacing": {"margin": {"value": str(MARGIN), "type": "spacing", "description": "Поля слайда"},
                        "gutter": {"value": str(GUTTER), "type": "spacing"}},
            "grid": {"columns": {"value": str(COLUMNS), "type": "other"}},
        },
        "brand": {
            "primary": {"value": ref["primary"], "type": "color"},
            "secondary": {"value": ref["secondary"], "type": "color"},
            "text": {"value": ref["text"], "type": "color"},
            "background": {"value": ref["background"], "type": "color"},
            "accent": {"value": ref["accent"], "type": "color", "description": "Только для главного числа на слайде"},
            "chart": {"value": ref["chart"], "type": "color"},
            "heading": {"value": {"fontFamily": "{fontFamilies.heading}", "fontWeight": "{fontWeights.heading}", "fontSize": "{fontSizes.heading}"},
                        "type": "typography"},
            "body": {"value": {"fontFamily": "{fontFamilies.body}", "fontWeight": "{fontWeights.body}", "fontSize": "{fontSizes.body}"},
                     "type": "typography"},
            "logo-position": {"value": "bottom-right", "type": "other", "description": "Логотип — в правом нижнем углу"},
        },
        "$themes": [{"id": "vk-cloud", "name": "VK Cloud", "selectedTokenSets": {"global": "source", "brand": "enabled"}}],
        "$metadata": {"tokenSetOrder": ["global", "brand"]},
    }


def build_tokens() -> None:
    (OUT / "tokens.json").write_text(json.dumps(w3c_tokens(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "tokens-studio.json").write_text(json.dumps(studio_tokens(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for tool in ("rsvg-convert",):
        if not shutil.which(tool):
            sys.exit(f"нужен {tool}")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build_logos()
        build_slides(tmp)
        build_pdf(tmp)
    build_tokens()
    print("готово:", OUT)


if __name__ == "__main__":
    main()
