"""A picture the author described beside the text («[Место под изображение: экран панели управления …]»).

The note is never a sentence of the deck: its free place goes on the slide that says what the author wrote next to it,
described, so the image model draws into it (verstka/images). Slides the user dictated («Слайд N», or headings laid
out as written) carry their notes in their own text (planning/faithful.py); this module serves the briefs whose slides
are cut by the architect (planning/agent.py) or by the rules planner (planning/outline.py). Before it, the live run of
2026-10-07 made a slide «Панель показывает три ключевых параметра» out of the note, and the deck had no picture.
"""

from __future__ import annotations

import re
from typing import Any

from verstka.planning import heuristics as H

# a bracketed note on a line of its own («[Место под изображение: экран панели …]», a note of several sentences too)
_PICTURE_NOTE_RE = re.compile(r"^[ \t]*\[(?P<body>[^\[\]]{3,})\][ \t]*[.;]?[ \t]*$", re.M)
_FRAMES = {"title", "agenda", "section", "thanks"}
_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.I)


def numbered_sentences(text: str) -> list[str]:
    """The brief's sentences in order (a list line is a sentence of its own), for the architect's numbers."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or re.match(r"^\|?\s*:?-{2,}", line):
            continue
        out.extend(H.split_sentences(line) or [line])
    return out


def picture_notes(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """The brief without its bracketed notes about a picture, and each note as (how many of the brief's sentences come
    before it, what the picture shows, the words after the note's label — «фото офиса добавлю сам» keeps the place for
    the author's own photo; the label «Место под изображение» itself never does). Notes about a chart or a table stay
    in the text: they ask for a form of the slide's own data."""
    from verstka.planning.faithful import _note_part

    text = text or ""
    kept: list[str] = []
    notes: list[tuple[int, str, str]] = []
    last = 0
    for m in _PICTURE_NOTE_RE.finditer(text):
        part = _note_part(m.group("body"))
        what = H.strip_end((part.text or part.label).strip())
        if part.kind != "image" or not what:
            continue
        kept.append(text[last:m.start()])
        notes.append((len(numbered_sentences("".join(kept))), H.cap_first(what), part.text.strip() if part.label else ""))
        last = m.end()
    kept.append(text[last:])
    return "".join(kept), notes


def _own(words: str, slide_text: str) -> bool:
    from verstka.planning.faithful import own_photo

    return bool(words and own_photo(words)) or own_photo(slide_text)


def place_pictures(units: list[Any], spans: dict[str, set[int]], notes: list[tuple[int, str, str]], warnings: list[str]) -> None:
    """The architect's slides (planning/agent.py `_Unit`): each note goes to the slide that holds the sentence just
    before it (the picture shows what the author wrote above it), else to the slide of the next sentence, else to the
    first slide still without a picture; one picture per slide, never on the cover or the closing slide."""
    for before, hint, words in notes:
        free = [u for u in units if not u.frame and not u.photo_hint]
        host = next((u for u in free if before in spans.get(u.key, set())), None)
        if host is None:
            later = [(min(n for n in spans.get(u.key, set()) if n > before), k, u) for k, u in enumerate(free) if any(n > before for n in spans.get(u.key, set()))]
            host = min(later, key=lambda x: (x[0], x[1]))[2] if later else (free[0] if free else None)
        if host is None:
            warnings.append(f"picture note left out (every slide already has a picture): {hint[:60]}")
            continue
        host.photo_hint = hint
        host.photo_own = _own(words, host.text)


def _stems(text: str) -> set[str]:
    return {w[:6] for w in _WORD_RE.findall((text or "").lower().replace("ё", "е"))}


def _slide_text(s: Any) -> str:
    c = s.content
    parts = [s.headline or "", s.subtitle or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text} {' '.join(it.bullets)}" for it in [*c.items, *c.columns]]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    if c.table is not None:
        parts += [" ".join(c.table.columns), *(" ".join(r) for r in c.table.rows)]
    return " ".join(parts)


def place_pictures_by_text(outline: Any, text: str, notes: list[tuple[int, str, str]], warnings: list[str]) -> None:
    """The rules planner's slides: each note's place goes on the slide whose words share the most with the sentence
    just before the note (else the one just after it); with no such slide, on the content slide at the note's place
    in the brief. One picture per slide, never on a frame slide (cover, agenda, divider, closing)."""
    sents = numbered_sentences(text)
    for before, hint, words in notes:
        free = [s for s in outline.slides if s.kind.value not in _FRAMES and not s.content.photo_slot]
        if not free:
            warnings.append(f"picture note left out (every slide already has a picture): {hint[:60]}")
            continue
        host = None
        for anchor in (sents[before - 1] if before >= 1 else "", sents[before] if before < len(sents) else ""):
            want = _stems(anchor)
            scored = [(len(want & _stems(_slide_text(s))), -k, s) for k, s in enumerate(free)] if want else []
            best = max(scored, key=lambda x: (x[0], x[1]), default=None)
            if best is not None and best[0] >= 2:
                host = best[2]
                break
        if host is None:
            share = before / max(1, len(sents))
            host = free[min(len(free) - 1, int(share * len(free)))]
        c = host.content
        c.photo_slot = "Изображение"
        c.photo_hint = hint
        c.photo_own = _own(words, _slide_text(host))


# a slide with a picture gives it about half of its width: the text beside it stays short (VK's experts: a picture
# that fits helps, one squeezed beside a full slide harms — the owner's run of 17.10 had a picture beside a lead, four
# figures and two bullets)
PICTURE_MAX_POINTS = 4
PICTURE_MAX_NUMBERS = 3
PICTURE_MAX_CHARS = 420


def room_for_picture(lead: str = "", points: list[str] | None = None, numbers: list[str] | None = None, *, other: bool = False) -> bool:
    """A slide of the writer keeps its picture: no timeline, steps, table, chart or formula beside it (`other`), at most
    4 points or 3 figures, and the slide's words short enough for half of it."""
    points = [p for p in (points or []) if (p or "").strip()]
    numbers = [n for n in (numbers or []) if (n or "").strip()]
    if other or len(points) > PICTURE_MAX_POINTS or len(numbers) > PICTURE_MAX_NUMBERS or (points and len(numbers) > 2):
        return False
    return len(" ".join([lead or "", *points, *numbers])) <= PICTURE_MAX_CHARS


_NOTE_LINE_RE = re.compile(r"^\s*\[(?P<body>[^\[\]]{3,})\]\s*[.;]?\s*$")


def is_picture_note(line: str) -> bool:
    """A line that is the author's bracketed note about a picture («[Место под изображение: фасад офиса]»)."""
    from verstka.planning.faithful import _note_part

    m = _NOTE_LINE_RE.match(line or "")
    return bool(m) and _note_part(m.group("body")).kind == "image"


def strip_picture_notes(outline: Any, warnings: list[str]) -> None:
    """A picture's note never stands on a slide as its text: the designer copied it into the bullets of the live run
    of 18.10 («[Место под изображение: стеклянный фасад …]» as the slide's second point) — the place keeps it."""
    for s in getattr(outline, "slides", None) or []:
        c = s.content
        lines = [*c.bullets, *c.paragraphs, *(it.title for it in c.items), s.takeaway or "", s.subtitle or ""]
        if not any(is_picture_note(x) for x in lines):
            continue
        c.bullets = [x for x in c.bullets if not is_picture_note(x)]
        c.paragraphs = [x for x in c.paragraphs if not is_picture_note(x)]
        c.items = [it for it in c.items if not is_picture_note(it.title)]
        if is_picture_note(s.takeaway or ""):
            s.takeaway = None
        if is_picture_note(s.subtitle or ""):
            s.subtitle = None
        warnings.append(f"slide {s.id}: the picture's note left the slide's text")


# Pictures Verstka adds itself when «Генерировать изображения» is on. VK's experts (17.10) and the jury of 20.10: a
# picture helps where it shows a thing one can see — a place, a product, a device, a process at work; a cloud for
# «облачные сервисы», an envelope, a notebook, an arrow «рост» on a slide about rising costs, the same arrow on two
# slides harm. So a slide gets one only when its heading names such a thing (`concrete_subject`), every picture of the
# deck shows another thing, and none is forced: a deck whose slides speak of money, plans and percentages keeps no
# added picture (0–1 is better than pictures that say nothing). The owner's rule (18.10) «картинки обязаны быть»
# holds where the text gives them a subject.
# the label of a place Verstka chose itself (its description is the slide's subject and heading, not the author's words
# about a picture): drawn only from the text model's English description (images/service.py) — the heading itself
# given to the image model came back written across the picture (live run of 18.10, the text model down)
AUTO_LABEL = "Иллюстрация"
PICTURE_SHARE = 4  # at most about one added picture per this many slides (1 on 5 slides, 2 on 6–10, 3 on 11–13)
_SLIDE_HEAD_RE = re.compile(r"^\s*Слайд\s+(\d+)\s*[.:)]\s*(.+?)\s*$", re.M)
# kinds of slide whose content needs the slide's width (a row of steps, two columns, a comparison) — beside a picture
# their words break (the jury's R04 s15: four steps in half of the slide, «генерац/ии»)
_WIDE_KINDS = {"timeline", "process", "comparison", "two_column", "table", "chart", "team", "quote", "code", "mockup", "agenda"}

# Things one can see, by the start of the word (ё as е) → what the picture shows (synonyms share it: one phone per
# deck). Only nouns that name a visible thing whatever the deck: «машинное обучение», «инструменты аналитики»,
# «мониторинг», «дорогой», «портал», «карьера» are left out on purpose.
_THINGS: dict[str, str] = {}
for _key, _words in {
    "склад": "склад складск стеллаж паллет поддон кладовщик комплектовщик комплектац",
    "коробки": "коробк посылк упаковк",
    "конвейер": "конвейер",
    "сканер": "сканер",
    "завод": "завод фабрик станок станк цех",
    "офис": "офис здани бизнес-центр",
    "магазин": "магазин супермаркет",
    "ресторан": "ресторан кофейн столов",
    "больница": "больниц клиник поликлиник аптек врач медсестр пациент",
    "школа": "школ учител школьник",
    "университет": "университет кампус студент",
    "лаборатория": "лаборатор микроскоп пробирк реактив",
    "теплица": "теплиц растени рассад",
    "ферма": "ферм урожа пшениц зерн трактор",
    "город": "город улиц",
    "озеро": "озер байкал",
    "лес": "лесн тайг",
    "берег": "берег пляж побереж",
    "остров": "остров",
    "горы": "горн",
    "лёд": "ледник льдин",
    "животные": "животн нерп тюлен медвед птиц рыб",
    "дата-центр": "дата-центр датацентр серверн сервер",
    "телефон": "телефон смартфон мобильн приложени экран планшет",
    "ноутбук": "ноутбук компьютер",
    "робот": "робот манипулятор",
    "дрон": "дрон беспилотн",
    "автомобиль": "автомобил грузовик фургон автопарк",
    "поезд": "поезд вагон железнодорож локомотив",
    "самолёт": "самолет аэропорт авиа",
    "корабль": "корабл судн причал",
    "автобус": "автобус трамва троллейбус электробус",
    "велосипед": "велосипед самокат",
    "курьер": "курьер доставк погрузк",
    "датчик": "датчик сенсор",
    "камера": "видеокамер",
    "солнечные панели": "солнечн ветрян турбин электростанц",
    "батарея": "батаре аккумулятор",
    "кабель": "кабел оптоволок",
    "станция": "станци вокзал",
    "стройка": "стройк стройплощадк строител",
    "шахта": "шахт месторожден скважин нефтян буров",
    "кофе": "кофе",
    "продукты": "хлеб овощ фрукт молок",
    "лекарства": "лекарств таблетк вакцин шприц",
    "мебель": "мебел кресл",
    "одежда": "одежд обув",
    "музей": "музе библиотек театр",
    "стадион": "стадион спортзал",
    "оператор": "оператор колл-центр контакт-центр",
    "инженер": "инженер",
}.items():
    for _w in _words.split():
        _THINGS[_w] = _key
# a stem that starts other, abstract words: those words are not the thing («классный», «камерный», «столовая ложка»)
_NOT_THINGS = ("мобильност", "экранир", "станцион", "серверлес")
# short words that name a thing only as themselves («метро», not «метров»; «лес», not «лестница»)
_EXACT = {w: k for k, ws in {"лес": "лес леса лесу", "станция": "метро", "стройка": "кран краны крана", "камера": "камера камеры камеру камерой",
                             "лёд": "лед льда льду", "корабль": "порт порта порту"}.items() for w in ws.split()}
_TOKEN_RE = re.compile(r"[а-яеa-z][а-яеa-z\-]*", re.I)


def concrete_subject(text: str) -> tuple[str, str] | None:
    """(what the picture shows, the word of the text that names it) — the first thing one can see named in `text`
    (a heading: «Перевод на сканеры и 6 кладовщиков стоят 2,9 млн ₽ в год» → сканер / «сканеры»); None for a text of
    money, plans and percentages («Расходы выросли на 12%»)."""
    low = (text or "").lower().replace("ё", "е")
    for m in _TOKEN_RE.finditer(low):
        w = m.group(0).strip("-")
        if w in _EXACT:
            return _EXACT[w], w
        if len(w) < 4 or w.startswith(_NOT_THINGS):
            continue
        stem = max((s for s in _THINGS if w.startswith(s)), key=len, default=None)
        if stem is not None:
            return _THINGS[stem], w
    return None


def _fits_picture(s: Any) -> bool:
    """A content slide short enough for half of its width: no table, chart, steps, columns or formula; at most two cards
    (three cards in half a slide broke «Канареечн/ая» — the jury's R07 s7), three figures, four points."""
    c = s.content
    if s.kind.value in _FRAMES or s.kind.value in _WIDE_KINDS or getattr(s, "continues", None) or c.photo_slot:
        return False
    if c.table is not None or c.chart is not None or c.chart2 is not None or c.code is not None or c.formula or c.quote or c.image_hint:
        return False
    if len(c.items) > 2 or len(c.columns) > 0 or len(c.numbers) > 3 or (c.items and c.numbers):
        return False
    words = " ".join([*c.bullets, *c.paragraphs, *(f"{it.title} {it.text} {' '.join(it.bullets)}" for it in c.items)])
    return len(c.bullets) <= 4 and len(words) <= 360


def _pick(cands: list[tuple[int, str]], k: int, used: set[str], n: int) -> list[tuple[int, str]]:
    """Up to k (position, thing) pairs of a deck of n slides: each thing once (and none of `used`), never two
    neighbours, spread over the deck (the candidate nearest each k-th share of it)."""
    fresh: list[tuple[int, str]] = []
    for i, thing in sorted(cands):
        if thing not in used and all(thing != t for _, t in fresh):
            fresh.append((i, thing))
    out: list[tuple[int, str]] = []
    for j in range(max(0, k)):
        target = (j + 0.5) * n / k
        pool = [c for c in fresh if c not in out and all(abs(c[0] - o[0]) > 1 for o in out)]
        if not pool:
            break
        out.append(min(pool, key=lambda c: (abs(c[0] - target), c[0])))
    return sorted(out)


# the owner (18.10): «если стоит настройка генерировать изображения, они ОБЯЗАНЫ быть в презентации» — with pictures on
# a deck has at least this many (1 up to 7 slides, 2 from 8): the slides that name a thing one can see first, else a
# concrete scene of the deck's own topic (its place, its people at work, its product in use — never a symbol)
def min_pictures(n: int) -> int:
    return 1 if n <= 7 else 2


# a scene is the text model's reading of the slide itself — its process, place, object or result — never a fixed
# angle: «люди темы за работой» gave «a team at a table» on 7 of 17 pictures of the jury's round 3, unrelated to «Просим
# 120 млн» and twice in one deck; the deck's other pictures go to the model with it (images/service.py), so none repeats
SCENE = "Сцена по смыслу слайда"


def _scene_hint(k: int, head: str) -> str:
    return f"{SCENE} — {head}"


def _first_words(s: Any, head: str, limit: int = 140) -> str:
    """The slide's own first words past its heading (its first point, paragraph, card or figure), up to `limit`."""
    c = s.content
    for t in [*c.bullets, *c.paragraphs, *(f"{it.title} {it.text}".strip() for it in c.items), *(f"{n.value} {n.label}".strip() for n in c.numbers), s.subtitle or "", s.takeaway or ""]:
        t = " ".join(str(t or "").split())
        if t and t.lower() not in (head or "").lower() and not is_picture_note(t):
            return H.strip_end(t[:limit].rsplit(" ", 1)[0] if len(t) > limit else t)
    return ""


def _place(outlines: list[Any], first: Any, i: int, hint: str) -> None:
    """The place on slide i of the first variant and on the same slide of every other one (by the text's slide number,
    else by position)."""
    ref = first.slides[i].spec_ref
    for o in outlines:
        host = next((s for s in o.slides if ref is not None and s.spec_ref == ref and _fits_picture(s)), None)
        if host is None and ref is None and i < len(o.slides) and _fits_picture(o.slides[i]):
            host = o.slides[i]
        if host is None:
            continue
        host.content.photo_slot = AUTO_LABEL
        host.content.photo_hint = hint
        host.content.photo_own = False


def ensure_pictures(outlines: list[Any], brief_text: str = "") -> list[str]:
    """Pictures on the slides where they help. A short content slide whose heading names a thing one can see (a place,
    a product, a device, a process at work — `concrete_subject`) gets a place first, each showing another thing than
    the deck's other pictures (the author's included), at most about one per PICTURE_SHARE slides. A deck with fewer
    than `min_pictures` gets the rest on its roomiest short slides as scenes of what each of them says (`SCENE`: its
    process, place, object or result as the text model reads it — never a scene the deck already has). The place is described by its thing (or scene)
    and the slide's heading (the text's «Слайд N. …» heading when it has one), so the variants share one picture per
    place. Returns what was done, for the warnings."""
    outlines = [o for o in outlines if o is not None and getattr(o, "slides", None)]
    if not outlines:
        return []
    heads = {int(m.group(1)): H.strip_end(m.group(2)) for m in _SLIDE_HEAD_RE.finditer(brief_text or "")}
    first = outlines[0]
    n = len(first.slides)
    need = min_pictures(n)
    cap = max(need, round(n / PICTURE_SHARE))
    placed = [s for s in first.slides if s.content.photo_slot and not s.content.photo_own]
    if len(placed) >= cap:
        return []
    used = {t[0] for t in (concrete_subject(f"{s.content.photo_hint or ''} {s.headline or ''}") for s in placed) if t}

    def head_of(i: int) -> str:
        s0 = first.slides[i]
        return (heads.get(s0.spec_ref) if s0.spec_ref is not None else None) or H.strip_end(s0.headline or "")

    def said_of(i: int) -> str:
        """The heading and the slide's first words: a heading alone («Что просим») gave the text model nothing to
        picture, and it drew a server room for a request to hire sales managers (live run of 20.10)."""
        head = head_of(i)
        more = _first_words(first.slides[i], head)
        return f"{head}. {more}" if more else head

    fits = [i for i, s in enumerate(first.slides) if _fits_picture(s)]
    cands = [(i, got[0]) for i in fits if (got := concrete_subject(first.slides[i].headline or "")) is not None]
    out: list[str] = []
    picked = _pick(cands, cap - len(placed), used, n)
    for i, thing in picked:
        _place(outlines, first, i, f"{H.cap_first(thing)} — {said_of(i)}")  # the thing itself, not the heading's word
        out.append(f"picture added on slide {i + 1} ({thing}: {head_of(i)[:60]}): the slide shows something one can see")
    short = need - len(placed) - len(picked)
    if short > 0:
        # pictures are on and the text names nothing one can see: scenes of the deck's topic on its roomiest short
        # slides (fewest words first), never next to another picture
        taken = {i for i, _ in picked} | {k for k, s in enumerate(first.slides) if s.content.photo_slot}
        free = [i for i in fits if i not in taken and all(abs(i - t) > 1 for t in taken)] or [i for i in fits if i not in taken]
        room = sorted(free, key=lambda i: (len(_slide_text(first.slides[i])), i))[: max(short * 3, short)]
        scenes = _pick([(i, f"scene{k}") for k, i in enumerate(sorted(room))], short, set(), n)
        for k, (i, _) in enumerate(scenes):
            _place(outlines, first, i, _scene_hint(k, said_of(i)))
            out.append(f"picture added on slide {i + 1} (a scene of the deck's topic: {head_of(i)[:60]}): pictures are on and no heading names a thing one can see")
    if not out and not placed:
        out.append("no picture added: no short content slide has room for one")
    return out


def pass_picture_on(outline: Any, oslide: Any, hint: str | None) -> Any:
    """An added picture the slide had no room for (rendering/synth.py) goes to the next short slide of the deck still
    without one, described by the same thing (or scene) and that slide's heading. Returns that slide, or None."""
    slides = list(getattr(outline, "slides", None) or [])
    at = next((k for k, s in enumerate(slides) if s is oslide or s.id == oslide.id), None)
    if at is None:
        return None
    thing = (hint or "").split(" — ", 1)[0].strip() or SCENE
    for s in slides[at + 1:]:
        if _fits_picture(s) and not s.content.photo_slot:
            s.content.photo_slot = AUTO_LABEL
            s.content.photo_hint = f"{thing} — {H.strip_end(s.headline or '')}"
            s.content.photo_own = False
            return s
    return None


# the owner's minimum and the strict check together (the coordinator, 20.10): a picture the vision model rejected twice
# moves to another slide — the one whose meaning is most a thing one can see (an example, an application, a place, a
# device; for a lecture on the derivative a speedometer for «мгновенная скорость») — at most this many more per deck
SECOND_CHANCES = 2
_CONCRETE_HINT_RE = re.compile(r"пример|применени|кейс|на практике|в жизни|скорост|движени|автомобил|машин[аы]\b|поезд|опыт|эксперимент|"
                               r"измерени|наблюдени|клиент|покупател|пользовател|сотрудник|команд[аы]\b|город|завод|склад|магазин", re.I)
_ABSTRACT_RE = re.compile(r"определени|формул|правил[оа]\b|правила|теорем|свойств|аксиом|лемм|доказательств|обозначени|термин", re.I)


def concreteness(s: Any) -> int:
    """How much a slide's meaning is a thing one can see: a thing named in its heading (3), in its text (2), an example,
    an application or people at work (2); a definition, a formula, a rule last (−2)."""
    head = s.headline or ""
    text = _slide_text(s)
    score = 3 if concrete_subject(head) else (2 if concrete_subject(text) else 0)
    if _CONCRETE_HINT_RE.search(text):
        score += 2
    if _ABSTRACT_RE.search(head) or (getattr(s.content, "formula", None) or "").strip():
        score -= 2
    return score


def second_chance(outline: Any, tried: set[str], want: int) -> list[tuple[int, str]]:
    """Up to `want` (position, description) pairs for pictures that replace rejected ones: short content slides still
    without a picture and not tried before, the most concrete first (`concreteness`), never next to a picture; each
    described as a scene of what the slide says."""
    slides = list(getattr(outline, "slides", None) or [])
    taken = {k for k, s in enumerate(slides) if s.content.photo_slot}
    cands = [(k, s) for k, s in enumerate(slides) if s.id not in tried and k not in taken and _fits_picture(s)]
    cands.sort(key=lambda ks: (-concreteness(ks[1]), ks[0]))
    out: list[tuple[int, str]] = []
    apart = [ks for ks in cands if all(abs(ks[0] - t) > 1 for t in taken)]
    for k, s in apart + [ks for ks in cands if ks not in apart]:
        if len(out) >= want:
            break
        if any(abs(k - j) <= 1 for j, _ in out):
            continue
        head = H.strip_end(s.headline or "")
        more = _first_words(s, head)
        out.append((k, _scene_hint(0, f"{head}. {more}" if more else head)))
    return out
