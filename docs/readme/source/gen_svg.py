"""README SVG set — usage: python docs/readme/source/gen_svg.py docs/readme/svg.
README SVG set in the «Слои» style: hero, section plates, pipeline, video cards, badges (light + dark)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from svgtext import path as T, width as W, flush, ink, cap, centered

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

L = dict(bg="#F3F4F1", ink="#0B1220", muted="#5A6272", blue="#2563EB", sky="#38BDF8", p1="#FFFFFF", p2="#E9F1FF",
         p3="#0B1220", p3t="#FFFFFF", p3m="#FFFFFF", bar1="#BFD6FF", bar1o=1, bar3="#0B1220", bar3o=1,
         strip1="#BFD6FF", strip2="#E9F1FF", plate="#F3F4F1", line="#0B1220", lineo=0.08, card="#FFFFFF")
D = dict(bg="#0B1220", ink="#F3F4F1", muted="#9AA3B2", blue="#3B82F6", sky="#38BDF8", p1="#151D2C", p2="#1A2742",
         p3="#E9F1FF", p3t="#0B1220", p3m="#0B1220", bar1="#FFFFFF", bar1o=0.24, bar3="#FFFFFF", bar3o=1,
         strip1="#2563EB", strip2="#1A2742", plate="#121A29", line="#FFFFFF", lineo=0.10, card="#151D2C")

GRAD = ('<linearGradient id="cta" x1="0" y1="0" x2="1" y2="0.35">'
        '<stop offset="0" stop-color="#1D4ED8"/><stop offset=".45" stop-color="#2563EB"/>'
        '<stop offset="1.4" stop-color="#38BDF8"/></linearGradient>')


def svg(w, h, title, desc, body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-labelledby="t d"><title id="t">{title}</title><desc id="d">{desc}</desc>'
            f'<defs>{GRAD}{defs}{flush()}</defs>{body}</svg>\n')


def save(name, s):
    open(f"{OUT}/{name}", "w", encoding="utf-8").write(s)


# The logo of the interface (web/src/ui/shell/Brand.tsx, styles base.css + offline.css), at 20 px type:
# «Verstka» Unbounded 700 20/24, letter-spacing −0.03em; under it one row of three bars 28 / 20 / 12 px wide, 4 px tall,
# fully rounded, 3 px apart, row 1 px right of the word box (.of-brand .p2-bars translateX(1px)) and 1 px up into it
# (margin-top −1px) — i.e. the bars start 23 px below the top of the 24 px line box. Colours: #BFD6FF / #2563EB / #0B1220
# (on dark: white .24 / #2563EB / white).
LOGO_BARS = ((28, "bar1"), (20, None), (12, "bar3"))


def _baseline_in_line(size=20, line=24):
    """Baseline offset from the top of a CSS line box (Unbounded hhea 995/−245 per 1000)."""
    content = (995 + 245) / 1000 * size
    return (line - content) / 2 + 995 / 1000 * size


def bars(x, top, k, c):
    """The logo's bar row scaled by k (k = font size / 20), top-left at (x, top)."""
    out, cx = [], x
    for wd, role in LOGO_BARS:
        col, op = (c[role], c[role + "o"]) if role else ("#2563EB", 1)
        out.append(f'<rect x="{cx:.2f}" y="{top:.2f}" width="{wd * k:.2f}" height="{4 * k:.2f}" rx="{2 * k:.2f}" '
                   f'fill="{col}" fill-opacity="{op}"/>')
        cx += (wd + 3) * k
    return "".join(out)


def logo(x, baseline, size, c, fill):
    """«Verstka» + bars exactly in the interface proportions; x is the left of the word box, baseline of the word."""
    k = size / 20
    top_line = baseline - _baseline_in_line() * k
    return (T("Verstka", "U", size, x, baseline, fill, track=-0.03)
            + bars(x + 1 * k, top_line + 23 * k, k, c))


def logo_width(size):
    return (28 + 3 + 20 + 3 + 12) * size / 20


def slide_sketch(x, y, w, h, kind, c):
    """2D sketch miniature of a slide form, like the build storyboard cards."""
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="#FFFFFF" stroke="#0B1220" stroke-opacity=".08"/>']
    o.append(f'<rect x="{x + 10}" y="{y + 10}" width="{w * .55:.0f}" height="6" rx="3" fill="#0B1220"/>')
    if kind == "s":
        for i in range(3):
            yy = y + 28 + i * 12
            o.append(f'<circle cx="{x + 13}" cy="{yy + 2}" r="2.5" fill="#2563EB"/>')
            o.append(f'<rect x="{x + 20}" y="{yy}" width="{w * (.62 - i * .08):.0f}" height="4" rx="2" fill="#5A6272" fill-opacity=".45"/>')
    elif kind == "v":
        o.append(f'<rect x="{x + 10}" y="{y + 26}" width="34" height="14" rx="3" fill="#2563EB"/>')
        o.append(f'<rect x="{x + 10}" y="{y + 46}" width="30" height="4" rx="2" fill="#5A6272" fill-opacity=".45"/>')
        for i, hh in enumerate((14, 22, 30, 40)):
            o.append(f'<rect x="{x + w - 64 + i * 13}" y="{y + h - 10 - hh}" width="9" height="{hh}" rx="2" '
                     f'fill="{"#2563EB" if i == 3 else "#BFD6FF"}"/>')
    else:
        for r in range(4):
            yy = y + 26 + r * 10
            o.append(f'<rect x="{x + 10}" y="{yy}" width="{w - 20}" height="{7 if r == 0 else 1.5}" rx="1" '
                     f'fill="{"#E9F1FF" if r == 0 else "#0B1220"}" fill-opacity="{1 if r == 0 else .15}"/>')
            for cx in (0.38, 0.66):
                o.append(f'<rect x="{x + 10 + (w - 20) * cx:.0f}" y="{yy + (0 if r == 0 else -6)}" width="{(w - 20) * .22:.0f}" '
                         f'height="4" rx="2" fill="#5A6272" fill-opacity=".45"/>')
    return "".join(o)


# ---------------------------------------------------------------- hero
def hero(c, dark):
    Wd, H = 1200, 480
    b = [f'<rect width="{Wd}" height="{H}" rx="32" fill="{c["bg"]}"/>']
    if dark:
        b.append(f'<rect x=".5" y=".5" width="{Wd - 1}" height="{H - 1}" rx="31.5" fill="none" stroke="#FFFFFF" stroke-opacity=".08"/>')
    # left half: the case label and the interface logo, centred as one block in the space left of the plates
    px = 664
    lab, lsize, ltrack = "ЛЦТ 2026 · КЕЙС VK TECH № 4 · ВТОРАЯ СТУПЕНЬ", 17, 0.06
    size, k = 104, 104 / 20
    wx0, wx1, wy0, _ = ink("Verstka", "U", size, -0.03)
    lab_cap = cap("M", lsize)
    gap = 36  # label baseline → top of the word's ink
    bars_bottom = (-_baseline_in_line() + 23 + 4) * k  # from the word baseline
    team, tgap = "КОМАНДА «РЕКРУТ 2»", 34  # under the bars: bottom of the bars → cap top of the team line
    block_h = lab_cap + gap + (-wy0) + bars_bottom + tgap + lab_cap
    top = (H - block_h) / 2
    lab_base = top + lab_cap
    base = lab_base + gap - wy0
    cx = px / 2
    lx0, lx1, _, _ = ink(lab, "M", lsize, ltrack)
    b.append(T(lab, "M", lsize, cx - (lx0 + lx1) / 2, lab_base, c["muted"], track=ltrack))
    tx0, tx1, _, _ = ink(team, "M", lsize, ltrack)
    b.append(T(team, "M", lsize, cx - (tx0 + tx1) / 2, base + bars_bottom + tgap + lab_cap, c["ink"], track=ltrack))
    # the logo is one unit (bars start under the word box, as in the header); centre the unit by its ink
    unit_x1 = max(wx1, 1 * k + logo_width(20 * k))
    unit_x0 = min(wx0, 1 * k)
    b.append(logo(cx - (unit_x0 + unit_x1) / 2, base, size, c, c["ink"]))
    # stacked plates, as on the «Создать» screen: one column of numbers, equal gap number → text, equal paddings
    pw, pad, band = 472, 24, 84
    nsize, gap = 40, 20
    col = max(ink(n, "U", nsize, -0.04)[1] - ink(n, "U", nsize, -0.04)[0] for n in ("01", "02", "03"))
    tx = px + pad + col + gap
    tcap, msize = cap("U", 24), 17
    line = 26  # title baseline → meta baseline
    block = tcap + line  # cap top of the title → baseline of the meta line

    def plate_head(y, n, t, m, tc, mc, nop, mop):
        top = y + (band - block) / 2
        tb = top + tcap
        mid = top + block / 2
        nx0 = ink(n, "U", nsize, -0.04)[0]
        out = [T(n, "U", nsize, px + pad - nx0, mid + cap("U", nsize) / 2, tc, opacity=nop, track=-0.04),
               T(t, "U", 24, tx, tb, tc, track=-0.03),
               T(m, "M", msize, tx, tb + line, mc, opacity=mop)]
        assert tx + W(m, "M", msize) <= px + pw - pad, m
        return "".join(out)

    plates = [(48, c["p1"], "01", "Шаблон", "любой файл PowerPoint · брендбук"),
              (48 + band, c["p2"], "02", "Текст и данные", "план, документ, таблицы, база знаний")]
    for y, fill, n, t, m in plates:
        b.append(f'<rect x="{px}" y="{y}" width="{pw}" height="{band + 46}" rx="28" fill="{fill}"/>')
        b.append(plate_head(y, n, t, m, c["ink"], c["muted"], .16, None))
    y3 = 48 + 2 * band
    sw, sh, sgap = 126, 71, 14
    sy = y3 + band + 4
    lab_base = sy + sh + 24
    bottom = lab_base + pad
    b.append(f'<rect x="{px}" y="{y3}" width="{pw}" height="{bottom - y3}" rx="28" fill="{c["p3"]}"/>')
    b.append(plate_head(y3, "03", "Три варианта", "с оценкой качества и «Почему так»", c["p3t"], c["p3m"], .24, .6))
    sx = px + (pw - 3 * sw - 2 * sgap) / 2
    for i, (k, lab) in enumerate((("s", "Структурный"), ("v", "Визуальный"), ("c", "Компактный"))):
        xx = sx + i * (sw + sgap)
        b.append(slide_sketch(round(xx), sy, sw, sh, k, c))
        b.append(centered(lab, "M", 16, xx + sw / 2, lab_base - cap("M", 16) / 2, c["p3t"], opacity=.62))
    return svg(Wd, H, "Verstka — цифровой дизайнер презентаций",
               "Слева — подпись «ЛЦТ 2026 · кейс VK Tech № 4 · вторая ступень», логотип Verstka и команда «Рекрут 2». "
               "Справа — три плиты интерфейса «Слои»: 01 Шаблон, 02 Текст и данные, 03 Три варианта.", "".join(b))


# ---------------------------------------------------------------- section plates
SECTIONS = [
    ("01", "interface", "Интерфейс", ""),
    ("02", "examples", "Примеры презентаций", ""),
    ("03", "video", "Видео", ""),
    ("04", "features", "Что умеет", ""),
    ("05", "how", "Как это работает", ""),
    ("06", "quality", "Качество", ""),
    ("07", "start", "Быстрый старт", ""),
    ("08", "models", "Модели и стоимость", ""),
    ("09", "tz", "Соответствие ТЗ", ""),
    ("10", "docs", "Документация и ограничения", ""),
]


SEC_NUM = 88
SEC_COL = max(ink(n, "U", SEC_NUM, -0.04)[1] - ink(n, "U", SEC_NUM, -0.04)[0] for n, *_ in SECTIONS)


def section(n, title, sub, c, dark):
    Wd, H = 1200, 150
    b = [f'<rect x="56" y="0" width="{Wd - 112}" height="60" rx="28" fill="{c["strip1"]}" fill-opacity="{.55 if dark else 1}"/>',
         f'<rect x="28" y="10" width="{Wd - 56}" height="60" rx="28" fill="{c["strip2"]}"/>',
         f'<rect x="0" y="20" width="{Wd}" height="{H - 20}" rx="28" fill="{c["plate"]}"/>']
    if dark:
        b.append(f'<rect x=".5" y="20.5" width="{Wd - 1}" height="{H - 21}" rx="27.5" fill="none" stroke="#FFFFFF" stroke-opacity=".07"/>')
    pad, gap = 40, 32
    tcap, line = cap("U", 40), 34
    block = tcap + (line if sub else 0)
    top = 20 + (H - 20 - block) / 2
    tb = top + tcap
    mid = top + block / 2
    nx0 = ink(n, "U", SEC_NUM, -0.04)[0]
    b.append(T(n, "U", SEC_NUM, pad - nx0, mid + cap("U", SEC_NUM) / 2, c["ink"], opacity=.14, track=-0.04))
    tx = pad + SEC_COL + gap
    b.append(T(title, "U", 40, tx, tb, c["ink"], track=-0.03))
    if sub:
        b.append(T(sub, "MR", 21, tx + 1, tb + line, c["muted"]))
    k = 2.0
    b.append(bars(Wd - pad - logo_width(20 * k), mid - 2 * k, k, c))
    return svg(Wd, H, f"{n} · {title}", sub or title, "".join(b))


# ---------------------------------------------------------------- pipeline
STEPS = [
    ("01", "Чтение", ["шаблон → manifest.json,", "текст, документы, данные"], "both"),
    ("02", "План", ["агент: аналитик,", "дизайнер, критик"], "model"),
    ("03", "Смысл", ["каждое число и доля", "сверены со входом"], "code"),
    ("04", "Данные", ["профиль → задача →", "вид → вывод с числом"], "both"),
    ("05", "Вёрстка", ["на слайды-образцы", "шаблона и бренда"], "code"),
    ("06", "Картинки", ["Z-Image, без надписей,", "проверка зрением"], "model"),
    ("07", "Аудит", ["73 + 3 проверки,", "автоисправление"], "both"),
    ("08", "Экспорт", ["PPTX с нативными", "объектами, PDF, HTML"], "code"),
]


def pipeline(c, dark):
    Wd, H = 1200, 520
    b = [f'<rect width="{Wd}" height="{H}" rx="32" fill="{c["bg"]}"/>']
    if dark:
        b.append(f'<rect x=".5" y=".5" width="{Wd - 1}" height="{H - 1}" rx="31.5" fill="none" stroke="#FFFFFF" stroke-opacity=".08"/>')
    m, g = 48, 24
    cw = (Wd - 2 * m - 3 * g) / 4
    ch = 158
    rows = (64, 290)
    dot = {"model": [c["blue"]], "code": [c["ink"]], "both": [c["blue"], c["ink"]]}
    for i, (n, t, lines, kind) in enumerate(STEPS):
        r, col = divmod(i, 4)
        x = m + col * (cw + g)
        y = rows[r]
        fill = c["card"] if not (i == 7) else c["p3"]
        tc = c["ink"] if i != 7 else c["p3t"]
        mc = c["muted"] if i != 7 else c["p3t"]
        # layered: a thin plate peeks from behind each card
        b.append(f'<rect x="{x + 14:.1f}" y="{y - 10}" width="{cw - 28:.1f}" height="40" rx="22" fill="{c["p2"] if not dark else "#1A2742"}"/>')
        b.append(f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="{ch}" rx="24" fill="{fill}"/>')
        b.append(T(n, "U", 46, x + 20, y + 56, tc, opacity=.14 if i != 7 else .22, track=-0.04))
        for j, dc in enumerate(dot[kind]):
            if i == 7 and dc == c["ink"]:
                dc = c["p3t"]
            b.append(f'<circle cx="{x + cw - 26 - j * 18:.1f}" cy="{y + 30}" r="6" fill="{dc}"/>')
        b.append(T(t, "U", 23, x + 20, y + 96, tc, track=-0.03))
        for j, ln in enumerate(lines):
            b.append(T(ln, "M", 18, x + 20, y + 124 + j * 23, mc, opacity=None if i != 7 else .7))
        if col < 3:
            ax = x + cw + 3
            b.append(f'<path d="M{ax:.1f} {y + ch / 2} h{g - 6}" stroke="{c["blue"]}" stroke-width="3" stroke-linecap="round"/>')
            b.append(f'<path d="M{ax + g - 12:.1f} {y + ch / 2 - 6} l6 6 l-6 6" fill="none" stroke="{c["blue"]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    # return connector row1 → row2
    x4 = m + 3 * (cw + g) + cw / 2
    x5 = m + cw / 2
    y1 = rows[0] + ch + 4
    y2 = rows[1] - 14
    ym = (y1 + y2) / 2
    b.append(f'<path d="M{x4:.1f} {y1} V{ym - 12} q0 12 -12 12 H{x5 + 12:.1f} q-12 0 -12 12 V{y2 - 6}" fill="none" '
             f'stroke="{c["blue"]}" stroke-width="3" stroke-linecap="round" stroke-dasharray="1 8"/>')
    b.append(f'<path d="M{x5 - 6:.1f} {y2 - 12} l6 6 l6 -6" fill="none" stroke="{c["blue"]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    # legend + feedback loop
    ly = 488
    b.append(f'<circle cx="{m + 6}" cy="{ly - 6}" r="6" fill="{c["blue"]}"/>')
    b.append(T("модель: понимает и пишет", "M", 18, m + 20, ly, c["muted"]))
    x2 = m + 20 + W("модель: понимает и пишет", "M", 18) + 32
    b.append(f'<circle cx="{x2 + 6:.1f}" cy="{ly - 6}" r="6" fill="{c["ink"]}"/>')
    b.append(T("код: считает, сверяет, верстает", "M", 18, x2 + 20, ly, c["muted"]))
    b.append(T("правка → к агенту, только нужный слайд", "M", 18, Wd - m, ly, c["muted"], anchor="end"))
    return svg(Wd, H, "Как работает Verstka: восемь шагов",
               "Чтение, план, смысл, данные, вёрстка по шаблону, картинки, аудит с автоисправлением, экспорт в PPTX, PDF и HTML. "
               "Синие точки — шаги модели, тёмные — шаги кода.", "".join(b))


# ---------------------------------------------------------------- video cards
def video_card(c, dark, first):
    """Video cards: the stage-2 screencast is the current solution (bright), the stage-1 video is the archive (muted)."""
    Wd, H = 580, 300
    if first:  # archive
        tag, title, meta, link, play, tagc, desc = (
            "АРХИВ · ПЕРВАЯ СТУПЕНЬ", "Прошлая версия", "29.09 · 8 мин 54 с", "Смотреть →",
            "#5A6272", "#9AA3B2", "Архив: видео первой ступени, 29 сентября, прежний интерфейс, 8 минут 54 секунды.")
    else:
        tag, title, meta, link, play, tagc, desc = (
            "АКТУАЛЬНАЯ ВЕРСИЯ · ВТОРАЯ СТУПЕНЬ", "Текущее решение", "20.10 · 9 мин 44 с",
            "Смотреть →", "url(#cta)", "#38BDF8",
            "Актуальная версия: скринкаст второй ступени, 20 октября, интерфейс «Слои», 9 минут 44 секунды.")
    b = [f'<rect width="{Wd}" height="{H}" rx="28" fill="#0B1220"/>']
    if dark:
        b.append(f'<rect x=".5" y=".5" width="{Wd - 1}" height="{H - 1}" rx="27.5" fill="none" stroke="#FFFFFF" stroke-opacity=".1"/>')
    if not first:
        b.append(f'<rect x="1.5" y="1.5" width="{Wd - 3}" height="{H - 3}" rx="26.5" fill="none" stroke="#2563EB" stroke-width="3"/>')
    b.append(T("01" if first else "02", "U", 120, 30, 140, "#FFFFFF", opacity=.08, track=-0.04))
    b.append(f'<circle cx="490" cy="84" r="44" fill="{play}"/>')
    b.append('<path d="M478 64 L510 84 L478 104 Z" fill="#FFFFFF"/>')
    b.append(T(title, "U", 32, 36, 196, "#FFFFFF", opacity=(.72 if first else 1), track=-0.03))
    b.append(T(meta, "M", 19, 36, 232, "#FFFFFF", opacity=.72))
    b.append(T(link, "M", 19, 36, 262, "#38BDF8" if not first else "#9AA3B2"))
    return svg(Wd, H, ("Архив: видео первой ступени" if first else "Актуальная версия: скринкаст второй ступени"), desc, "".join(b))


# ---------------------------------------------------------------- features board
FEATS = [
    ("Данные → выводы", ["профиль, задача, 2–3 вида", "с причинами, заголовок с числом"], "data"),
    ("Любой брендбук", ["PDF, токены, Figma, .fig, ZIP —", "бренд побеждает шаблон"], "brand"),
    ("База знаний", ["документы и ссылки, источник", "в заметках, сверка с таблицами"], "kb"),
    ("Любой вход", ["план, письмо, DOCX, PDF, тема,", "готовая презентация, дословно"], "input"),
    ("Картинки по смыслу", ["Z-Image в палитре шаблона,", "без надписей — проверяет зрение"], "pic"),
    ("Правки и Помощник", ["«покажи таблицей», «короче»,", "«почему слайд 4 такой»"], "edit"),
]


def feat_icon(kind, x, y, c, dark):
    """Small native illustration in a 120×84 box at (x, y)."""
    o = []
    card = "#FFFFFF" if not dark else "#0B1220"
    o.append(f'<rect x="{x}" y="{y}" width="120" height="84" rx="14" fill="{card}"/>')
    if kind == "data":
        for i, hh in enumerate((22, 34, 28, 48, 58)):
            o.append(f'<rect x="{x + 16 + i * 19}" y="{y + 72 - hh}" width="12" height="{hh}" rx="3" fill="{c["blue"] if i == 4 else c["bar1"]}" fill-opacity="{1 if i == 4 or not dark else .35}"/>')
        o.append(f'<circle cx="{x + 104}" cy="{y + 14}" r="4" fill="{c["sky"]}"/>')
    elif kind == "brand":
        for i, col in enumerate(("#0077FF", "#2787F5", "#FF3985", "#00C2FF")):
            o.append(f'<circle cx="{x + 22 + i * 25}" cy="{y + 26}" r="10" fill="{col}"/>')
        o.append(T("Aa", "U", 26, x + 14, y + 72, c["ink"], track=-0.03))
        o.append(f'<rect x="{x + 62}" y="{y + 52}" width="44" height="18" rx="9" fill="{c["blue"]}"/>')
    elif kind == "kb":
        for i in range(3):
            o.append(f'<rect x="{x + 18 + i * 10}" y="{y + 12 + i * 8}" width="56" height="58" rx="8" fill="{c["p2"]}" stroke="{c["line"]}" stroke-opacity=".12"/>')
        for j in range(3):
            o.append(f'<rect x="{x + 46}" y="{y + 38 + j * 9}" width="{30 - j * 6}" height="4" rx="2" fill="{c["muted"]}" fill-opacity=".6"/>')
        o.append(f'<circle cx="{x + 96}" cy="{y + 56}" r="11" fill="none" stroke="{c["blue"]}" stroke-width="4"/>')
        o.append(f'<path d="M{x + 104} {y + 64} l8 8" stroke="{c["blue"]}" stroke-width="4" stroke-linecap="round"/>')
    elif kind == "input":
        for i, (lab, col) in enumerate((("PDF", "#2563EB"), ("DOCX", "#0B1220" if not dark else "#F3F4F1"), ("CSV", "#38BDF8"))):
            yy = y + 10 + i * 23
            o.append(f'<rect x="{x + 14}" y="{yy}" width="92" height="19" rx="9.5" fill="{col}" fill-opacity="{.14 if not (dark and i == 1) else .2}"/>')
            o.append(T(lab, "M", 13, x + 60, yy + 14, col if not (dark and i == 0) else "#7AA7FF", anchor="middle"))
    elif kind == "pic":
        o.append(f'<rect x="{x + 14}" y="{y + 12}" width="66" height="60" rx="8" fill="{c["p2"]}"/>')
        o.append(f'<path d="M{x + 18} {y + 66} l18 -22 l12 12 l10 -8 l18 18 Z" fill="{c["blue"]}"/>')
        o.append(f'<circle cx="{x + 64}" cy="{y + 26}" r="7" fill="{c["sky"]}"/>')
        o.append(f'<circle cx="{x + 98}" cy="{y + 42}" r="13" fill="{c["blue"]}"/>')
        o.append(f'<path d="M{x + 92} {y + 42} l4.5 4.5 l8 -9" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    else:
        o.append(f'<rect x="{x + 12}" y="{y + 12}" width="78" height="26" rx="13" fill="{c["p2"]}"/>')
        o.append(f'<rect x="{x + 24}" y="{y + 22}" width="50" height="5" rx="2.5" fill="{c["muted"]}" fill-opacity=".6"/>')
        o.append(f'<rect x="{x + 34}" y="{y + 46}" width="74" height="26" rx="13" fill="url(#cta)"/>')
        o.append(f'<rect x="{x + 46}" y="{y + 56}" width="46" height="5" rx="2.5" fill="#FFFFFF" fill-opacity=".85"/>')
    return "".join(o)


def features(c, dark):
    Wd, H = 1200, 520
    b = [f'<rect width="{Wd}" height="{H}" rx="32" fill="{c["bg"]}"/>']
    if dark:
        b.append(f'<rect x=".5" y=".5" width="{Wd - 1}" height="{H - 1}" rx="31.5" fill="none" stroke="#FFFFFF" stroke-opacity=".08"/>')
    m, g = 40, 20
    cw = (Wd - 2 * m - 2 * g) / 3
    ch = 210
    for i, (t, lines, kind) in enumerate(FEATS):
        r, col = divmod(i, 3)
        x = m + col * (cw + g)
        y = 40 + r * (ch + g)
        first = i == 0
        fill = c["p3"] if first else c["p1"]
        tc = c["p3t"] if first else c["ink"]
        b.append(f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="{ch}" rx="24" fill="{fill}"/>')
        b.append(feat_icon(kind, round(x + 22), y + 22, (L if dark else D) if first else c, (not dark) if first else dark))
        if first:
            b.append(T("вторая ступень", "M", 16, x + cw - 24, y + 40, c["p3t"], anchor="end", opacity=.6))
        b.append(T(t, "U", 21, x + 22, y + 140, tc, track=-0.03))
        for j, ln in enumerate(lines):
            if first:
                b.append(T(ln, "M", 17, x + 22, y + 166 + j * 23, c["p3t"], opacity=.72))
            else:
                b.append(T(ln, "M", 17, x + 22, y + 166 + j * 23, c["muted"]))
    return svg(Wd, H, "Что умеет Verstka", "Данные в выводы, брендбук в любой форме, база знаний, любой вход, картинки по смыслу, правки и Помощник.", "".join(b))


# ---------------------------------------------------------------- quality stats
STATS = [("76", "проверок качества", "73 кодом + 3 моделью"),
         ("≤ 5 мин", "на три варианта", "с данными — 26–80 с"),
         ("6 098", "тестов", "5 294 + 48 + 756 интерфейса"),
         ("0", "закрытых API", "открытые веса на VK")]


def stats(c, dark):
    Wd, H = 1200, 230
    b = [f'<rect width="{Wd}" height="{H}" rx="32" fill="{c["bg"]}"/>']
    if dark:
        b.append(f'<rect x=".5" y=".5" width="{Wd - 1}" height="{H - 1}" rx="31.5" fill="none" stroke="#FFFFFF" stroke-opacity=".08"/>')
    m, g = 32, 16
    cw = (Wd - 2 * m - 3 * g) / 4
    for i, (big, lab, sub) in enumerate(STATS):
        x = m + i * (cw + g)
        first = i == 0
        fill = c["p3"] if first else c["p1"]
        tc = c["p3t"] if first else c["ink"]
        b.append(f'<rect x="{x:.1f}" y="32" width="{cw:.1f}" height="166" rx="24" fill="{fill}"/>')
        b.append(T(big, "U", 50, x + 22, 102, c["blue"] if not first else tc, track=-0.04))
        b.append(T(lab, "M", 20, x + 22, 140, tc))
        b.append(T(sub, "MR", 17, x + 22, 170, tc, opacity=.62))
    return svg(Wd, H, "Качество Verstka в цифрах", "76 проверок качества, до 5 минут на три варианта, 6 098 тестов, ноль закрытых API.", "".join(b))


# ---------------------------------------------------------------- badges
BADGES = [("python", "Python", "3.11 · 3.12"), ("web", "Интерфейс", "React · TypeScript"),
          ("ci", "CI", "Linux · Ubuntu 24.04"), ("llm", "Модель", "Qwen3.8-27B · инференс VK"),
          ("t2i", "Картинки", "Z-Image · Polza"), ("license", "Лицензия", "MIT")]


def badge(label, value):
    h, fs, pad = 30, 14, 13
    def inkw(t):
        x0, x1, _, _ = ink(t, "M", fs)
        return x1 - x0
    wl = inkw(label) + 2 * pad
    wv = inkw(value) + 2 * pad
    Wd = wl + wv
    b = [f'<rect width="{Wd:.2f}" height="{h}" rx="15" fill="#0B1220"/>',
         f'<path d="M{wl:.2f} 0 H{Wd - 15:.2f} a15 15 0 0 1 0 30 H{wl:.2f} Z" fill="url(#cta)"/>',
         centered(label, "M", fs, wl / 2, h / 2, "#FFFFFF", opacity=.72),
         centered(value, "M", fs, wl + wv / 2, h / 2, "#FFFFFF"),
         f'<rect x=".5" y=".5" width="{Wd - 1:.2f}" height="{h - 1}" rx="14.5" fill="none" stroke="#FFFFFF" stroke-opacity=".16"/>']
    return svg(f"{Wd:.2f}", h, f"{label}: {value}", f"{label}: {value}", "".join(b))


for theme, c, dark in (("light", L, False), ("dark", D, True)):
    save(f"hero-{theme}.svg", hero(c, dark))
    save(f"pipeline-{theme}.svg", pipeline(c, dark))
    save(f"features-{theme}.svg", features(c, dark))
    save(f"quality-{theme}.svg", stats(c, dark))
    save(f"video-stage1-{theme}.svg", video_card(c, dark, True))
    save(f"video-stage2-{theme}.svg", video_card(c, dark, False))
    for n, slug, t, s in SECTIONS:
        save(f"section-{n}-{slug}-{theme}.svg", section(n, t, s, c, dark))
for slug, lab, val in BADGES:
    save(f"badge-{slug}.svg", badge(lab, val))
print("ok", len(os.listdir(OUT)))
