"""Что просил человек — и выполнено ли (жюри 5: колода UI1 из 3 слайдов при «5 слайдов» показана «94 · Ошибок нет»;
модель находила напечатанную директиву «сделай 8 слайдов, без картинок», а исправление её не убирало).

- `slide_count_unmet` — текст просит N слайдов («5 слайдов», «на 8 слайдов», «6–8 слайдов»), в колоде другое число;
- `author_note_printed` — на слайде напечатано то, что автор сказал составителю: размер колоды, «без картинок»,
  «не выдумывай цифру», «таблицы приложил», «(наметки)»; исправление убирает фрагмент (`unsay_note`);
- `plan_point_unanswered` — колода с данными: вопрос плана напечатан, а не отвечен («Больше половины?» без числа),
  пункт плана перепечатан как есть («1) общий итог Q3 против Q2»), пункт плана не раскрыт ни на одном слайде.

Все три — замечания аудита: видны человеку и снижают оценку."""

from __future__ import annotations

import re
from typing import Optional

from verstka.audit.checks.common import fix
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.outline import OutlineSlide

SLIDE_COUNT_UNMET = CheckSpec(
    id="slide_count_unmet", title="Число слайдов не то, что просили в тексте", severity="error", category="integrity",
    description=("Текст просит число слайдов («5 слайдов», «на 8 слайдов», «6–8 слайдов» — по тем же правилам, что читает "
                 "сборка), а в презентации другое число. Разница в один слайд — предупреждение, больше — ошибка."),
)
AUTHOR_NOTE_PRINTED = CheckSpec(
    id="author_note_printed", title="На слайде напечатано указание автора", severity="error", category="integrity",
    description=("Заголовок, подзаголовок, подпись или строка слайда повторяет то, что автор сказал составителю, а не "
                 "зрителю: число слайдов («сделай 8 слайдов»), «без картинок», «не выдумывай цифру», «таблицы приложил», "
                 "«цели — в регламенте», «(наметки)». Исправление убирает фрагмент."),
)
PLAN_POINT_UNANSWERED = CheckSpec(
    id="plan_point_unanswered", title="Пункт плана не раскрыт", severity="warn", category="integrity",
    description=("Презентация из плана и данных: вопрос плана напечатан на слайде как есть, без ответа числом; пункт плана "
                 "перепечатан строкой («1) общий итог Q3 против Q2»), а не раскрыт; пункт плана не нашёлся ни на одном слайде."),
)

# what the author says to the deck-maker, surely (the rules of planning/directives.py for the notes — kept here on their
# own, without «проверь» and «по-моему», which a text for the audience may say too: «Проверьте настройки перед запуском»)
_V = r"(?:и\s+|а\s+|но\s+|только\s+)?"
_PIC = r"(?:картин\w*|изображени\w*|фото\w*|иллюстраци\w*|рисунк\w*|анимаци\w*)"
_NOTES = (
    re.compile(rf"^{_V}(?:без|с|со)\s+{_PIC}(?:\s+(?:и|или)\s+{_PIC})?$", re.I),
    re.compile(rf"^{_V}{_PIC}\s+(?:не\s+(?:нужн\w*|надо|став\w*|добавля\w*|вставля\w*|рису\w*)|ненужн\w*)$", re.I),
    re.compile(rf"^{_V}(?:ничего\s+)?(?:не\s+(?:выдумыва|придумыва|додумыва|сочиня|фантазир|домысл|выдума|придума)\w*|без\s+(?:выдумок|домыслов|фантазий))\b", re.I),
    re.compile(r"^(?:выдумывать|придумывать|додумывать)\s+(?:ничего\s+)?не\s+(?:надо|нужно|стоит)\b", re.I),
    re.compile(r"(?:^|\s)(?:во\s+вложени\w*|в\s+приложени\w*|приложил\w*|приложены|приложена|приложен|прикрепил\w*|прилагаю|прикладываю|в\s+аттаче)$", re.I),
    re.compile(r"^[^—–:]{1,70}?\s*[—–-]\s*(?:в|во)\s+(?:файл\w*|таблиц\w*|вложени\w*|приложени\w*|баз\w*\s+знаний|регламент\w*|положени\w*|"
               r"отч[её]т\w*|\w*меморандум\w*|документ\w*|материал\w*|excel|xlsx|csv)(?:\s+[\w-]+){0,2}$", re.I),
    re.compile(r"^(?:все\s+|полные\s+|сырые\s+)?(?:данные|цифры|таблиц\w*|файл\w*|выгрузк\w*)(?:\s+[\w«»-]+){0,4}?\s+(?:в|во)\s+"
               r"(?:файл\w*|таблиц\w*|вложени\w*|приложени\w*)(?:\s+(?:ниже|выше))?$", re.I),
    re.compile(r"^(?:база\s+знаний|в\s+базе\s+знаний)$", re.I),
    re.compile(r"^(?:наметки|наброс\w*|черновик\w*|драфт|draft|wip|todo|tbd|не\s+финал\w*|сыро\w*|для\s+себя|пока\s+наброс\w*)$", re.I),
    re.compile(r"^(?:о\s+ч[её]м\s+(?:хочу|хотим|хотел\w*|буду|будем|нужно|надо)\s+рассказать|что\s+(?:хочу|хотим)\s+рассказать)$", re.I),
)
# the deck's size said as a rule: «сделай 8 слайдов», «5 слайдов», «не больше 10 слайдов»
_COUNT_NOTE = re.compile(
    r"^(?:(?:сделай(?:те)?|подготовь(?:те)?|собери(?:те)?|нужно|нужн[аы]|надо|давай|уложись\s+в|уложиться\s+в|хватит|примерно|около|"
    r"всего|ровно|итого|максимум|не\s+больше|не\s+более|на|до)\s*)*\d{1,2}(?:\s*[–—-]\s*\d{1,2})?\s+слайд(?:ов|а)?$", re.I)


def _fields(s: OutlineSlide) -> list[tuple[str, Optional[int], str]]:
    """(field, index, text) of what the slide shows in words."""
    c = s.content
    out: list[tuple[str, Optional[int], str]] = [("headline", None, s.headline or ""), ("subtitle", None, s.subtitle or ""),
                                                 ("takeaway", None, s.takeaway or "")]
    out += [("bullets", k, b) for k, b in enumerate(c.bullets)]
    out += [("paragraphs", k, b) for k, b in enumerate(c.paragraphs)]
    out += [("items", k, " ".join(x for x in (it.title, it.text) if x)) for k, it in enumerate(c.items)]
    return [x for x in out if x[2].strip()]


def _clauses(text: str) -> list[str]:
    t = " ".join((text or "").replace(" ", " ").split())
    parts: list[str] = []
    for m in re.finditer(r"\(([^()]{1,120})\)?", t):
        parts += re.split(r"[,;]\s*", m.group(1))
    body = re.sub(r"\([^()]*\)?", " ", t)
    for sent in re.split(r"(?<=[.!?…])\s+", body):
        parts += re.split(r",\s+|;\s+", sent)
    return [p.strip(" .!?…,;:—–-«»\"") for p in parts if p.strip(" .!?…,;:—–-«»\"")]


def author_notes_in(text: str) -> list[str]:
    """The clauses of `text` that are surely the author's words to the deck-maker (the deck's size, no pictures, never
    invent, pointers to the material, the author's marks)."""
    return [c for c in _clauses(text) if _COUNT_NOTE.match(c) or any(rx.search(c) for rx in _NOTES)]


def without_notes(text: str) -> str:
    """`text` without its clauses of author's notes; the punctuation and brackets around a cut tidied."""
    t = " ".join((text or "").replace("\u00a0", " ").split())
    for c in sorted(set(author_notes_in(t)), key=len, reverse=True):
        t = re.sub(r"\s*[,;]?\s*" + re.escape(c) + r"\s*", " ", t)
    t = re.sub(r"\(\s*[,;]?\s*\)|\(\s*$", "", t)
    t = re.sub(r"\(\s*[,;]\s*", "(", t)
    t = re.sub(r"\s+([,.;:!?)])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,;:—–-")
    return t


def unsay(s: OutlineSlide) -> list[str]:
    """The slide's words without the author's notes (autofix `unsay_note`); what was taken out. A line left with nothing
    goes; a headline left with nothing keeps its own words."""
    done: list[str] = []
    for name in ("headline", "subtitle", "takeaway"):
        t = getattr(s, name) or ""
        if t and author_notes_in(t):
            new = without_notes(t)
            if new.strip(" .,;:—–-"):
                setattr(s, name, new)
                done.append(f"{name}: «{t}» → «{new}»")
            elif name != "headline":
                setattr(s, name, None)
                done.append(f"{name}: «{t}» убран")
    c = s.content
    for key in ("bullets", "paragraphs"):
        lines = []
        for b in getattr(c, key):
            if author_notes_in(b):
                new = without_notes(b)
                if new.strip(" .,;:—–-"):
                    lines.append(new)
                done.append(f"{key}: «{b}»")
            else:
                lines.append(b)
        setattr(c, key, lines)
    for it in c.items:
        for name in ("title", "text"):
            t = getattr(it, name) or ""
            if t and author_notes_in(t):
                new = without_notes(t)
                setattr(it, name, new if new.strip(" .,;:—–-") else ("" if name == "text" else t))
                done.append(f"item {name}: «{t}»")
    return done


def asked_of(ctx: AuditContext) -> tuple[str, Optional[int]]:
    """(the person's text, the slide count the request set explicitly — the stepper —, None when left to the text). The
    request is read from the generation's record beside the audited file (a variant's deck or its scratch copy) when the
    caller passes no brief text: a data deck's audit gets none, its figures are checked against the data."""
    import json

    text, slides = ctx.brief_text or "", None
    p = ctx.pptx
    for d in ([p.parent, p.parent.parent] if p is not None else []):
        g = d / "generation.json"
        if g.is_file():
            try:
                meta = json.loads(g.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                break
            text = text or str(meta.get("brief") or "")
            n = meta.get("slides")
            slides = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None
            break
    return text, slides


def _ir_index(ctx: AuditContext, oid: str) -> int:
    return next((s.index for s in ctx.ir.slides if s.outline_id == oid), 0)


@check(SLIDE_COUNT_UNMET)
def slide_count_unmet(ctx: AuditContext) -> list[Issue]:
    from verstka.planning.brief import slide_count_of, slide_range

    text, set_n = asked_of(ctx)
    if not ctx.ir.slides or (not text.strip() and set_n is None):
        return []
    have = len(ctx.ir.slides)
    r = slide_range(text) if set_n is None else None
    if set_n is not None:
        # the count the person set (the stepper, or «slides» of the request): it overrides the text (api `_brief_from_request`)
        if set_n == have:
            return []
        want, said = set_n, str(set_n)
    elif r is not None:
        lo, hi = r
        if lo <= have <= hi:
            return []
        want, said = (lo if have < lo else hi), f"{lo}–{hi}"
    else:
        want = slide_count_of(text)
        if want is None or want == have:
            return []
        said = str(want)
    from verstka.data.words import plural

    # «на 12 слайдов» над планом «Слайд 1…12»: the person counts their own slides, the cover comes on top of them
    first = ctx.outline.slides[0] if ctx.outline is not None and ctx.outline.slides else None
    if have == want + 1 and first is not None and getattr(first.kind, "value", first.kind) == "title":
        return []
    gap = abs(have - want)
    def n_slides(n: int) -> str:
        return plural(n, "слайд", "слайда", "слайдов")

    asked = f"{want} {n_slides(want)}" if r is None else f"{said} {n_slides(r[1])}"
    return [ctx.new_issue(
        SLIDE_COUNT_UNMET, 0, f"В тексте просили {asked}, а в презентации {have} {n_slides(have)}",
        severity="error" if gap >= 2 else "warn",
        suggestion=("Пунктов плана с содержанием меньше, чем слайдов: допишите, что показать, или соберите ещё раз" if have < want
                    else "Сократите план или попросите меньше слайдов"),
        details={"asked": want, "have": have},
    )]


@check(AUTHOR_NOTE_PRINTED)
def author_note_printed(ctx: AuditContext) -> list[Issue]:
    if ctx.outline is None:
        return []
    out: list[Issue] = []
    for osl in ctx.outline.slides:
        notes = [n for _, _, t in _fields(osl) for n in author_notes_in(t)]
        if not notes:
            continue
        idx = _ir_index(ctx, osl.id)
        if not idx:
            continue
        said = "; ".join(f"«{n[:60]}»" for n in dict.fromkeys(notes))
        out.append(ctx.new_issue(
            AUTHOR_NOTE_PRINTED, idx, f"На слайде напечатано указание автора, а не текст для зрителя: {said}",
            suggestion="Указание выполняется, а не печатается — уберите его со слайда.",
            autofix=fix("unsay_note", "убрать со слайда указание автора", outline_id=osl.id), details={"notes": notes[:6]},
        ))
    return out


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^\wё%]+", " ", (t or "").lower().replace("ё", "е")).split())


# the plan's own question words and asks — not what the point is about
_STOP = frozenset({"сколь", "какие", "какой", "какая", "каких", "почем", "сравн", "покаж", "прост", "снача", "главн", "проти",
                   "котор", "между", "тольк", "очень", "более", "менее", "этого", "также", "потом", "здесь", "нужно", "давай",
                   "графи", "сдела", "добав", "расск", "хочу", "чтобы", "вопро"})


def _stems(t: str) -> list[str]:
    return [w[:5] for w in re.findall(r"[а-яёa-z]{5,}", (t or "").lower().replace("ё", "е")) if w[:5] not in _STOP]


_POINT_RE = re.compile(r"^\s*(?:[-–—•*·]|\d{1,2}\s*[.)])\s+(.+?)\s*$")


def _plan_points(text: str) -> list[str]:
    """The points of the author's plan: its list lines, without what the author says to the deck-maker."""
    out = []
    for line in (text or "").splitlines():
        m = _POINT_RE.match(line)
        if not m or line.lstrip().startswith("|"):
            continue
        body = without_notes(m.group(1))
        if len(_stems(body)) >= 2:
            out.append(body.strip())
    return out


@check(PLAN_POINT_UNANSWERED)
def plan_point_unanswered(ctx: AuditContext) -> list[Issue]:
    o = ctx.outline
    text, _ = asked_of(ctx)
    if o is None or not text.strip() or not any(s.data is not None for s in o.slides):
        return []  # a deck of the author's text shows the text as written; the check is about a plan answered by data
    points = _plan_points(text)
    if not points:
        return []
    out: list[Issue] = []
    shown = {s.id: _fields(s) for s in o.slides}
    for p in points:
        np = _norm(re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", p))
        printed = None
        for s in o.slides:
            for name, _, t in shown[s.id]:
                nt = _norm(re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", t))
                if np and nt and (nt == np or (len(np) >= 20 and np in nt and len(nt) <= len(np) + 6)):
                    printed = (s, name, t)
                    break
            if printed:
                break
        if printed is not None:
            s, name, t = printed
            if s.kind.value in ("title", "section", "thanks"):
                continue
            q = p.rstrip().endswith("?")
            if q and re.search(r"\d", t) and not re.search(r"\d", p):
                continue  # the question with its answer
            idx = _ir_index(ctx, s.id)
            if not idx:
                continue
            msg = (f"Вопрос плана напечатан, а не отвечен: «{p[:80]}»" if q else f"Пункт плана перепечатан как есть, а не раскрыт: «{p[:80]}»")
            out.append(ctx.new_issue(
                PLAN_POINT_UNANSWERED, idx, msg,
                suggestion="Ответ на пункт плана — вывод с числом из данных; соберите ещё раз или попросите слайд об этом.",
                details={"point": p, "how": "question" if q else "printed"},
            ))
            continue
        st = _stems(p)
        best = 0.0
        for s in o.slides:
            words = " ".join(t for _, _, t in shown[s.id]) + " " + (s.notes or "")
            if s.content.chart is not None:
                words += " " + " ".join(str(c) for c in s.content.chart.categories) + " " + " ".join(x.name for x in s.content.chart.series)
            have = set(_stems(words))
            best = max(best, sum(1 for w in st if w in have) / len(st))
        if best < 0.5:
            out.append(ctx.new_issue(
                PLAN_POINT_UNANSWERED, 0, f"Пункт плана не раскрыт ни на одном слайде: «{p[:80]}»",
                suggestion="Допишите в план, какие данные о нём показать, или соберите ещё раз.",
                details={"point": p, "how": "missing"},
            ))
    return out
