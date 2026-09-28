"""The remarks of one slide — the audit issues a person sees on the stage — and the words the slide fix speaks about
them (REMARKS_SPEC §2.3): check titles, where a remark sits on the slide, the designer's note, the critic's line, which
remarks a new version of the slide fixed, the check step's line and the reply for the history and the chat.

Pure: no files, no models. The numbering follows the UI (severity first, then reading order, whole-slide remarks last
within their severity), so «замечание 2» means the same thing on the stage, in the note and in the reply."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional, Sequence

from verstka.ru import ru_count
from verstka.schemas.audit import Issue

# what the slide designer can fix by redesigning the slide (its content, its form, its density)
CONTENT_CHECKS = frozenset({
    "text_overflow", "text_outside_card", "overlap", "word_break", "table_cell_wrap", "too_many_bullets",
    "bullet_too_long", "table_too_big", "too_many_series", "fill_ratio", "empty_slide", "content_missing",
    "placeholder_text", "duplicate_slides", "figure_not_in_brief", "chart_missing_labels", "slide_content",
    "deck_coherence", "content_in_notes", "timeline_order", "slide_is_picture",
    # the words of a written deck (audit/checks/writing.py): the designer rewrites the line from the slide's text
    "line_fragment", "figure_is_time", "chart_mixed_units", "duplicate_heading", "orphan_opener",
})
# fixed in place first (an element moved back inside, a smaller size); they reach the designer only when they survive
INPLACE_FIRST = frozenset({"text_clipped", "out_of_bounds", "margin_violation"})
# the template's own style: fixed in place by the rules, never sent to the designer
TEMPLATE_CHECKS = frozenset({
    "font_not_in_template", "size_not_in_scale", "color_not_in_palette", "layout_not_from_template", "chrome_moved",
    "contrast_low", "table_contrast_low", "image_stretched", "grid_alignment",
})

# the titles the UI shows for these checks (REMARKS_SPEC §3.6) — the chat and the history say the same words
UI_TITLES = {
    "slide_content": "Содержание слайда",
    "deck_coherence": "Связность презентации",
    "contrast_low": "Контраст текста к фону ниже 4,5:1",
    "font_not_in_template": "Шрифт не из шаблона",
    "fill_ratio": "Слайд слишком пустой или слишком плотный",
    "chrome_moved": "Логотип или колонтитул не на месте",
}
_SEVERITY_TITLE = {"error": "Ошибка", "warn": "Предупреждение", "info": "Замечание"}
_SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}

_FIT = "сократи текст этого блока или раздели его на пункты, чтобы он поместился"
_SHORTER = "используй слова короче или дай блоку больше места"
FIX_HINT: dict[str, str] = {
    "text_clipped": _FIT, "out_of_bounds": _FIT, "text_overflow": _FIT, "text_outside_card": _FIT,
    "overlap": "разведи блоки или убери лишний",
    "margin_violation": "оставь поля у краёв слайда свободными",
    "word_break": _SHORTER, "table_cell_wrap": _SHORTER,
    "too_many_bullets": "не больше 6 пунктов — объедини или сократи",
    "bullet_too_long": "каждый пункт — не длиннее 15 слов",
    "table_too_big": "не больше 7 строк и 5 колонок — сгруппируй или покажи главное",
    "too_many_series": "не больше 5 рядов на диаграмме",
    "fill_ratio": "слайд слишком пустой или слишком плотный — добавь содержание из текста или сократи",
    "empty_slide": "добавь содержание из текста этого слайда",
    "content_missing": "верни пропавшие тексты: форма слайда должна вместить их все",
    "placeholder_text": "убери текст-заглушку",
    "figure_not_in_brief": "оставь только числа из исходного текста",
    "chart_missing_labels": "подпиши значения или оси диаграммы",
    "duplicate_slides": "сделай слайд непохожим на соседний: другой вывод или форма",
    "content_in_notes": "верни эту строку на слайд: сократи или уплотни основной блок, чтобы под ним осталось для неё место",
    "timeline_order": "поставь пункты с датами по порядку — от ранней даты к поздней",
    "slide_is_picture": "добавь на слайд текст: заголовок и главное из текста этого слайда",
    "content_over_art": "не клади текст на рисунок шаблона: сократи блок или выбери форму, которая оставляет рисунок свободным",
    "line_fragment": "возьми из текста слайда предложение целиком или сократи его так, чтобы остались сказуемое и смысл — без обрыва на середине",
    "figure_is_time": "не делай крупным числом время суток или номер проекта, модели: возьми настоящую величину из текста или покажи строку без крупного числа",
    "chart_mixed_units": "на одной диаграмме — одна величина в одних единицах: покажи разные числа карточками или раздели на две диаграммы",
    "duplicate_heading": "дай слайду свой заголовок — о главном именно на этом слайде",
    "orphan_opener": "начни строку с того, о ком или о чём она: замени «Также», «Этот», «она», «они» на имя или название из текста",
}

_NOTE_LEAD = (
    "- The quality check of the rendered slide found these problems (where they are on the slide in brackets). Fix every "
    "one of them in your design and keep everything else of your previous design:"
)
_WISH_LINE = (
    "- The person also asks: «{wishes}». Do exactly what they ask; their request overrides the form the brief asked for "
    "this slide. Every figure still comes from the source text or the data list."
)
_MAX_MISSING = 12  # the missing texts a content_missing line names


def _clean_title(title: str) -> str:
    title = re.sub(r"\s*\((?:VLM|LLM)\)", "", title).strip()
    return re.sub(r"(\d)\.(\d)", r"\1,\2", title)


@lru_cache(maxsize=1)
def check_titles() -> dict[str, str]:
    """check_id → its title in plain Russian (the list of /api/checks, «(VLM)» and «(LLM)» dropped, the UI's words)."""
    from verstka.audit.model_checks import DECK_COHERENCE, SLIDE_CONTENT
    from verstka.audit.registry import all_checks

    specs = [spec for spec, _ in all_checks()] + [SLIDE_CONTENT, DECK_COHERENCE]
    out = {s.id: _clean_title(s.title) for s in specs}
    out.update(UI_TITLES)
    return out


def title_of(issue: Issue, titles: Optional[dict[str, str]] = None) -> str:
    t = (titles if titles is not None else check_titles()).get(issue.check_id)
    return t or _SEVERITY_TITLE.get(issue.severity, "Замечание")


def lower_first(text: str) -> str:
    """«Часть контента…» → «часть контента…» (an abbreviation like «VK» stays)."""
    if len(text) >= 2 and text[0].isupper() and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?…" else text + "."


# ---------------------------------------------------------------------------- which remarks, in which order


def is_stage(issue: Issue) -> bool:
    """A remark the stage shows: errors, warnings and the model's own remarks on a slide (the rules' info notes, e.g.
    grid_alignment on almost every slide, live only in the drawer)."""
    return issue.slide >= 1 and not (issue.severity == "info" and issue.kind != "model")


def stage_remarks(issues: Iterable[Issue], slide: int) -> list[Issue]:
    return order_remarks([i for i in issues if i.slide == slide and is_stage(i)])


def _boxes(bboxes: Sequence) -> list[tuple[float, float, float, float]]:
    """Usable boxes, clamped to the slide: (x0, y0, x1, y1) in fractions."""
    out = []
    for b in bboxes or []:
        raw = [b.get(k) if isinstance(b, dict) else getattr(b, k, None) for k in ("x", "y", "w", "h")]
        try:
            x, y, w, h = (float(v or 0.0) for v in raw)
        except (TypeError, ValueError):
            continue
        x0, y0, x1, y1 = max(0.0, x), max(0.0, y), min(1.0, x + w), min(1.0, y + h)
        if x1 - x0 > 0.002 and y1 - y0 > 0.002:
            out.append((x0, y0, x1, y1))
    return out


def order_remarks(remarks: Iterable[Issue]) -> list[Issue]:
    """Severity first (error → warn → the model's info), then the top-left of the first box (y, then x); whole-slide
    remarks (no usable box) last within their severity."""

    def key(pair: tuple[int, Issue]):
        k, i = pair
        boxes = _boxes(i.bboxes)
        first = boxes[0] if boxes else None
        return (_SEVERITY_RANK.get(i.severity, 3), first is None, round(first[1], 4) if first else 0.0, round(first[0], 4) if first else 0.0, k)

    return [i for _, i in sorted(enumerate(remarks), key=key)]


def where(bboxes: Sequence) -> str:
    """Where the remark sits: «внизу слева», «в центре», «на большей части слайда»; "" without a usable box."""
    boxes = _boxes(bboxes)
    if not boxes:
        return ""
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    if (x1 - x0) * (y1 - y0) > 0.6:
        return "на большей части слайда"
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    v = "вверху" if cy < 1 / 3 else "посередине" if cy < 2 / 3 else "внизу"
    h = "слева" if cx < 1 / 3 else "по центру" if cx < 2 / 3 else "справа"
    return "в центре" if (v, h) == ("посередине", "по центру") else f"{v} {h}"


# ---------------------------------------------------------------------------- the designer's note and the critic's line


def hint_of(issue: Issue) -> Optional[str]:
    if issue.kind == "model":
        return (issue.suggestion or "").strip() or None
    return FIX_HINT.get(issue.check_id)


_NOTE_LINE_RU = {"takeaway": "вывод", "footnote": "сноска", "goal": "цель обложки"}


def _message_of(issue: Issue) -> str:
    """The remark's message; a content_missing one names every missing text it knows, a content_in_notes one the whole
    line that left the slide (the messages cut them)."""
    msg = " ".join((issue.message or "").split())
    details = issue.details or {}
    missing = details.get("missing") if issue.check_id == "content_missing" else None
    if isinstance(missing, list) and missing:
        names = [str(m).strip() for m in missing if str(m).strip()]
        head = msg.split(":", 1)[0] if ":" in msg else msg
        listed = ", ".join(f"«{m}»" for m in names[:_MAX_MISSING]) + ("…" if len(names) > _MAX_MISSING else "")
        msg = f"{head}: {listed}"
    lines = details.get("lines") if issue.check_id in ("line_fragment", "orphan_opener") else None
    if isinstance(lines, list) and len(lines) > 1:
        # every line the check found, each with its reason (the message names the first)
        what = "строки — обрывки предложений" if issue.check_id == "line_fragment" else "строки начинаются со ссылки на то, чего на слайде нет"
        parts = [f"«{' '.join(str(x.get('text') or '').split())}» ({x.get('why')})" for x in lines if isinstance(x, dict) and x.get("text")]
        if parts:
            msg = f"{what}: " + "; ".join(parts[:_MAX_MISSING])
    if issue.check_id == "content_in_notes" and str(details.get("text") or "").strip():
        what = _NOTE_LINE_RU.get(str(details.get("line") or ""), "строка")
        where_ = "есть только в заметках докладчика" if details.get("in_notes") else "нет ни на слайде, ни в заметках"
        msg = f"{what} «{' '.join(str(details['text']).split())}» {where_}"
    return msg


def remark_line(k: int, issue: Issue, titles: Optional[dict[str, str]] = None) -> str:
    """«1. Текст не поместился в свою рамку — «…» (внизу слева). Как исправить: сократи текст этого блока…»"""
    body = title_of(issue, titles)
    msg = _message_of(issue)
    if msg:
        body += f" — {msg}"
    place = where(issue.bboxes)
    if place:
        body += f" ({place})"
    line = f"{k}. {_sentence(body)}"
    hint = hint_of(issue)
    if hint:
        line += f" Как исправить: {_sentence(hint)}"
    return line


def remarks_note(remarks: Sequence[Issue], titles: Optional[dict[str, str]] = None, wishes: Optional[str] = None) -> str:
    """The designer's `issues` block of its revision mode: the remarks, numbered like the UI, with where they are and how
    to fix them; the person's wishes after them (only when there are some)."""
    lines: list[str] = []
    ordered = order_remarks(remarks)
    if ordered:
        lines.append(_NOTE_LEAD)
        lines += [f"  {remark_line(k, i, titles)}" for k, i in enumerate(ordered, 1)]
    wishes = (wishes or "").strip()
    if wishes:
        lines.append(_WISH_LINE.format(wishes=wishes))
    return "\n".join(lines)


def retry_line(kind: str) -> str:
    """The designer's second try, when its first version still lost content or broke the layout."""
    return (
        f"- Your previous version of this slide used the kind «{kind}», and the rendered slide still has the problems above: "
        "that kind cannot show all of this slide's content. Choose another kind that shows every text of the slide, or "
        "merge the lines so that nothing is lost."
    )


def remark_count(n: int) -> str:
    return ru_count(n, "замечание", "замечания", "замечаний")


def titles_phrase(remarks: Sequence[Issue], titles: Optional[dict[str, str]] = None, most: int = 3) -> str:
    """«часть запланированного контента пропала со слайда; текст обрезан краем слайда и ещё 2» — each title once."""
    names: list[str] = []
    for i in order_remarks(remarks):
        t = lower_first(title_of(i, titles))
        if t not in names:
            names.append(t)
    if not names:
        return ""
    text = "; ".join(names[:most])
    return text + (f" и ещё {len(names) - most}" if len(names) > most else "")


def critic_line(n: int, remarks: Sequence[Issue], titles: Optional[dict[str, str]] = None) -> str:
    """«Критик: слайд 8 — 1 замечание: часть запланированного контента пропала со слайда.»"""
    if not remarks:
        return f"Критик: слайд {n} — замечаний нет, переделываю по пожеланию."
    return f"Критик: слайд {n} — {remark_count(len(remarks))}: {titles_phrase(remarks, titles)}."


# ---------------------------------------------------------------------------- one remark across two audits


_ID_TAIL = re.compile(r"-(\d+)$")


def _pair_key(issue: Issue, tier: int) -> Optional[tuple]:
    """How sure two audits' issues are the same remark, strongest first: 1 — the same check on the same slide about the
    same elements with the same words; 2 — the same elements; 3 — the same words; 4 — the same check on the same
    slide. The slide is its outline id when the audit knows it (a moved slide keeps its remarks), else its number; a
    stage remark only ever pairs with a stage remark."""
    loc = ("o", issue.outline_id) if issue.outline_id else ("s", issue.slide)
    head = (loc, issue.check_id, is_stage(issue))
    els = tuple(sorted(issue.element_ids or []))
    msg = " ".join((issue.message or "").split())
    if tier == 1:
        return (*head, els, msg)
    if tier == 2:
        return (*head, els) if els else None
    if tier == 3:
        return (*head, msg)
    return head


def pair_issues(old: Sequence[Issue], new: Sequence[Issue], *, by_id: bool = False) -> dict[int, int]:
    """Which issue of a new audit is which issue of the old one: {index in `new`: index in `old`}.

    The audit numbers its issues through the whole deck (`{check}-{slide}-{n}`), so one remark gone on slide 1 renames
    every remark after it; this matches them by what they are instead. Tiers as `_pair_key`, each one-to-one; within a
    group of equal keys the issues pair from the end in number order, so when several remarks of a check are alike and
    fewer remain, the first ones in number order are the ones gone (the per-check count of REMARKS_SPEC §2.3). With
    `by_id`, equal ids pair first (the new audit's ids were carried over already)."""
    pairs: dict[int, int] = {}
    used: set[int] = set()
    if by_id:
        at = {i.id: k for k, i in enumerate(old)}
        for k, i in enumerate(new):
            b = at.get(i.id)
            if b is not None and b not in used:
                pairs[k] = b
                used.add(b)
    rank_old = {id(i): r for r, i in enumerate(order_remarks(old))}
    rank_new = {id(i): r for r, i in enumerate(order_remarks(new))}
    old_order = sorted(range(len(old)), key=lambda k: rank_old[id(old[k])])
    new_order = sorted(range(len(new)), key=lambda k: rank_new[id(new[k])])
    for tier in (1, 2, 3, 4):
        groups_old: dict[tuple, list[int]] = {}
        for k in old_order:
            if k not in used and (key := _pair_key(old[k], tier)) is not None:
                groups_old.setdefault(key, []).append(k)
        groups_new: dict[tuple, list[int]] = {}
        for k in new_order:
            if k not in pairs and (key := _pair_key(new[k], tier)) is not None:
                groups_new.setdefault(key, []).append(k)
        for key, ks in groups_new.items():
            olds = groups_old.get(key)
            if not olds:
                continue
            m = min(len(ks), len(olds))
            for a, b in zip(ks[len(ks) - m:], olds[len(olds) - m:]):
                pairs[a] = b
                used.add(b)
    return pairs


def carry_ids(old: Sequence[Issue], new: Sequence[Issue]) -> list[Issue]:
    """The new audit's issues with the ids they had in the old one (`pair_issues`), so a remark that stayed keeps its
    id through a fix or an edit. A remark the old audit did not have gets an id no old remark had: a fixed remark's id
    never comes back on another one."""
    pairs = pair_issues(old, new)
    reserved = {i.id for i in old}
    counter = max((int(m.group(1)) for i in (*old, *new) if (m := _ID_TAIL.search(i.id))), default=0)
    seen: set[str] = set()
    out: list[Issue] = []
    for k, issue in enumerate(new):
        nid = old[pairs[k]].id if k in pairs else issue.id
        if k not in pairs and (nid in reserved or nid in seen):
            while nid in reserved or nid in seen:
                counter += 1
                nid = f"{issue.check_id}-{issue.slide}-{counter}"
        seen.add(nid)
        out.append(issue if nid == issue.id else issue.model_copy(update={"id": nid}))
    return out


def carry_report_ids(old, new):
    """`new` (an AuditReport) with the issue ids of `old` carried over (`carry_ids`) and its per-slide index rebuilt;
    returns `new`. `old` None leaves it as it is."""
    if old is None:
        return new
    new.issues = carry_ids(old.issues, new.issues)
    per: dict[int, list[str]] = {}
    for i in new.issues:
        per.setdefault(i.slide, []).append(i.id)
    new.per_slide = per
    return new


# ---------------------------------------------------------------------------- what the new version fixed


def match_fixed(requested: Sequence[Issue], after: Sequence[Issue], before: Optional[Sequence[Issue]] = None) -> tuple[list[str], list[dict]]:
    """Which requested remarks the new version fixed, and the remarks of the slide it still has.

    `before` is every stage remark the slide had (default: the requested ones), `after` the new report's stage remarks
    of the slide. They are paired by `pair_issues` (equal ids first: the new report's ids are carried over): a requested
    remark is fixed when nothing of the new report is it. Per check this is the count of REMARKS_SPEC §2.3 — `max(0,
    before − after)` remarks of the check are gone, and among alike ones the first in number order count as fixed — but
    a remark that is still there by its elements or its words is never called fixed. A remaining remark keeps the id
    it had (the one the person saw), and it is `new` when its check was not among the slide's remarks before."""
    before = list(before) if before is not None else list(requested)
    known = {i.id for i in before}
    before += [i for i in requested if i.id not in known]
    after = order_remarks([i for i in after if is_stage(i)])
    pairs = pair_issues(before, after, by_id=True)
    still = {before[b].id for b in pairs.values()}
    fixed = [i.id for i in order_remarks(requested) if i.id not in still]
    had = {i.check_id for i in before}
    remaining = [
        {"id": before[pairs[k]].id if k in pairs else i.id, "check_id": i.check_id, "severity": i.severity, "message": i.message, "new": i.check_id not in had}
        for k, i in enumerate(after)
    ]
    return fixed, remaining


def _remaining_phrase(remaining: Sequence[dict], titles: Optional[dict[str, str]] = None) -> str:
    fake = [Issue(id=r["id"], slide=1, check_id=r["check_id"], severity=r["severity"], kind="deterministic", message=r.get("message") or "") for r in remaining]
    return titles_phrase(fake, titles)


def check_line(
    fixed: Sequence[str], requested: Sequence, remaining: Sequence[dict], applied: bool, worse: bool,
    titles: Optional[dict[str, str]] = None, other: Sequence[int] = (),
) -> str:
    """The check step's line: «Проверка: замечаний на слайде не осталось, остальные слайды не изменились.» and the rest
    (when other slides changed too, the caller says so in a line of its own)."""
    if not applied:
        return "Проверка: новая версия хуже — оставляю слайд как был." if worse else "Проверка: замечания остались — оставляю слайд как был."
    if not remaining:
        return "Проверка: замечаний на слайде не осталось." if other else "Проверка: замечаний на слайде не осталось, остальные слайды не изменились."
    left = _remaining_phrase(remaining, titles)
    if requested:
        return f"Проверка: исправлено {len(fixed)} из {len(requested)}, осталось: {left}."
    return f"Проверка: слайд переделан, осталось: {left}."


def preview_line(fixed: Sequence[str], requested: Sequence, remaining: Sequence[dict]) -> str:
    """The check step's last line while the fixed slide's previews render (the fix is applied, the job still works):
    «Проверка: замечаний на слайде не осталось — готовлю превью слайда.»"""
    if not remaining:
        head = "замечаний на слайде не осталось"
    elif requested:
        head = f"исправлено {len(fixed)} из {len(requested)}"
    else:
        head = "слайд переделан"
    return f"Проверка: {head} — готовлю превью слайда."


def slides_phrase(slides: Sequence[int]) -> str:
    return ", ".join(str(s) for s in slides)


def score_phrase(before: Optional[float], after: Optional[float]) -> str:
    if before is None or after is None or round(before) == round(after):
        return ""
    return f"{round(before)} → {round(after)}"


def fix_reply(
    n: int,
    fixed: Sequence[str],
    requested: Sequence,
    remaining: Sequence[dict],
    before: Optional[float],
    after: Optional[float],
    notes: Sequence[str],
    applied: bool,
    why: Optional[str],
    other: Sequence[int],
    what: str = "",
    titles: Optional[dict[str, str]] = None,
) -> str:
    """The reply for the history and the chat (all Russian): what happened to the slide, the score, the notes, and the
    other slides when they changed too."""
    what = (what or "").strip().rstrip(".")
    if not applied:
        reason = lower_first((why or "замечания остались").strip().rstrip("."))
        text = f"Не получилось исправить слайд {n}: {reason}."
    elif not remaining:
        text = f"Слайд {n} исправлен: {what}. Замечаний на нём не осталось." if what else f"Слайд {n} исправлен — замечаний на нём не осталось."
    elif requested:
        text = f"Слайд {n}: исправлено {len(fixed)} из {len(requested)}, осталось: {_remaining_phrase(remaining, titles)}."
    else:
        text = (f"Слайд {n} исправлен: {what}." if what else f"Слайд {n} переделан.") + f" Осталось: {_remaining_phrase(remaining, titles)}."
    score = score_phrase(before, after) if applied else ""
    if score:
        text += f" Оценка {score}."
    for note in notes:
        if note and note.strip():
            text += " " + _sentence(_upper_first(note.strip()))
    if other:
        text += f" Изменились и слайды {slides_phrase(other)}."
    return text
