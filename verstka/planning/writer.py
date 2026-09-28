"""Writer mode: Verstka writes the deck's source text from a topic when the user gave no material of their own.

«презентация про вторую мировую войну», 10 slides → the writer writes a 10-slide text (facts, dates, a timeline, a
chart's data when the topic has comparable figures), neutral and encyclopedic, and that text then goes through the
planning agent exactly as a user's brief would (analyst → designer → critic → compiler → grounding): every figure on
the slides comes from the written text. A text WITH material (slide specs, tables, lists, figures, more than a few
sentences) is the faithful mode and is never touched here.

Flow (WRITER_SPEC.md §3): writer_mode (deterministic) → topic_reference (a tiny call: the Wikipedia article titles and
the topic's kind) → reference.fetch_reference (≤ 2 pages, cached) → deck_writer (one call, a continuation when the
answer is cut or short) → normalise → verify_against the full article (figures and names, no model) → writer_check
(deletion-only) → guard_politician → render_text → the new Brief.

Mirror of the mode's rules on the create screen: web/src/lib/writerMode.ts (keep the two in step)."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional

import yaml

from verstka.planning import heuristics as H
from verstka.schemas.outline import Brief
from verstka.schemas.writer import ReferenceAnswer, WriterAnswer, WriterCheckAnswer

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ budget (seconds; measured, WRITER_SPEC §1, §3.3)
AGENT_RESERVE_S = 110.0  # the writer phase never runs past budget_end − this (designer, critic, revise)
WRITER_MAX_S = 100.0  # the writer phase's own cap
WRITER_MIN_S = 30.0  # less writer time than this: no writer (the skeleton, as before)
REFERENCE_MAX_S = 12.0  # titles call + the article requests
TITLES_MAX_S = 8.0
CONTINUE_MIN_S = 35.0  # a continuation call starts only with this much writer time left
CHECK_MIN_LEFT_S = 120.0  # the check runs only when this much of the whole budget remains
CHECK_MAX_S = 25.0
DEFAULT_SLIDES = 10
POLITICIAN_MAX_CONTENT = 9
SKILLS = ("topic_reference", "deck_writer", "writer_check")

EventFn = Callable[[dict], None]

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "temperature": 0.3,
    "reference": {"enabled": True, "source": "wikipedia", "contact": "", "max_chars": 12000, "timeout_s": 6, "cache_days": 7},
    "check": {"enabled": True},
    "limits": {"writer_max_s": WRITER_MAX_S, "agent_reserve_s": AGENT_RESERVE_S, "check_min_left_s": CHECK_MIN_LEFT_S},
}


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "writer.yaml"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_flag(name: str) -> Optional[bool]:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return None
    return v.strip().lower() not in ("0", "false", "no", "off")


def load_config(path: Optional[Path | str] = None) -> dict:
    """configs/writer.yaml over the defaults; env VERSTKA_WRITER=0 switches writer mode off, VERSTKA_WIKI=0 the
    Wikipedia reference (the writer then writes from the model's knowledge), VERSTKA_WIKI_CONTACT sets the contact of
    the User-Agent."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    p = Path(path) if path else default_config_path()
    try:
        if p.is_file():
            cfg = _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError) as e:
        log.warning("configs/writer.yaml not read (%s): the defaults are used", e)
    on = _env_flag("VERSTKA_WRITER")
    if on is not None:
        cfg["enabled"] = on
    wiki = _env_flag("VERSTKA_WIKI")
    if wiki is not None:
        cfg["reference"]["enabled"] = wiki
    contact = os.environ.get("VERSTKA_WIKI_CONTACT")
    if contact:
        cfg["reference"]["contact"] = contact.strip()
    return cfg


# ------------------------------------------------------------------ when writer mode starts (§2)

_YEAR_RE = re.compile(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?:\s*[-–—]\s*(?:1\d{3}|20\d{2}))?(?:\s*(?:год\w*|гг?\.?))?(?![\d.,])")
_COUNT_RE = re.compile(r"(?:(?:на|из|ровно|не\s+более|не\s+больше|максимум|до|в)\s+)?\d{1,2}\s+слайд\w*", re.I)
_LIST_RE = re.compile(r"^\s*(?:[—–\-•*]\s+|\d{1,2}[.)]\s+)")
NO_WRITE_RE = re.compile(r"не\s+(?:добавляй|придумывай|дописывай|выдумывай)|только\s+(?:по|из)\s+(?:моему\s+|этому\s+)?текст", re.I)
PRIVATE_RE = re.compile(r"(?<![\wё])(?:наш\w{0,3}|мо[йяеёи]\w{0,3}|мы|нас|нам|our|my|we)(?![\wё])", re.I)
MAX_FIGURES = 2
MAX_SENTENCES = 5
MAX_WORDS = 69


@dataclass
class WriterMode:
    kind: Literal["off", "topic", "expand"]
    topic: str = ""
    theses: list[str] = field(default_factory=list)
    private_hint: bool = False
    language: str = "ru"
    reason: str = ""


def writer_mode(brief: Brief | str) -> WriterMode:
    """Whether a brief is a topic the writer writes («topic»; «expand» with the user's few statements kept word for
    word) or a text with material of its own («off»: the faithful mode). Deterministic, no model."""
    from verstka.planning.brief_structure import _front_matter, _is_rule, numbers_of, read_structure, sentences_of

    text = brief.text if isinstance(brief, Brief) else str(brief or "")
    _, body = _front_matter(text or "")
    body = body.strip()
    language = "ru" if re.search(r"[А-Яа-яЁё]", body) else "en"
    private = bool(PRIVATE_RE.search(body))
    if not body:
        return WriterMode("off", reason="empty", language=language)
    if NO_WRITE_RE.search(body):
        return WriterMode("off", topic=body, reason="no_write", language=language, private_hint=private)
    try:
        specs = len(read_structure(body).specs)
    except Exception:  # noqa: BLE001 - an analyst failure: the faithful mode, as before
        return WriterMode("off", topic=body, reason="analyst", language=language)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    table_lines = sum(1 for ln in lines if ln.strip().startswith("|"))
    list_lines = sum(1 for ln in lines if _LIST_RE.match(ln))
    if specs >= 2:
        return WriterMode("off", topic=body, reason="specs", language=language, private_hint=private)
    if table_lines >= 2:
        return WriterMode("off", topic=body, reason="table", language=language, private_hint=private)
    if list_lines >= 3:
        return WriterMode("off", topic=body, reason="list", language=language, private_hint=private)
    sents = [s for s in sentences_of(body) if not _is_rule(s)]
    content = " ".join(sents)
    figs = numbers_of(_COUNT_RE.sub(" ", _YEAR_RE.sub(" ", content)))
    words = len(re.findall(r"[\wё]+", content))
    if len(figs) > MAX_FIGURES:
        return WriterMode("off", topic=body, reason=f"figures:{len(figs)}", language=language, private_hint=private)
    if len(sents) > MAX_SENTENCES:
        return WriterMode("off", topic=body, reason=f"sentences:{len(sents)}", language=language, private_hint=private)
    if words > MAX_WORDS:
        return WriterMode("off", topic=body, reason=f"words:{words}", language=language, private_hint=private)
    theses = [H.strip_end(s) + "." if not s.rstrip().endswith((".", "!", "?", "…")) else s.strip() for s in sents[1:]]
    kind: Literal["topic", "expand"] = "expand" if theses else "topic"
    return WriterMode(kind, topic=" ".join(body.split()), theses=theses, private_hint=private, language=language, reason=kind)


# ------------------------------------------------------------------ storylines (§5.7)

# «!» always kept, «*» the timeline slide, «†» the data slide, «+» a part repeated «(продолжение)» for a long deck
STORYLINES: dict[str, list[str]] = {
    "history": ["Предпосылки и причины!", "Начало!", "Ход событий+", "Ход событий (продолжение)", "Переломные события+", "Участники", "Окончание!", "Итоги и последствия!", "Хронология*!", "В цифрах†", "Главное!"],
    "conflict": ["Предпосылки и причины!", "Начало!", "Ход событий+", "Участники", "Окончание!", "Итоги и последствия!", "Хронология*!", "Главное!"],
    "person": ["Ранние годы и образование!", "Начало пути!", "Основные этапы+", "Главные работы или должности+", "Признание", "Поздние годы", "Хронология*!", "Главное!"],
    "politician": ["Ранние годы!", "Образование!", "Начало карьеры!", "Переход на государственную службу", "Первые должности", "Избрание", "Последующие сроки и должности!", "Хронология*!", "Главное!"],
    "company": ["Основание!", "Первые годы!", "Развитие+", "Продукты и сервисы!+", "Аудитория в цифрах†", "Структура и управление", "Партнёры и рынки", "Современный этап!", "Хронология*!", "Главное!"],
    "market": ["Что это за рынок!", "Объём рынка в цифрах†!", "Основные игроки!+", "Продукты и цены", "Инфраструктура", "Регулирование и поддержка", "Тенденции!+", "Главное!"],
    "science": ["Что это!", "Как устроено!", "Как это работает!+", "Этапы процесса", "Где встречается или применяется+", "История открытия", "Значение!", "Главное!"],
    "place": ["Где находится!", "История!+", "Население в цифрах†", "Экономика", "Культура и достопримечательности!+", "Главное!"],
    "culture": ["Что это!", "История!", "Особенности!+", "Известные примеры+", "Влияние", "Главное!"],
    "howto": ["Зачем это нужно!", "Основные принципы!", "Шаг 1!", "Шаг 2", "Шаг 3+", "Типичные ошибки!", "Инструменты", "Главное!"],
    "other": ["Что это!", "Контекст!", "Основные аспекты!+", "Примеры+", "Значение", "Главное!"],
}
STORYLINES["technology"] = STORYLINES["science"]
KINDS = tuple(STORYLINES) + ("private",)
_WORKING_TITLES = {raw.rstrip("!*†+").lower() for parts in STORYLINES.values() for raw in parts} | {"в цифрах", "цифры", "данные"}


@dataclass
class _Part:
    title: str
    must: bool = False
    timeline: bool = False
    data: bool = False
    repeat: bool = False
    pos: float = 0.0
    hint: str = ""  # what the slide tells, for the writer («the turning points the reference names…»)

    @property
    def line(self) -> str:
        return self.title + (" (timeline)" if self.timeline else " (data)" if self.data else "") + (f" — {self.hint}" if self.hint else "")


# a history of ≤ 10 slides is a story, not a list of sections (gate 2: «Итоги + Хронология + В цифрах + Главное» told the
# same 62 государства / 80 % / 70 млн three times and left out Сталинград and Курск): causes → start → course with its
# turning points → end → outcome and losses → consequences; no separate chronology, no «В цифрах», no «Главное»
_H_CAUSES = ("Предпосылки и причины", "the causes and the situation before it, with their dates")
_H_START = ("Начало", "how it started: the first events with their exact dates")
_H_COURSE = ("Ход событий", "the main events of the first stage, in time order, each with its date")
_H_COURSE2 = ("Ход событий (продолжение)", "the next stage, in time order, each event with its date")
_H_TURN = ("Переломные события", "the turning points the reference names (battles, operations, landings, treaties), each with its date and its outcome")
_H_TURN2 = ("Переломные события (продолжение)", "the later turning points the reference names, each with its date and its outcome")
_H_END = ("Окончание", "how it ended: the last events and the exact dates of the end")
_H_OUTCOME = ("Итоги и потери", "the outcome and the losses in figures the reference gives")
_H_AFTER = ("Последствия", "what changed after it: states, borders, organisations founded, with dates")
_H_OUT_AFTER = ("Итоги и последствия", "the outcome, the losses in figures and what changed after it")
_H_COURSE_TURN = ("Ход событий и переломные события", "the main events and the turning points the reference names, each with its date")
HISTORY_SHORT: dict[int, list[tuple[str, str]]] = {
    1: [_H_OUT_AFTER],
    2: [_H_COURSE_TURN, _H_OUT_AFTER],
    3: [_H_CAUSES, _H_COURSE_TURN, _H_OUT_AFTER],
    4: [_H_CAUSES, _H_COURSE_TURN, _H_END, _H_OUT_AFTER],
    5: [_H_CAUSES, _H_START, _H_COURSE_TURN, _H_END, _H_OUT_AFTER],
    6: [_H_CAUSES, _H_START, _H_COURSE, _H_TURN, _H_END, _H_OUT_AFTER],
    7: [_H_CAUSES, _H_START, _H_COURSE, _H_TURN, _H_END, _H_OUTCOME, _H_AFTER],
    8: [_H_CAUSES, _H_START, _H_COURSE, _H_COURSE2, _H_TURN, _H_END, _H_OUTCOME, _H_AFTER],
    9: [_H_CAUSES, _H_START, _H_COURSE, _H_COURSE2, _H_TURN, _H_TURN2, _H_END, _H_OUTCOME, _H_AFTER],
}
SHORT_DECK_CONTENT = 9  # ≤ 10 slides with the cover: no separate chronology slide (the narrative slides carry the dates)


def _parts(kind: str) -> list[_Part]:
    out = []
    for i, raw in enumerate(STORYLINES.get(kind) or STORYLINES["other"]):
        t = raw.rstrip("!*†+")
        marks = raw[len(t):]
        out.append(_Part(t, must="!" in marks, timeline="*" in marks, data="†" in marks, repeat="+" in marks, pos=float(i)))
    return out


def storyline_parts(kind: str, n: int, reference: bool = False) -> list[_Part]:
    """The working titles of `n` content slides for a topic of `kind`, in the story's order: the «!» parts, then the
    data part (when kept: with a reference, or for a market or a company), then the others in order; a long deck
    repeats the «+» parts with «(продолжение)» — never a generic filler (measured: «Ещё одна сторона темы» was filled
    with policy content); a short one keeps the first two parts, «Главное», the timeline and the data part first."""
    kind = kind if kind in STORYLINES else "other"
    if kind == "politician":
        n = min(n, POLITICIAN_MAX_CONTENT)
    n = max(1, n)
    if kind == "history" and n <= SHORT_DECK_CONTENT:
        return [_Part(t, must=True, pos=float(i), hint=h, data=t in ("Итоги и потери", "Итоги и последствия") and reference) for i, (t, h) in enumerate(HISTORY_SHORT[n])]
    # a deck of ≤ 10 slides has no separate chronology: its narrative slides carry the dates (a chronology repeated them)
    parts = [p for p in _parts(kind) if (not p.data or reference or kind in ("market", "company")) and not (p.timeline and n <= SHORT_DECK_CONTENT)]
    last = parts[-1]
    musts = [p for p in parts if p.must]
    rank: list[_Part] = []
    if len(musts) >= 1:
        rank.append(musts[0])
    rank.append(last)
    if len(musts) >= 2 and musts[1] is not last:
        rank.append(musts[1])
    rank += [p for p in parts if p.timeline and p not in rank]
    rank += [p for p in parts if p.data and p not in rank]
    rank += [p for p in musts if p not in rank]
    rank += [p for p in parts if p not in rank]
    chosen = rank[:n]
    extra = n - len(chosen)
    if extra > 0:
        pool = [p for p in parts if p.repeat] or [p for p in parts if p.must and p is not last][:2] or parts[:1]
        k = 0
        while extra > 0:
            base = pool[k % len(pool)]
            if re.match(r"^Шаг \d+$", base.title):
                same = [p for p in chosen if re.match(r"^Шаг \d+$", p.title)] or [base]
                title = f"Шаг {max(int(p.title.split()[1]) for p in same) + 1}"
            else:
                same = [p for p in chosen if p.title == base.title or p.title.startswith(base.title + " (продолжение")] or [base]
                taken = {p.title for p in chosen}
                rnd = len(same)
                title = f"{base.title} (продолжение)" if rnd <= 1 else f"{base.title} (продолжение {rnd})"
                while title in taken:
                    rnd += 1
                    title = f"{base.title} (продолжение {rnd})"
            chosen.append(_Part(title, pos=max(p.pos for p in same) + 0.001))
            k += 1
            extra -= 1
    chosen.sort(key=lambda p: p.pos)
    # «Главное» is always the last line
    chosen = [p for p in chosen if p is not last] + ([last] if last in chosen else [])
    return chosen


def storyline(kind: str, n: int, reference: bool = False) -> str:
    return "\n".join(f"{i}. {p.line}" for i, p in enumerate(storyline_parts(kind, n, reference), 1))


_KIND_GUESS = (
    (re.compile(r"истори|войн|революц|импери|восстани|битв|сражени", re.I), "history"),
    (re.compile(r"(?<![\wё])рын(?:ок|ка|ке|ку|ком)(?![\wё])", re.I), "market"),
    (re.compile(r"как\s+работает|что\s+такое|процесс|как\s+устроен", re.I), "science"),
    (re.compile(r"как\s+(?:сделать|научиться|начать|выбрать|подготовить)|пошагов|инструкци", re.I), "howto"),
)


def guess_kind(topic: str) -> str:
    """The topic's kind without a model (the reference is off): a few keywords, a name-like topic is a person."""
    for rx, kind in _KIND_GUESS:
        if rx.search(topic or ""):
            return kind
    from verstka.planning.reference import lead_free

    core = lead_free(topic)
    words = core.split()
    if 2 <= len(words) <= 3 and all(w[:1].isupper() for w in words):
        return "person"
    return "other"


# ------------------------------------------------------------------ parsing, salvage (§6.6)


def _string_field(text: str, name: str) -> str:
    m = re.search(rf'"{name}"\s*:\s*("(?:[^"\\]|\\.)*")', text)
    if not m:
        return ""
    try:
        return str(json.loads(m.group(1)))
    except ValueError:
        return ""


def salvage_slides(text: str) -> Optional[WriterAnswer]:
    """The complete slides of a cut or broken answer, in order (a slide object that never closes and everything after
    it are lost); title and subtitle from before «"slides"» when complete. None when not one slide is complete."""
    text = text or ""
    at = text.find('"slides"')
    if at < 0:
        return None
    br = text.find("[", at)
    if br < 0:
        return None
    dec = json.JSONDecoder()
    pos = br + 1
    slides: list[Any] = []
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            obj, end = dec.raw_decode(text, pos)
        except ValueError:
            break
        slides.append(obj)
        pos = end
    if not slides:
        return None
    head = text[:at]
    data = {"status": "ok", "kind": _string_field(head, "kind"), "title": _string_field(head, "title"), "subtitle": _string_field(head, "subtitle"), "slides": slides}
    try:
        return WriterAnswer.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


def parse_answer(text: str) -> tuple[Optional[WriterAnswer], bool]:
    """(the writer's answer, salvaged) — salvaged is True when the answer was cut or broken and only its complete
    slides were kept. (None, False) when there is no answer at all."""
    from verstka.providers.openai_compat import TruncatedJSON, extract_json

    try:
        data = extract_json(text or "", {"status", "slides", "title", "subtitle", "kind"})
        a = WriterAnswer.model_validate(data)
        if a.status != "ok" or a.slides:
            return a, False
    except (TruncatedJSON, ValueError):
        pass
    except Exception:  # noqa: BLE001 - a validation error: salvage what is there
        pass
    s = salvage_slides(text or "")
    return (s, True) if s is not None else (None, False)


# ------------------------------------------------------------------ the working text (sentences, timeline, data)


@dataclass
class _Slide:
    title: str
    sentences: list[str] = field(default_factory=list)
    timeline: Optional[list[dict]] = None
    data: Optional[dict] = None
    theses: set[str] = field(default_factory=set)
    working: str = ""  # the storyline's working title when the chart's caption replaced it («В цифрах»)
    part: int = -1  # the storyline part the slide was written for (its place in the answer): a refill goes back there

    @property
    def empty(self) -> bool:
        return not (self.sentences or self.timeline or self.data)


@dataclass
class _Deck:
    title: str = ""
    subtitle: str = ""
    kind: str = "other"
    slides: list[_Slide] = field(default_factory=list)


# a piece that ends with an abbreviation or an initial did not end its sentence: «…при Высшей школе КГБ СССР им.» +
# «Дзержинского.», «В.» + «В. Путин родился…», «в 1999 г.» + «…»
_ABBR_TAIL_RE = re.compile(
    r"(?:^|[\s(«])(?:им|ул|св|проф|акад|ген|пр|просп|пл|обл|оз|ст|см|т\.\s?е|т\.\s?д|т\.\s?п|г|гг|в|вв|н\.\s?э|[А-ЯЁA-Z])\.$"
)


def sentences_of(text: str) -> list[str]:
    """The sentences of a slide's text (heuristics' split, with the pieces an abbreviation cut glued back, and a piece
    of one word glued to the one before it: «…приобрела Дзен.» + «Новости.» is one sentence — alone, «Новости.» would
    be left over when the check removes the first part)."""
    parts = [x.strip() for x in (H.split_sentences(text or "") or ([text.strip()] if (text or "").strip() else []))]
    out: list[str] = []
    for p in parts:
        if out and (_ABBR_TAIL_RE.search(out[-1]) or len(p.split()) < 2):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


# a sentence that leans on the one before it: a pronoun or a demonstrative opens it («Это создало…», «Согласно
# договору, страна…»), or a personal pronoun is its subject within its first words («В 1941 году она вторглась…»)
_ANAPHOR_RE = re.compile(
    r"^(?:Это|Этот|Эта|Эти|Этим|Этого|Этому|Эту|Он|Она|Оно|Они|Его|Её|Ее|Их|Ему|Ей|Им|Там|Тогда|Страна|Такой|Такая|Такие|"
    r"После\s+этого|В\s+результате\s+этого|Согласно\s+(?:ему|ей|им|договору|документу|соглашению|пакту|плану|закону))(?![\wё])"
)
_PRONOUN_SUBJECT_RE = re.compile(r"^(?:[^\s,.;:]+\s+){1,4}?(?:он|она|оно|они)(?![\wё])|^(?:[^\s,.;:]+\s+)?(?:её|ее|его|их)\s+(?!числ)")


def anaphoric(sentence: str) -> bool:
    """The sentence leans on the one before it (a pronoun or a demonstrative opens it, or a personal pronoun is its
    subject): without that sentence it has no antecedent."""
    s = (sentence or "").strip()
    return bool(_ANAPHOR_RE.match(s) or _PRONOUN_SUBJECT_RE.match(s))


# a conjunction that ties a sentence to the one before it («Однако в других странах…»): without that one, it goes
_LEAD_CONJ_RE = re.compile(r"^(?:Однако|Но|При\s+этом|Тем\s+не\s+менее|Также|Кроме\s+того|Поэтому|Таким\s+образом|Вместе\s+с\s+тем|Зато|Впрочем)\s*,?\s+(?=\S)")


def unlinked(sentence: str) -> str:
    """The sentence without a conjunction that ties it to the one before it («Однако в других странах введены…» →
    «В других странах введены…»)."""
    m = _LEAD_CONJ_RE.match(sentence or "")
    return H.cap_first(sentence[m.end():]) if m else sentence


def _prune(s: "_Slide", why_of: Callable[[str], Optional[str]], removed: list[dict], where: "str | Callable[[str], str]") -> int:
    """The slide's sentences without those `why_of` names (the user's theses always stay) and — deletion only — every
    sentence right after a removed one that leans on it («Одной из причин стало недовольство… договора» removed →
    «Согласно договору, страна теряла…» and «Это создало напряжённость» go too). Returns how many were removed."""
    keep: list[str] = []
    gone = False
    n = 0
    for sn in s.sentences:
        why = None if sn in s.theses else why_of(sn)
        if why is None and gone and sn not in s.theses and anaphoric(sn):
            why = "no antecedent: the sentence before it was removed"
        if why:
            _removed(removed, where(sn) if callable(where) else where, sn, why)
            gone = True
            n += 1
        else:
            keep.append(unlinked(sn) if (gone or not keep) and sn not in s.theses else sn)
            gone = False
    s.sentences = keep
    return n


def _deck_of(a: WriterAnswer) -> _Deck:
    d = _Deck(title=a.title.strip(), subtitle=a.subtitle.strip(), kind=(a.kind or "other").lower())
    for k, s in enumerate(a.slides):
        d.slides.append(_Slide(
            title=s.title.strip(),
            sentences=sentences_of(s.text or ""),
            timeline=[e.model_dump() for e in s.timeline] if s.timeline else None,
            data=s.data.model_dump() if s.data else None,
            part=k,
        ))
    return d


def fmt_value(v: float) -> str:
    v = float(v)
    if v.is_integer():
        return str(int(v))
    return f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",")


_VOWELS = set("аеёиоуыэюяaeiouy")
_NO_VOWEL_WORDS = frozenset({"млрд", "трлн", "квтч", "мвтч", "гвтч", "твтч", "мвт", "гвт", "квт", "тыс", "млн", "вв", "гг", "кпд"})
_FILLER_RE = re.compile(
    r"играет\s+важную\s+роль|имеет\s+(?:большое|огромное)\s+значение|стоит\s+отметить|оставил\w*\s+(?:глубокий\s+)?след|"
    r"показал\w*\s+необходимость|является\s+важн|^вот\s|^ниже\s|^далее\s|^рассмотрим|"
    r"произошл\w*\s+(?:много|множество)\s+(?:ключевых\s+|важных\s+)?событий|множество\s+(?:ключевых|важных)\s+событий",
    re.I,
)
_LATIN_RE = re.compile(r"[A-Za-z]{3,}")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_MARKER_RE = re.compile(r"\s*\((?:timeline|data)[^)]*\)\s*$", re.I)
# the last slide that sums up the deck («Главное», «Ключевые факты»; «Итоги и последствия» is a content slide)
SUMMARY_TITLE_RE = re.compile(r"^(?:главн|ключев\w*\s+(?:факт|дат|итог)|основн\w*\s+факт|кратк|заключ|резюм|коротко)", re.I)
_SLIDE_PREFIX_RE = re.compile(r"^\s*(?:слайд|slide)\s*\d{1,2}\s*[.:—–-]?\s*", re.I)


def _latin_junk(text: str, known: str, strict: bool, min_len: int = 3) -> Optional[str]:
    """A Latin word the topic and the reference never write: any (with a reference) or a lowercase / camelCase one
    (without: a capitalised name like «Tesla» is the model's knowledge, «elementGuidId» or «ll» is junk)."""
    low = known.lower()
    for w in re.findall(rf"[A-Za-z]{{{min_len},}}", text):
        if w.lower() in low:
            continue
        proper = w[:1].isupper() and (w[1:].islower() or w.isupper())
        if strict or not proper:
            return w
    return None


def junk_sentence(sentence: str, known: str, language: str = "ru", strict: bool = True) -> Optional[str]:
    """Why a sentence is junk the model emitted («…в elementGuidId», «.ll», an English sentence in a Russian text), or
    None. `known`: the topic and the reference (a Latin word written there is a name, not junk); `strict` (a
    reference is given): every unknown Latin word is junk, else only a lowercase or camelCase one."""
    w = _latin_junk(sentence, known, strict, 3)
    if w:
        return f"latin word «{w}»"
    for w in _WORD_RE.findall(sentence):
        if w.lower() in _NO_VOWEL_WORDS:
            continue  # «87,6 млрд рублей», «трлн», «кВтч»: abbreviations a text writes without a vowel
        if len(w) >= 4 and not w.isupper() and not (set(w.lower()) & _VOWELS):
            return f"no vowel «{w}»"
    if language == "ru":
        # a Russian sentence may name several brands («Сервисы VK были удалены из App Store и Google Play»): the Latin
        # names the topic or the reference write are names, not English
        low = known.lower()
        cyr = len(re.findall(r"[А-Яа-яЁё]+", sentence))
        lat = len([w for w in re.findall(r"[A-Za-z]{2,}", sentence) if not (w[:1].isupper() and w.lower() in low)])
        if cyr == 0 or lat > cyr:
            return "not Russian"
    return None


def filler_sentence(sentence: str) -> bool:
    return bool(_FILLER_RE.search(sentence.strip()))


# an evaluation, not a fact («Электромобили в России — быстро развивающийся рынок», «значительный рост»): a sentence
# with no figure and no date that says it goes, unless the reference itself uses the word («стремительное завоевание»)
_OPINION_RE = re.compile(
    r"(?<![\wё])(быстро\s+развива\w*|стремительн\w*|значительн\w*|выдающ\w*|успешн\w*|к\s+сожалению|беспрецедентн\w*|"
    r"грандиозн\w*|впечатляющ\w*|блестящ\w*|героическ\w*|трагическ\w*|славн\w*)(?![\wё])",
    re.I,
)


def opinion_word(text: str, known: str = "") -> Optional[str]:
    """The first evaluative word of a text («значительный», «стремительный») that `known` (the source) never uses."""
    low = (known or "").lower()
    for m in _OPINION_RE.finditer(text or ""):
        stem_ = m.group(1).lower().split()[0][:7]
        if not low or stem_ not in low:
            return m.group(1)
    return None


def opinion_sentence(sentence: str, known: str = "") -> Optional[str]:
    """The evaluative word of a sentence that states no figure and no date, when the reference (`known`) never uses its
    stem; None for a sentence of facts."""
    from verstka.planning.grounding import figures

    if figures(sentence) or re.search(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", sentence):
        return None
    low = (known or "").lower()
    for m in _OPINION_RE.finditer(sentence):
        stem_ = m.group(1).lower().split()[0][:7]
        if not low or stem_ not in low:
            return m.group(1)
    return None


# governance errors the model makes (gate 2: «Войну участвовали 62 страны»): the case a verb needs
_GRAMMAR_FIXES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^(?:Войну|Войне|Войны)\s+(участвовал\w*)", re.I), r"В войне \1"),
    (re.compile(r"^(?:Битву|Битве|Битвы)\s+(участвовал\w*)", re.I), r"В битве \1"),
    (re.compile(r"^(?:Сражение|Сражению)\s+(участвовал\w*)", re.I), r"В сражении \1"),
    (re.compile(r"^(?:Операцию|Операции)\s+(участвовал\w*)", re.I), r"В операции \1"),
    (re.compile(r"^(?:Конфликт|Конфликту)\s+(участвовал\w*)", re.I), r"В конфликте \1"),
    (re.compile(r"(?<![\wё])(участвовал\w*)\s+(?:войну|войне)(?![\wё])", re.I), r"\1 в войне"),
    (re.compile(r"(?<![\wё])(?:в|во)\s+(?:войну)\s+(участвовал\w*)", re.I), r"в войне \1"),
)


_INCLUDING_RE = re.compile(r",?\s+(?:включая|в\s+том\s+числе)\s+([^,.;]*?\d[^,.;]*)(?=[,.;]|$)")


def fix_including(sentence: str) -> str:
    """A «part» larger than its whole is not a part: «В войне участвовали 62 государства, включая 110 млн мобилизованных
    солдат» → «В войне участвовали 62 государства» (the clause joined two measures)."""
    from verstka.planning.grounding import figures

    m = _INCLUDING_RE.search(sentence or "")
    if not m:
        return sentence
    head = [f for f in figures(sentence[: m.start()]) if f.date is None]
    part = [f for f in figures(m.group(1)) if f.date is None]
    if not head or not part:
        return sentence
    if part[0].mag > head[-1].mag and (part[0].unit or "") != (head[-1].unit or "") or part[0].mag > head[-1].mag * 1.0001 and not head[-1].unit:
        if "%" in m.group(1):
            # a share of something else, as the article writes it: «62 государства (80 % населения Земного шара)»
            out = sentence[: m.start()] + f" ({m.group(1).strip()})" + sentence[m.end():]
        else:
            out = sentence[: m.start()] + sentence[m.end():]
        return _sentence(re.sub(r"\s+([,.;])", r"\1", " ".join(out.split())))
    return sentence


def fix_grammar(sentence: str) -> str:
    """The sentence with the model's known governance errors fixed («Войну участвовали 62 страны» → «В войне
    участвовали 62 страны») and a «part» larger than its whole cut (fix_including)."""
    out = sentence
    for rx, rep in _GRAMMAR_FIXES:
        out = rx.sub(rep, out)
    return fix_including(out)


def _clean_title(t: str) -> str:
    t = _MARKER_RE.sub("", _SLIDE_PREFIX_RE.sub("", " ".join((t or "").split()))).strip().strip("«»\"").strip()
    t = H.strip_end(t)
    words = t.split()
    return " ".join(words[:8]) if len(words) > 8 else t


MAX_TIMELINE = 6  # the prompt's 4–6 entries: a longer timeline does not read on one slide


def _spread(items: list, n: int) -> list:
    """At most `n` of the items, the first and the last kept and the others evenly spaced between them."""
    if len(items) <= n:
        return items
    if n <= 1:
        return items[:n]
    idx = sorted({round(k * (len(items) - 1) / (n - 1)) for k in range(n)})
    return [items[k] for k in idx]


_MONTH_WORD_RE = re.compile(
    r"(?<![\wё])(январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)(?![\wё])", re.I,
)
_MONTH_STEMS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
_PART_OF_YEAR = (("зим", 1), ("весн", 3), ("лет", 6), ("осен", 9), ("начал", 1), ("середин", 6), ("конц", 12), ("конец", 12))


def _is_month_stem(x: str) -> bool:
    """A word's stem is a month's («сентя», «мая»)."""
    return bool(re.fullmatch(r"ма[йяе]", x)) or any(x.startswith(st[:5]) or st.startswith(x) and len(x) >= 4 for st in _MONTH_STEMS if st != "ма")


def _month_of(word: str) -> int:
    w = word.lower()
    if re.fullmatch(r"ма[йяе]", w):
        return 5
    return next((k for k, st in enumerate(_MONTH_STEMS, 1) if st != "ма" and w.startswith(st)), 0)


def date_start(text: str) -> Optional[tuple[int, int, int]]:
    """(year, month, day) of where a dated title starts — «22 июня 1941» (1941, 6, 22), «Апрель — июнь 1940» (1940, 4,
    0), «1931–1937» (1931, 0, 0), «20.02.2026», «Весна 1945» (1945, 3, 0); None without a year."""
    t = " ".join(str(text or "").split())
    m = re.search(r"(?<![\d.,])(\d{1,2})\.(\d{1,2})\.(1\d{3}|20\d{2})(?!\d)", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(3)), int(m.group(2)), int(m.group(1))
    m = re.search(r"(?<![\d.,])(1\d{3}|20\d{2})(?![\d.,])", t)
    if not m:
        return None
    year, head = int(m.group(1)), t[: m.start()]
    mm = _MONTH_WORD_RE.search(head)
    if mm:
        dm = re.search(r"(?<![\d.,])(\d{1,2})\s*$", head[: mm.start()])
        day = int(dm.group(1)) if dm and 1 <= int(dm.group(1)) <= 31 else 0
        return year, _month_of(mm.group(1)), day
    low = head.lower()
    part = next((mo for st, mo in _PART_OF_YEAR if re.search(rf"(?<![\wё]){st}", low)), 0)
    return year, part, 0


def chrono_sort(items: list, when: Callable[[Any], str], share: float = 0.8) -> list:
    """The items in time order when at least `share` of their dates parse (date_start), stably (an item without a date
    keeps its place after the item before it); else as they are — «22 июня 1941 → 1931–1937 → Июль 1937 → 7 декабря
    1941» of a slide told in the narrative's order becomes «1931–1937 → Июль 1937 → 22 июня 1941 → 7 декабря 1941»."""
    if len(items) < 2:
        return items
    keys = [date_start(when(x)) for x in items]
    if sum(k is not None for k in keys) < share * len(items):
        return items
    filled: list[tuple[int, int, int]] = []
    prev = next(k for k in keys if k is not None)
    for k in keys:
        prev = k if k is not None else prev
        filled.append(prev)
    order = sorted(range(len(items)), key=lambda i: (filled[i], i))
    return [items[i] for i in order]


def _working_title(title: str) -> bool:
    """The slide kept a working title of the storyline («В цифрах», «Главное», «Ход событий (продолжение)»)."""
    t = re.sub(r"\s*\(продолжение(?:\s+\d+)?\)\s*$", "", (title or "").strip(), flags=re.I).lower()
    return not t or t in _WORKING_TITLES


def _removed(log_: list[dict], where: str, text: str, why: str) -> None:
    log_.append({"where": where, "text": text, "why": why})


def _data_ok(d: Optional[dict]) -> Optional[dict]:
    """A chart's data kept when it is one measure over ≥ 3 labels of one kind; a line over years in order, a pie of
    parts of a whole (≈ 100 %), else a column chart."""
    if not d:
        return None
    rows = []
    seen: set[str] = set()
    for r in d.get("rows") or []:
        label = " ".join(str(r.get("label") or "").split())
        v = r.get("value")
        if not label or not isinstance(v, (int, float)) or label.lower() in seen:
            continue
        seen.add(label.lower())
        rows.append({"label": label, "value": float(v)})
    if len(rows) < 3:
        return None
    years = [bool(re.fullmatch(r"\d{4}", r["label"])) for r in rows]
    if any(years) and not all(years):
        return None  # years mixed with other labels: not one measure over one kind of label
    chart = d.get("chart") or "column"
    if chart == "line" and not (all(years) and [int(r["label"]) for r in rows] == sorted(int(r["label"]) for r in rows)):
        chart = "column"
    if chart == "pie" and abs(sum(r["value"] for r in rows) - 100.0) > 5.0:
        chart = "column"
    if chart in ("column", "bar") and not any(years):
        rows.sort(key=lambda r: -r["value"])  # items compared: the largest first (years keep their order)
    return {"caption": " ".join(str(d.get("caption") or "").split()), "unit": " ".join(str(d.get("unit") or "").split()), "chart": chart if chart in ("column", "bar", "line", "pie") else "column", "rows": rows[:6]}


def normalise_answer(a: WriterAnswer | _Deck, topic: str, reference: str = "", theses: Optional[list[str]] = None, language: str = "ru", removed: Optional[list[dict]] = None, first: int = 1) -> _Deck:
    """The answer cleaned deterministically (§6.1): titles, junk and filler sentences, duplicates across slides,
    timelines (dated entries, ≥ 3, the two longest), data (one measure, ≥ 3 rows, the first two), and — expand mode —
    every thesis of the user present word for word. `first`: the number of the answer's first slide in the deck."""
    deck = a if isinstance(a, _Deck) else _deck_of(a)
    removed = removed if removed is not None else []
    known = f"{topic}\n{reference}"
    strict = bool(reference.strip())
    from verstka.planning.agent import same_text

    kept_sentences: list[str] = []
    for i, s in enumerate(deck.slides, first):
        s.title = _clean_title(s.title)
        # the summing-up slide restates the deck's key facts by design: only its own repeats go
        earlier = [] if SUMMARY_TITLE_RE.match(s.title or "") else kept_sentences
        s.sentences = [x if x in s.theses else fix_grammar(x) for x in s.sentences]
        seen: list[str] = [x for x in s.sentences if x in s.theses]

        def why_of(sn: str, earlier: list[str] = earlier, seen: list[str] = seen) -> Optional[str]:
            why = junk_sentence(sn, known, language, strict)
            if why:
                return f"junk: {why}"
            if filler_sentence(sn):
                return "filler"
            word = opinion_sentence(sn, reference)
            if word:
                return f"opinion: «{word}»"
            if any(same_text(sn, x) for x in earlier + seen):
                return "duplicate"
            seen.append(sn)
            return None

        _prune(s, why_of, removed, f"{i}")
        kept_sentences.extend(s.sentences)
        if s.timeline:
            tl = []
            for e in s.timeline:
                when, what = " ".join(str(e.get("when") or "").split()), " ".join(str(e.get("what") or "").split())
                if not when or not what or not re.search(r"\d", when):
                    continue
                if _latin_junk(what, known, strict, 2):
                    _removed(removed, f"{i}", f"{when} — {what}", "junk timeline entry")
                    continue
                tl.append({"when": H.strip_end(when), "what": H.strip_end(what)})
            tl = chrono_sort(tl, lambda e: e["when"])
            s.timeline = _spread(tl, MAX_TIMELINE) if len(tl) >= 3 else None
        s.data = _data_ok(s.data)
        if s.data and s.data.get("caption") and _working_title(s.title):
            # «В цифрах» is the storyline's working title: the chart's caption says what the slide shows
            s.working, s.title = s.title, _clean_title(H.cap_first(s.data["caption"]))
    tls = sorted((s for s in deck.slides if s.timeline), key=lambda s: -len(s.timeline or []))
    for s in tls[2:]:
        s.timeline = None
    for s in [s for s in deck.slides if s.data][2:]:
        s.data = None
    deck.slides = [s for s in deck.slides if not s.empty or s.theses]
    for t in theses or []:
        _place_thesis(deck, t)
    return deck


def _place_thesis(deck: _Deck, thesis: str) -> None:
    from verstka.planning.agent import said_in
    from verstka.planning.grounding import content_stems

    for s in deck.slides:
        if said_in(thesis, " ".join(s.sentences), 0.9):
            for sn in s.sentences:
                if said_in(thesis, sn, 0.9) or said_in(sn, thesis, 0.9):
                    s.theses.add(sn)
            return
    if not deck.slides:
        deck.slides.append(_Slide(title="", sentences=[thesis], theses={thesis}))
        return
    mine = set(content_stems(thesis, neutral=True))
    best = max(range(len(deck.slides)), key=lambda k: (len(mine & set(content_stems(" ".join([deck.slides[k].title] + deck.slides[k].sentences), neutral=True))), -k))
    if not mine & set(content_stems(" ".join([deck.slides[best].title] + deck.slides[best].sentences), neutral=True)):
        best = 0
    deck.slides[best].sentences.insert(0, thesis)
    deck.slides[best].theses.add(thesis)


# ------------------------------------------------------------------ verification against the reference (§6.2)

_PROPER_RE = re.compile(r"(?<![«(„\"])(?<=\s)([A-ZА-ЯЁ][a-zа-яё]{2,}|[A-ZА-ЯЁ]{2,})")


def _article_stems(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", t):
            out.add(w.lower()[:4])
    return out


def unknown_names(sentence: str, stems: set[str]) -> list[str]:
    """The proper nouns of a sentence (capitalised, not sentence-initial, not after «(» or «; all-caps abbreviations)
    whose 4-letter stem the articles never have."""
    return [w for w in _PROPER_RE.findall(sentence.strip()) if w.lower()[:4] not in stems]


_DATING_PREV_RE = re.compile(
    r"(?:^|\s)(?:в|во|с|со|до|к|ко|от|по|около|после|между|на|за|из|перед|через|начала|конца|середины|середине|году|года|"
    r"январ\w*|феврал\w*|март\w*|апрел\w*|ма[яе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|\d+)\s*$",
    re.I,
)
_THING_RE = re.compile(
    r"договор|пакт|соглашени|конференци|конгресс|съезд|саммит|конституци|закон|кодекс|выбор|олимпиад|чемпионат|кризис|"
    r"революци|реформ|восстани|переворот|указ|декрет|манифест|плана?\b|программ|войн",
    re.I,
)


def _caption_gone(s: _Slide) -> None:
    """The chart the slide was titled after is gone (its rows were not the article's): the slide takes its working title
    back («Потери по странам» over the war's total figures would promise the chart)."""
    if s.data is None and s.working:
        s.title, s.working = s.working, ""


def _cut_dating_years(sentence: str, bad: list[Any]) -> str:
    """The sentence without the years the article does not give that only date a named thing — «…условиями Версальского
    договора 1919 года» → «…условиями Версальского договора»: a genitive year («1919 года», «1919 г.») or a year in
    brackets right after a noun that names a thing (a capitalised name within the three words before it, or «договор»,
    «конференция», «кризис»…), never an event's date («в 1919 году», «1 сентября 1919 года»). The sentence as it is when
    a bad figure is not such a year."""
    from verstka.planning.grounding import _is_year

    out = sentence
    for f in sorted(bad, key=lambda f: -f.start):
        span = sentence[f.start:f.uend]
        if not _is_year(f):
            return sentence
        whole = re.match(r"^\(?\s*(?:1\d{3}|20\d{2})\s*(?:года|г\.?)?\s*\)?$", span.strip())
        start, end = f.start, f.uend
        if start > 0 and sentence[start - 1] == "(" and end < len(sentence) and sentence[end:end + 1] == ")":
            start, end = start - 1, end + 1  # «договора (1919)»
        elif not re.match(r"^(?:1\d{3}|20\d{2})\s*(?:года|г\.)$", span.strip()):
            return sentence  # «в 1919 году», «1919» alone: an event's date, not a thing's
        if not whole:
            return sentence
        before = sentence[:start]
        if _DATING_PREV_RE.search(before) or not re.search(r"[А-Яа-яЁёA-Za-z]{3,}\s*$", before):
            return sentence
        all_words = before.split()
        words = all_words[-3:]
        caps = words[1:] if len(all_words) <= 3 else words  # the sentence's first word is capitalised anyway
        named = any(w.strip("«»\"(")[:1].isupper() for w in caps) or bool(_THING_RE.search(" ".join(words[-2:])))
        if not named:
            return sentence
        out = out[:start].rstrip() + out[end:]
    out = re.sub(r"\s+([,.;:!?)])", r"\1", " ".join(out.split()))
    return out if len(out.split()) >= 4 else sentence


def verify_against(
    deck: _Deck, full_texts: list[str], topic: str, removed: Optional[list[dict]] = None, first: int = 1, edits: Optional[list[dict]] = None,
    support: Optional["ArticleSupport"] = None,
) -> _Deck:
    """With a reference: a sentence goes when one of its figures (dates and years included) is not in the articles
    (value level: grounding's verdict «bad»), or when it names ≥ 2 people / places / organisations the articles never
    mention; a timeline entry and a data row go when their figure is not there. A year that only dates a named thing
    («договора 1919 года») is cut out and its sentence stays (`edits`); a sentence that leans on a removed one goes
    with it. Deletion only; the user's theses stay."""
    from verstka.planning.grounding import BriefIndex, figures, unit_scale, value_ok

    removed = removed if removed is not None else []
    if not full_texts:
        return deck
    idx = BriefIndex("\n\n".join(full_texts) + "\n" + topic)
    stems = _article_stems(full_texts + [topic])
    support = support or ArticleSupport(full_texts, topic)

    def bad_figs(text: str) -> list[Any]:
        out = []
        for f in figures(text):
            try:
                if idx.verdict(f) == "bad":
                    out.append(f)
            except Exception:  # noqa: BLE001 - a figure the index cannot judge is kept
                continue
        return out

    def bad_figures(text: str) -> list[str]:
        return [text[f.start:f.uend].strip() or str(f.value) for f in bad_figs(text)]

    for i, s in enumerate(deck.slides, first):
        # a year the article does not give that only dates a named thing («Версальского договора 1919 года») is cut
        # out of its sentence, which stays («…условиями Версальского договора.»)
        cut = []
        for sn in s.sentences:
            new = sn if sn in s.theses else _cut_dating_years(sn, bad_figs(sn))
            if new != sn and not bad_figs(new):
                if edits is not None:
                    edits.append({"where": f"{i}", "text": sn, "now": new, "why": "a year the article does not give, cut"})
                cut.append(new)
            else:
                cut.append(sn)
        s.sentences = cut

        def why_of(sn: str) -> Optional[str]:
            bad = bad_figures(sn)
            if bad:
                return f"not in the article: {', '.join(bad)[:80]}"
            names = unknown_names(sn, stems)
            if len(names) >= 2:
                return f"names not in the article: {', '.join(names)[:80]}"
            return None

        _prune(s, why_of, removed, f"{i}")
        if s.timeline:
            tl = []
            for e in s.timeline:
                line = f"{e['when']} — {e['what']}"
                bad = bad_figures(line)
                if bad:
                    _removed(removed, f"{i}", line, f"not in the article: {', '.join(bad)[:80]}")
                else:
                    tl.append(e)
            s.timeline = tl if len(tl) >= 3 else None
        if s.data:
            scale = unit_scale(s.data.get("unit"))
            unit = s.data.get("unit") or ""
            rows = []
            for r in s.data["rows"]:
                ok = False
                try:
                    ok = value_ok(idx, r["value"], scale)
                except Exception:  # noqa: BLE001
                    ok = True
                # a chart's row is the article's when its value stands next to its label there («СССР … 27 млн»): a
                # value the article writes about something else («20» somewhere) is the model's memory («Китай — 20»)
                near = ok and support.supported(f"{r['label']} — {fmt_value(r['value'])} {unit}".strip())
                if near and support.range_bound_only(r["value"], r["label"]):
                    _removed(removed, f"{i}", f"{s.data.get('caption')}: {r['label']} — {fmt_value(r['value'])} {unit}".strip(), "the article gives a range, not this value")
                    continue
                if ok and near:
                    rows.append(r)
                else:
                    _removed(removed, f"{i}", f"{s.data.get('caption')}: {r['label']} — {fmt_value(r['value'])} {unit}".strip(), "not in the article" if not ok else "not in the article next to its label")
            s.data["rows"] = rows
            s.data = _data_ok(s.data)
            _caption_gone(s)
    if deck.subtitle and bad_figures(deck.subtitle):
        _removed(removed, "cover", deck.subtitle, "not in the article")
        deck.subtitle = ""
    deck.slides = [s for s in deck.slides if not s.empty]
    return deck


# ------------------------------------------------------------------ the fact check (§6.3), deletion-only


def numbered(deck: _Deck, first: int = 1) -> str:
    lines = []
    for i, s in enumerate(deck.slides, first):
        lines.append(f"Slide {i}. {s.title}")
        for j, sn in enumerate(s.sentences, 1):
            lines.append(f"[{i}.{j}] {sn}")
        for k, e in enumerate(s.timeline or [], 1):
            lines.append(f"[{i}.t{k}] {e['when']} — {e['what']}")
        if s.data:
            for k, r in enumerate(s.data.get("rows") or [], 1):
                lines.append(f"[{i}.d{k}] {s.data.get('caption')}: {r['label']} — {fmt_value(r['value'])} {s.data.get('unit') or ''}".rstrip())
    return "\n".join(lines)


_ID_RE = re.compile(r"^\s*\[?\s*(\d{1,2})\s*\.\s*([td])?\s*(\d{1,2})\s*\]?\s*$", re.I)


class ArticleSupport:
    """Whether the full article(s) state a written statement, deterministically — the fact check's model reads only the
    ~12 000-character cut and reported true sentences of the full article as unsupported («погибло более 70 миллионов
    человек», «61 государство, 80 % населения», the atomic bombings). A statement is supported when every proper noun of
    it is in the article, it pairs its years with the right names and events (pair_issue: none), and
    - with figures: every figure is the article's (value level, dates and years included) and either all its figures
      and names stand together in one passage of the article (a sentence and the ones next to it) with one of its rare
      words — or with none needed for two full dates or a range («1 сентября 1939 — 2 сентября 1945», «60—65 млн») —,
      or each figure stands next to the statement's own words («61 государство (80 % населения Земного шара)» for «61
      страну и около 80 % населения Земли»): words the article uses rarely (not «компания», «Mail.ru» of the VK article:
      «В 2006 году компания была переименована в Mail.ru Group» is not supported by 2006 standing next to
      «компания»), two of them when the statement has three or more; a word may be the article's synonym («погибло» for
      «потери», «закончилась» for «завершилась»);
    - without figures: at least two of its rare words, and half of them, stand in one passage with its names.

    It also indexes the article sentence by sentence for the pairing checks (pair_issue): a year next to a name or an
    event must be the one the article gives it, a plan must not be told as done (or the reverse), a transfer must go the
    article's way."""

    COMMON_SHARE = 0.03  # a word of more than this share of the article's sentences is no evidence
    FREQUENT_SHARE = 0.10  # a name in more than this share of the sentences is the article's subject: not paired

    def __init__(self, full_texts: list[str], topic: str = "") -> None:
        from verstka.planning.grounding import BriefIndex, content_stems

        self.idx = BriefIndex("\n\n".join(full_texts))
        self.stems = _article_stems(list(full_texts) + [topic])
        self.topic = {x[:5] for x in content_stems(topic, neutral=True)}
        self._group: dict[int, set[str]] = {}
        self._ctx: dict[int, set[str]] = {}
        texts = self.idx._texts  # sentence group → its text
        df: dict[str, int] = {}
        for g, t in texts.items():
            got = {x[:5] for x in content_stems(t, neutral=True)}
            self._group[g] = got
            for x in got:
                df[x] = df.get(x, 0) + 1
        limit = max(3.0, self.COMMON_SHARE * max(1, len(texts)))
        self.common = {x for x, n in df.items() if n > limit}
        # the article sentence by sentence (the groups in order), for the passages and the pairing checks
        # (a sentence the splitter cut inside a quotation — «Территория будущего. Москва 2030» — is joined back)
        self.keys = sorted(texts)
        self.pos: dict[int, int] = {}
        self.sents: list[str] = []
        self.sstems: list[set[str]] = []
        for k in self.keys:
            t = " ".join(texts[k].split()).strip("= ").strip()
            if self.sents and self.sents[-1].count("«") > self.sents[-1].count("»"):
                self.sents[-1] = f"{self.sents[-1]} {t}"
                self.sstems[-1] = self.sstems[-1] | self._group.get(k, set())
            else:
                self.sents.append(t)
                self.sstems.append(set(self._group.get(k, set())))
            self.pos[k] = len(self.sents) - 1
        self.low = [s.lower().replace("ё", "е") for s in self.sents]
        self.years = [_statement_years(s) for s in self.sents]
        self.full = "\n".join(self.sents)
        self.full_low = "\n".join(self.low)
        self._phrases: dict[tuple, bool] = {}
        lead = self.sents[0] if self.sents else ""
        m = re.match(r"^([^(—–,]{1,40}?)\s*[(—–]", lead)
        self.subject = m.group(1).strip() if m else ""
        self._hits: dict[str, set[int]] = {}
        self._found: dict[tuple, list[int]] = {}
        self._inv: Optional[dict[str, set[int]]] = None
        self.former = _former_names(self.sents[0] if self.sents else "")
        from verstka.planning.reference import place_of

        where = place_of(topic) if topic else None
        self.place, self.place_stem = (where[0], where[1]) if where else ("", "")

    # -------------------------------------------------------------- words and names

    def _near(self, group: int) -> set[str]:
        got = self._ctx.get(group)
        if got is None:
            got = set().union(*(self._group.get(g, set()) for g in (group - 1, group, group + 1)))
            self._ctx[group] = got
        return got

    @staticmethod
    def _meets(a: str, near: set[str]) -> bool:
        return any(n.startswith(b) or b.startswith(n) for b in _synonyms(a) for n in near if min(len(b), len(n)) >= 3)

    def hits(self, stem5: str) -> set[int]:
        """The article sentences (positions) that have the word (its 5-letter stem) or one of its synonyms."""
        got = self._hits.get(stem5)
        if got is not None:
            return got
        if self._inv is None:
            inv: dict[str, set[int]] = {}
            for i, st in enumerate(self.sstems):
                for n in st:
                    for k in range(3, len(n) + 1):
                        inv.setdefault(n[:k], set()).add(i)
            self._inv = inv
        out: set[int] = set()
        for b in _synonyms(stem5):
            out |= self._inv.get(b, set())  # an article word that starts with it
            for k in range(3, len(b)):
                exact = self._inv.get(b[:k])
                if exact:
                    out |= {i for i in exact if b[:k] in self.sstems[i]}  # an article word it starts with
        self._hits[stem5] = out
        return out

    def rare(self, text: str, skip: Iterable[str] = ()) -> set[str]:
        """The statement's words the article uses rarely (5-letter stems; not the topic's, not a month, not a figure)."""
        from verstka.planning.grounding import content_stems

        skip = {x[:5] for x in skip}
        out = set()
        for x in content_stems(text, neutral=True):
            x = x[:5]
            if re.match(r"^\d", x) or x in self.topic or x in self.common or x in skip or _is_month_stem(x):
                continue
            out.add(x)
        return out

    def find(self, e: "_Ent") -> list[int]:
        """The article sentences that name the entity (every word of it, by its stem)."""
        got = self._found.get(e.prefs)
        if got is None:
            rxs = [re.compile(r"(?<![\wё])" + re.escape(p)) for p in e.prefs]
            got = [i for i, low in enumerate(self.low) if all(rx.search(low) for rx in rxs)]
            self._found[e.prefs] = got
        return got

    def frequent(self, e: "_Ent") -> bool:
        return len(self.find(e)) > max(12, self.FREQUENT_SHARE * len(self.sents))

    def _cap_mid(self, word: str) -> bool:
        """The article writes the word capitalised inside a sentence (a name, not a sentence's first word)."""
        p = word[: max(4, len(word) - 2)]
        return bool(re.search(r"[a-zа-яё0-9,;:)»]\s+" + re.escape(p), self.full))

    def _phrase(self, prefs: tuple) -> bool:
        """The article writes these words one after another (a name of several words: «Digital Sky Technologies»)."""
        got = self._phrases.get(prefs)
        if got is None:
            got = bool(re.search(r"(?<![\wё])" + r"\S*\s+".join(re.escape(p) for p in prefs), self.full_low))
            self._phrases[prefs] = got
        return got

    def entities(self, text: str) -> list["_Ent"]:
        return [e for e in _entities(text, self._cap_mid, self._phrase) if not all(p[:5] in self.topic for p in e.prefs)]

    def _renames(self, text: str) -> Optional[list[tuple[tuple, str, int]]]:
        """The renames a statement tells, as (its year span, the new name of the lead's chain, the year the chain gives
        that name): the name after «в» / «название» that follows each year («В 2010 году компания была переименована в
        Mail.ru Group, а в 2021 году — в VK»; «В 2021 году компания Mail.ru Group была переименована в VK»). None when it
        tells no rename, a year has no such name, or a name is not in the chain."""
        if not self.former or not _RENAME_RE.search(text):
            return None
        chain = sorted(self.former, key=lambda x: x[1])
        when = {(chain[k + 1][0] if k + 1 < len(chain) else self.subject).lower(): chain[k][1] for k in range(len(chain))}
        ents = _entities(text, self._cap_mid, self._phrase)
        ys = _statement_years(text)
        if not ys:
            return None
        out = []
        for k, y in enumerate(ys):
            stop = ys[k + 1][0] if k + 1 < len(ys) else len(text)
            new = [e for e in ents if y[1] <= e.start < stop and re.search(r"(?:\s[вВ]|назван\w*|именем)\s+«?$", text[: e.start])]
            if not new:
                return None
            name = next((nm for nm in when if nm and nm.startswith(new[0].text.lower()[:6])), None)
            if name is None:
                return None
            out.append((y, name, when[name]))
        return out

    def rename_fixed(self, text: str) -> Optional[str]:
        """A rename statement with the lead's years put in («В 2006 году компания была переименована в Mail.ru Group» →
        «В 2010 году …»); None when it is not a rename of the lead's chain."""
        got = self._renames(text)
        if not got:
            return None
        out, shift = text, 0
        for y, _name, right in got:
            if right != y[2]:
                a, b = y[0] + shift, y[1] + shift
                out = out[:a] + str(right) + out[b:]
                shift += len(str(right)) - (b - a)
        return out if out != text and self._rename_ok(out) else None

    def _rename_ok(self, text: str) -> bool:
        """A rename the lead's former names state: «В 2010 году компания была переименована в Mail.ru Group, а в 2021
        году — в VK» of «VK (до 12 октября 2021 года — Mail.ru Group, до 2010 года — Digital Sky Technologies)»: each
        year is the last year of the name before the new name it gives (the article's subject last)."""
        got = self._renames(text)
        return bool(got) and all(y[2] == right for y, _n, right in got)

    def _rename_wrong(self, text: str) -> bool:
        got = self._renames(text)
        return bool(got) and not all(y[2] == right for y, _n, right in got)

    # -------------------------------------------------------------- support

    def _window_names_ok(self, text: str, centre: int) -> bool:
        for e in self.entities(text):
            got = self.find(e)
            if got and not any(abs(i - centre) <= 1 for i in got):
                return False
        return True

    def _together(self, text: str, figs: list[Any]) -> bool:
        """All the statement's figures and names in one passage (a sentence ± 1), with one of its rare words there — none
        needed for two full dates or a range («1 сентября 1939 — 2 сентября 1945», «60—65 млн»)."""
        spots: list[set[int]] = []
        for f in figs:
            try:
                places = self.idx._same(f)
            except Exception:  # noqa: BLE001
                return False
            got = {self.pos[p.group] for p in places if p.group in self.pos}
            if not got:
                return False
            spots.append(got)
        dates = [f for f in figs if f.date is not None and f.date[2]]
        ranged = any(b.start - a.end <= 2 and re.fullmatch(r"\s*[—–-]\s*", text[a.end:b.start] or "-") for a, b in zip(figs, figs[1:]))
        distinctive = len(dates) >= 2 or ranged
        rare = self.rare(text, [p for e in self.entities(text) for p in e.prefs])
        for c in sorted(spots[0]):
            for centre in (c - 1, c, c + 1):
                if centre < 0 or centre >= len(self.sents):
                    continue
                if not all(any(abs(i - centre) <= 1 for i in s) for s in spots):
                    continue
                if not self._window_names_ok(text, centre):
                    continue
                if distinctive or not rare or any(self.hits(x) & {centre - 1, centre, centre + 1} for x in rare):
                    return True
        return False

    def _words_supported(self, text: str) -> bool:
        """A statement without figures: two of its rare words, and half of them, in one passage with its names."""
        rare = self.rare(text, [p for e in self.entities(text) for p in e.prefs])
        if len(rare) < 2:
            return False
        need = max(2, -(-len(rare) // 2))
        count: dict[int, int] = {}
        for x in rare:
            spread = {j for i in self.hits(x) for j in (i - 1, i, i + 1)}
            for j in spread:
                count[j] = count.get(j, 0) + 1
        return any(n >= need and self._window_names_ok(text, j) for j, n in count.items())

    def supported(self, text: str) -> bool:
        from verstka.planning.grounding import content_stems, figures

        text = " ".join((text or "").split())
        if unknown_names(text, self.stems) or unknown_names(f"x {text}", self.stems):
            return False
        if self._rename_ok(text):
            return True
        if self.pair_issue(text) is not None:
            return False
        figs = figures(text)
        if not figs:
            return self._words_supported(text)
        for f in figs:
            try:
                if self.idx.verdict(f) == "bad":
                    return False
            except Exception:  # noqa: BLE001 - a figure the index cannot judge: not supported
                return False
        if self._together(text, figs):
            return True
        mine = {x[:5] for x in content_stems(text, neutral=True) if not re.match(r"^\d", x)} - self.topic
        for f in figs:
            try:
                places = self.idx._same(f)
            except Exception:  # noqa: BLE001
                return False
            own = {x[:5] for x in content_stems(text[f.start:f.uend], neutral=True)}
            want = [x for x in mine - own if x not in self.common]
            if not want:
                want = list(mine - own)  # only common words: any of them
                need = 1 if want else 0
            else:
                need = 1 if len(want) <= 2 else 2
            if need and not any(sum(1 for x in want if self._meets(x, self._near(p.group))) >= need for p in places):
                return False
        return True

    def range_bound_only(self, value: float, label: str) -> bool:
        """The article gives this value next to the label only as a bound of a range («Общие людские потери достигли
        60—65 млн человек»: «Общие потери — 65» turns a range into its upper bound)."""
        from verstka.planning.grounding import content_stems

        v = fmt_value(value)
        rx = re.compile(rf"(?<![\d.,]){re.escape(v)}(?![\d.,])")
        stems = {x[:5] for x in content_stems(label or "", neutral=True) if not re.match(r"^\d", x)}
        seen = 0
        for s, low in zip(self.sents, self.low):
            if not stems or not any(st in low for st in stems):
                continue
            for m in rx.finditer(s):
                seen += 1
                before, after = s[max(0, m.start() - 8):m.start()], s[m.end():m.end() + 8]
                if not (re.search(r"\d\s*[—–-]\s*$", before) or re.match(r"^\s*[—–-]\s*\d", after)):
                    return False
        return seen > 0

    # -------------------------------------------------------------- pairing checks

    def _bound(self, i: int, e: "_Ent", year: int) -> bool:
        """The article's sentence `i` (which names the entity) gives it `year`: in the sentence — unless another year
        stands right at the name while this one is far («до 2010 года — Digital Sky Technologies) — …, основанная в
        1998 году»: 1998 is VK's, not DST's) — or, when the sentence has no year, in the one before or after it."""
        ys = self.years[i]
        if ys:
            # «…, Франции и стран Бенилюкса (май — июнь 1940), Югославии (апрель 1941)»: the brackets right after the
            # name date it, not the year closest to it
            own = []
            for m in re.finditer(r"(?<![\wё])" + re.escape(e.prefs[0]) + r"[\wё]*\s*\(([^()]*)\)", self.low[i]):
                own += [y for y in _year_spans(m.group(1))]
            if own:
                return any(y[2] <= year <= y[3] for y in own)
            hit = [y for y in ys if y[2] <= year <= y[3]]
            if not hit:
                return False
            other = [y for y in ys if not (y[2] <= year <= y[3])]
            if other:
                rx = re.compile(r"(?<![\wё])" + re.escape(e.prefs[0]))
                at = [m.start() for m in rx.finditer(self.low[i])]
                if at:
                    d_other = min(_dist(p, y) for p in at for y in other)
                    d_hit = min(_dist(p, y) for p in at for y in hit)
                    if d_other <= 15 and d_hit > 30:
                        return False
            return True
        # no year in the sentence: the paragraph's date (the nearest earlier sentence with a year, up to three back, not
        # past a heading) or the next sentence's
        for j in range(i - 1, max(-1, i - 4), -1):
            if _heading(self.sents[j]):
                break
            if self.years[j]:
                if any(y[2] <= year <= y[3] for y in self.years[j]):
                    return True
                break
        j = i + 1
        if j < len(self.sents) and any(y[2] <= year <= y[3] for y in self.years[j]):
            return True
        # the chapter's period («Второй период войны (июнь 1941 — ноябрь 1942 годов)» over «Осуществление плана
        # «Барбаросса» началось … 21 июня»)
        span = self._chapter(i)
        return span is not None and span[0] <= year <= span[1]

    def _chapter(self, i: int) -> Optional[tuple[int, int]]:
        """The years of the nearest chapter heading above sentence `i` that gives a period (first year, last year)."""
        for j in range(i - 1, max(-1, i - 150), -1):
            s = self.sents[j].strip()
            if s.endswith((".", "!", "?", "…", ":", ";")) or len(s.split()) > 12:
                continue
            ys = self.years[j]
            if ys:
                return min(y[2] for y in ys), max(y[3] for y in ys)
        return None

    def _scene(self, text: str, e: "_Ent") -> bool:
        """A place the statement's event happens in («В Азии Япония…», «в Европе»), which the article names often: the
        scene, not what the year dates."""
        return bool(re.search(r"(?:^|\s)(?:[Вв]о?|[Нн]а)\s+$", text[: e.start])) and len(self.find(e)) >= max(6, 0.01 * len(self.sents))

    def _event(self, text: str, cands: list[int], skip: Iterable[str] = ()) -> tuple[list[int], int]:
        """The candidate sentences that tell the statement's event best (most of its rare words) and that score."""
        rare = self.rare(text, skip)
        scored = [(sum(1 for x in rare if i in self.hits(x)), i) for i in cands]
        best = max((s for s, _ in scored), default=0)
        return ([i for s, i in scored if s == best] if best else list(cands)), best

    def pair_issue(self, text: str) -> Optional["_Pairing"]:
        """What the statement pairs wrongly against the article, or None: a former name told as the founding name
        («основана … как Digital Sky Technologies» where the lead says «до 2010 года — Digital Sky Technologies»); a
        year next to a name the article never gives that name (the name's sentence, or the one next to it when it has
        no year: «В 2024 году АвтоВАЗ начал производство e-Largus» — the article: February 2025); a plan told as done or
        a start told as a plan («В 2026 году начнётся выпуск UMO 5» — the article: «20 февраля 2026 года … началось
        производство»); a transfer the other way round («передал ей территории» — the article: «передал из её
        состава ряд территорий»)."""
        text = " ".join((text or "").split())
        if not text or not self.sents:
            return None
        low = text.lower()
        for name, until in self.former:
            k = low.find(name.lower()[: max(5, len(name) - 2)])
            if k > 0 and re.search(r"основ\w*[^.]*?\s(?:как|под\s+названием)\s+(?:компани\w+\s+|фонд\w*\s+)?«?$", low[:k]):
                return _Pairing("former", None, until, 0, f"«{name}» is a former name (until {until}), not the founding one")
        years = _statement_years(text)
        if self._rename_wrong(text):
            return _Pairing("rename", None, years[0][2] if years else 0, -1, "the article gives other years or names of the renames")
        ents = [e for e in self.entities(text) if self.find(e)]
        if years:
            failed: list[tuple[_Ent, int]] = []
            anchored = False
            for e in ents:
                if self.frequent(e) or self._scene(text, e):
                    continue
                year = min(years, key=lambda y: _dist(e.start, (y[0], y[1])))[2]
                # a name of several words is dated by any of its distinctive words too («Операция Барбаросса»: the
                # article dates «плана «Барбаросса»» by its chapter, 1941)
                generic = [p[:5] in _GENERIC_NAME_WORDS for p in e.prefs]
                subs = [e] + ([_Ent(w, e.start, e.end, (p,)) for w, p, g in zip(e.text.split(), e.prefs, generic) if len(p) >= 4 and not g]
                              if len(e.prefs) > 1 and any(generic) else [])
                if any(self._bound(i, x, year) for x in subs for i in self.find(x)):
                    anchored = True  # one name of the statement the article dates so: the year is the article's
                else:
                    failed.append((e, year))
            if failed and anchored and years[0][0] <= 20:
                # one item of a list the article dates otherwise («В 1940 году Германия захватила Данию, Норвегию,
                # Францию, страны Бенилюкса и Югославию» — «Югославии (апрель 1941)»): that item goes (the year opens
                # the statement and dates all of it — not «…, купленные в 2022 году» of one item)
                for e, year in failed:
                    if self._scene(text, e) or not any(self.years[i] for i in self.find(e)):
                        continue
                    if cut_list_item(text, e) is not None:
                        return _Pairing("item", e, year, -1, f"the article dates «{e.text}» otherwise than {year}")
            if failed and not anchored:
                e, year = failed[0]
                cands = self.find(e)
                ev, score = self._event(text, cands, e.prefs)
                dated = [i for i in ev if self.years[i]]
                # the same event: two of its words, or one and a second name of the statement («… АвтоВАЗ сообщила о
                # первой продаже электромобиля e-Largus»)
                names_in = sum(1 for x in ents if x is not e and set(self.find(x)) & set(dated or ev))
                strong = score >= 2 or (score >= 1 and names_in >= 1)
                return _Pairing("year" if dated else "undated", e, year, (dated or ev)[0] if strong else -1,
                                f"{year} is not the article's year of «{e.text}»")
        # a month the article gives the event otherwise («В марте 1941 года Германия начала вторжение в Югославию» — the
        # article: «6 апреля 1941 года»), or a month where the article gives only the season («летом 1944 года»)
        if years:
            got = self._month_issue(text, ents) or self._event_year_issue(text, ents, years)
            if got is not None:
                return got
        # a plan told as done, or the reverse
        fut, past = bool(_FUTURE_RE.search(text)), bool(_PAST_RE.search(text))
        if years and fut != past:
            for y in years:
                year = y[2]
                cands = [i for i in range(len(self.sents)) if any(z[2] <= year <= z[3] for z in self.years[i])]
                if not cands:
                    continue
                skip = [p for e in ents for p in e.prefs]
                rare = self.rare(text, skip)
                named = {i for e in ents for i in self.find(e)}
                scored = sorted(((sum(1 for x in rare if i in self.hits(x)) + (2 if i in named else 0), i) for i in cands), reverse=True)
                if not scored or scored[0][0] < 2 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
                    continue
                i = scored[0][1]
                a_fut, a_past = bool(_FUTURE_RE.search(self.sents[i])), bool(_PAST_RE.search(self.sents[i]))
                who = next((e for e in ents if i in self.find(e) and not self.frequent(e)), None)  # the clause to take
                if fut and a_past and not a_fut:
                    return _Pairing("tense", who, year, i, "told as a plan, the article says it happened")
                if past and a_fut and not a_past:
                    return _Pairing("tense", who, year, i, "told as done, the article says it is a plan")
        if not years and fut and not past:
            # no year: a plan about a product the article names in a few sentences, which tell it as done («…а также
            # планируется выпуск электрического кроссовера UMO 5» — the article: «20 февраля 2026 года … началось
            # производство … UMO 5»)
            rare_all = self.rare(text, [p for e in ents for p in e.prefs])
            for e in ents:
                where = self.find(e)
                if self.frequent(e) or not where or len(where) > 5 or not re.search(r"[A-Za-z0-9]", e.text) and text[max(0, e.start - 1)] != "«":
                    continue
                if not _FUTURE_RE.search(text[max(0, e.start - 90):e.start]):
                    continue  # the plan is about another thing of the sentence
                scored = sorted(((sum(1 for x in rare_all if i in self.hits(x)), i) for i in where), reverse=True)
                i = scored[0][1]
                a_fut, a_past = bool(_FUTURE_RE.search(self.sents[i])), bool(_PAST_RE.search(self.sents[i]))
                if a_past and not a_fut and scored[0][0] >= 1:
                    return _Pairing("tense", e, 0, i, "told as a plan, the article says it happened")
        # a world figure told as the topic's place's («В 2025 году общая стоимость владения электромобилем сравнялась
        # с автомобилями с ДВС» — the article: «…в мире сравнима…»)
        measured = _has_figure(re.sub(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?:\s*[—–-]\s*(?:1\d{3}|20\d{2}))?", " ", text)) or bool(_MEASURE_RE.search(text))
        if self.place and measured and not _PLACE_WORD_RE.search(text) and self.place_stem not in text.lower():
            rare = self.rare(text, [p for e in ents for p in e.prefs])
            if len(rare) >= 2:
                scored = sorted(((sum(1 for x in rare if i in self.hits(x)), i) for i in range(len(self.sents))), reverse=True)[:2]
                sc, i = scored[0]
                unique = len(scored) < 2 or scored[1][0] < sc
                s_low = self.low[i]
                if sc >= max(2, -(-2 * len(rare) // 3)) and unique and _PLACE_WORD_RE.search(self.sents[i]) and self.place_stem not in s_low:
                    if not years or any(any(z[2] <= y[2] <= z[3] for z in self._passage_years(i)) for y in years):
                        return _Pairing("place", None, years[0][2] if years else 0, i, "the article gives it for another place than the topic's")
        # the direction of a transfer
        gain, lose = bool(_GAIN_RE.search(text)), bool(_LOSE_RE.search(text))
        if gain != lose:
            skip = [p for e in ents for p in e.prefs]
            rare = self.rare(text, skip)
            if len(rare) >= 3:
                scored = sorted(((sum(1 for x in rare if i in self.hits(x)), i) for i in range(len(self.sents))), reverse=True)[:3]
                for sc, i in scored:
                    if sc < 3:
                        break
                    a_gain, a_lose = bool(_GAIN_RE.search(self.sents[i])), bool(_LOSE_RE.search(self.sents[i]))
                    if (gain and a_lose and not a_gain) or (lose and a_gain and not a_lose):
                        return _Pairing("direction", None, 0, i, "the transfer goes the other way in the article")
        return self._verb_issue(text, ents) or self._founder_issue(text, ents)

    def _founder_issue(self, text: str, ents: list["_Ent"]) -> Optional["_Pairing"]:
        """A person told as the founder of the subject whom the article names the founder of another company:
        «Основателем компании стал Евгений Голанд» — the article: «…для внутренних нужд американской компании DataArt,
        основанной российским эмигрантом Евгением Голандом»."""
        if not _FOUNDER_RE.search(text):
            return None
        low = text.lower()
        for e in ents:
            if len(e.prefs) < 2 or re.search(r"[A-Za-z]", e.text) or self.frequent(e):
                continue  # a person: two words of a name
            for i in self.find(e):
                s = self.sents[i]
                ms = list(_FOUNDER_RE.finditer(s))
                if not ms:
                    continue
                at = [x.start() for x in re.finditer(r"(?<![\wё])" + re.escape(e.prefs[-1]), self.low[i])] or [0]
                m = min(ms, key=lambda x: min(abs(x.start() - p) for p in at))
                orgs = [o for o in _entities(s, self._cap_mid, self._phrase)
                        if o.end <= m.start() and m.start() - o.end <= 40 and (re.search(r"[A-Za-z]", o.text) or s[max(0, o.start - 1)] == "«")]
                if not orgs:
                    continue
                org = orgs[-1]
                if org.text.lower()[:5] in low or (self.subject and org.text.lower().startswith(self.subject.lower()[:5])):
                    continue
                return _Pairing("founder", e, 0, i, f"the article names «{e.text}» the founder of «{org.text}»")
        return None

    def _verb_issue(self, text: str, ents: list["_Ent"]) -> Optional["_Pairing"]:
        """A thing told as the subject's own creation that the article only tells as bought: «Компания запустила
        социальную сеть «ВКонтакте»» — the article: DST «вошёл в капитал «ВКонтакте»», Mail.ru Group «приобрела долю»;
        «запуская новые продукты: «Одноклассники», …» — «Одноклассники» were bought. Only the names after the verb (a
        name before it may be the real founder: «Павел Дуров основал «ВКонтакте»»)."""
        m = _CREATE_RE.search(text)
        if not m:
            return None
        if any(e.start < m.start() and not self.frequent(e) for e in ents):
            return None
        def near(rx: re.Pattern, i: int, e: "_Ent") -> bool:
            at = [x.start() for x in re.finditer(r"(?<![\wё])" + re.escape(e.prefs[0]), self.low[i])]
            return any(abs(v.start() - p) <= 80 for v in rx.finditer(self.sents[i]) for p in at)

        for e in ents:
            if e.start < m.end() or e.start - m.end() > 80 or self.frequent(e) or re.search(r"(?<![\wё])(?:после|благодаря|вдохнов\w*)(?![\wё])", text[m.end():e.start], re.I):
                continue
            quoted = e.start > 0 and text[e.start - 1] == "«" or bool(re.search(r"[A-Za-z]", e.text))
            if not quoted or (len(e.prefs) == 1 and _ADJ_NAME_RE.search(e.text)):
                continue  # a product's or a company's name, not a place or a word
            where = self.find(e)
            if not where or len(where) > 15:
                continue
            made = sum(1 for i in where if near(_CREATE_RE, i, e))
            bought = sum(1 for i in where if near(_ACQUIRE_RE, i, e))
            if bought and not made:
                return _Pairing("verb", e, 0, -1, f"the article tells «{e.text}» as bought, not created")
        return None

    def _month_issue(self, text: str, ents: list["_Ent"]) -> Optional["_Pairing"]:
        """The first month date of the statement that the article gives its event otherwise, conservatively: the
        statement's names (not the article's subject, not a scene, not an adjective of a name — «Красная», «Восточного»)
        are looked up in the article sentences of that year; the date is fine when one of them that tells the event (one
        of the statement's own words) gives that month anywhere; it is wrong when the sentence that tells the event best
        (two of its words at least) gives another month or only a season — «В марте 1941 года Германия начала вторжение
        в Югославию» (the article: «6 апреля 1941 года … вторглись в Югославию»), «В июле 1944 года … в Восточной
        Белоруссии» (the article: «Летом 1944 года»)."""
        # an adjective of a name that the article writes often («Красная армия», «Восточного фронта») dates too many
        # events; a rare one («Курская битва») dates its own
        cands = [e for e in ents if not self.frequent(e) and not (len(e.prefs) == 1 and _ADJ_NAME_RE.search(e.text) and len(self.find(e)) > 8)
                 and not (e.start <= 3 and self._scene(text, e))]  # «В Тихом океане …»: the scene, not what the date dates
        if not cands:
            return None
        rare = self.rare(text, [p for x in ents for p in x.prefs])
        need = min(2, len(rare))  # the event's own words the article sentence must share (none: a name it gives ≤ 3 times)
        score = lambda i: sum(1 for r in rare if i in self.hits(r))  # noqa: E731
        from verstka.planning.grounding import content_stems

        own = {x[:5] for x in content_stems(text, neutral=True) if not re.match(r"^\d", x) and not _is_month_stem(x[:5])}
        own -= {p[:5] for x in ents for p in x.prefs}
        tells = lambda i: any(i in self.hits(x) for x in own)  # noqa: E731 - a word of the statement's event is there
        for w in _whens(text):
            if w.season:
                continue
            best: Optional[tuple[int, _When, int, _Ent]] = None
            anchored = False
            dated: dict[int, list[tuple[_When, int]]] = {}
            for k, e in enumerate(cands):
                for i in self.find(e):
                    ws = [x for x in _whens(self.sents[i], inherit=True, default_year=self._paragraph_year(i)) if x.year == w.year]
                    if not ws:
                        continue
                    sc = score(i)
                    if (sc >= 1 or len(self.find(e)) <= 5 and tells(i)) and any(x.months & w.months for x in ws if not x.season):
                        anchored = True
                        break
                    pos = [m.start() for m in re.finditer(r"(?<![\wё])" + re.escape(e.prefs[0]), self.low[i])] or [0]
                    x = min(ws, key=lambda z: min(abs(z.start - p) for p in pos))
                    dated.setdefault(k, []).append((x, i))
                    if best is None or (sc, bool(x.day)) > (best[0], bool(best[1].day)):
                        best = (sc, x, i, e)
                if anchored:
                    break
            if anchored or best is None:
                continue
            if best[0] < need or (need == 0 and len(self.find(best[3])) > 3):
                # a name the article gives in a few sentences, all of that year's dating it the same month («Курская
                # битва»: «В июле 1943 года … в битве под Курском»): its date, whatever the statement's other words
                told = {k: [(x, i) for x, i in xs if tells(i)] for k, xs in dated.items()}
                alone = [(k, xs) for k, xs in told.items() if xs and len(self.find(cands[k])) <= 5 and len({x.months for x, _ in xs}) == 1]
                if not alone:
                    continue
                k, xs = alone[0]
                # … that tells the statement's event (a word of it: «битве под Курском» for «Курская битва»; not «вошла
                # в Ростов, достигнув целей плана «Барбаросса»» for «вторжение … в рамках операции «Барбаросса»»)
                if not tells(xs[0][1]):
                    continue
                # … unless the article gives the statement's month to the place the name comes from («Ялтинской
                # конференции» — «4—11 февраля 1945 года в Ялте»)
                r4 = cands[k].prefs[0][:4]
                root = re.compile(r"(?<![\wё])" + re.escape(r4[:3] if r4[-1:] in "аеёиоуыэюя" else r4))
                if any(root.search(low) and any(x.months & w.months for x in _whens(self.sents[j], inherit=True) if x.year == w.year and not x.season)
                       for j, low in enumerate(self.low)):
                    continue
                best = (need, xs[0][0], xs[0][1], cands[k])
            if best[1].months & w.months and not best[1].season:
                continue
            sc, x, i, e = best
            return _Pairing("month", e, w.year, i, f"the article dates «{e.text}» {_date_phrase(x)}", fix=(w, x))
        return None

    def _paragraph_year(self, i: int) -> int:
        """The last year of the nearest earlier sentence that writes one (up to three back, not past a heading)."""
        for j in range(i - 1, max(-1, i - 4), -1):
            if _heading(self.sents[j]):
                break
            if self.years[j]:
                return max(y[3] for y in self.years[j])  # the narrative's time (an older year is a reference back)
        return 0

    def _passage_years(self, i: int) -> list[tuple]:
        """The years of an article sentence, else of the one before it (not past a heading), else of the one after."""
        if self.years[i]:
            return self.years[i]
        if i > 0 and not _heading(self.sents[i - 1]) and self.years[i - 1]:
            return self.years[i - 1]
        return self.years[i + 1] if i + 1 < len(self.sents) else []

    def _event_year_issue(self, text: str, ents: list["_Ent"], years: list[tuple]) -> Optional["_Pairing"]:
        """A statement of one year whose event the article tells, unmistakably, in a passage of another year: «В мае
        1961 года Совет Министров утвердил программу первого пилотируемого полёта» — the article: «В мае 1959 года …
        было принято решение Совета Министров СССР об утверждении разработки пилотируемого комплекса». Unmistakable: at
        least three of the statement's own words (and 60 % of them) in one sentence, its names in the passage, no
        sentence as close with the statement's year."""
        if len(years) != 1 or years[0][2] != years[0][3]:
            return None
        y = years[0][2]
        rare = {r for r in self.rare(text, [p for e in ents for p in e.prefs]) if len(r) >= 4}
        names = [e for e in ents if not self.frequent(e)]
        if len(names) >= 2:
            # two names of the statement that the article writes together in one sentence only, with its event's words
            # («В 2024 году началось производство «Москвич 3е» на Московском автомобильном заводе» — the article: «23
            # ноября 2022 на Московском автомобильном заводе стартовало производство «Москвич 3е»»)
            both = set.intersection(*[set(self.find(e)) for e in names])
            if len(both) == 1:
                at = next(iter(both))
                from verstka.planning.grounding import content_stems

                own = {x[:5] for x in content_stems(text, neutral=True) if not re.match(r"^\d", x)} - {p[:5] for e in names for p in e.prefs}
                shared = sum(1 for x in own if at in self.hits(x))
                pys = sorted({(z[2], z[3]) for z in self._passage_years(at)})
                if shared >= 2 and len(pys) == 1 and pys[0][0] == pys[0][1] and pys[0][0] != y:
                    return _Pairing("event", names[0], y, at, f"the article tells this event in {pys[0][0]}, not {y}", fix=pys[0][0])
        if len(rare) < 2 or len(rare) + len(names) < 3:
            return None
        named = [set(self.find(e)) for e in names]
        hits = {i: sum(1 for r in rare if i in self.hits(r)) for i in range(len(self.sents))}
        scored = [(hits[i] + sum(1 for s in named if i in s), i) for i in range(len(self.sents))]
        best = max((s for s, _ in scored), default=0)
        if best < max(3, -(-6 * (len(rare) + len(names)) // 10)):
            return None
        tops = [i for s, i in scored if s == best and hits[i] >= 2]
        if not tops or any(any(z[2] <= y <= z[3] for z in self._passage_years(i)) for s, i in scored if s >= best - 1):
            return None
        found = {tuple(self._passage_years(i)) for i in tops}
        if len(found) != 1:
            return None
        pys = sorted({(z[2], z[3]) for z in next(iter(found))})
        if len(pys) != 1 or pys[0][0] != pys[0][1]:
            return None
        yb = pys[0][0]
        at = tops[0]
        if not all(any(abs(j - at) <= 1 for j in s) for s in named):
            return None
        return _Pairing("event", names[0] if names else None, y, at, f"the article tells this event in {yb}, not {y}", fix=yb)

    def event_year_fixed(self, text: str, p: "_Pairing") -> Optional[str]:
        """The statement with the article's year of its event (and the article's month, when it gives one then)."""
        yb = int(p.fix)
        passage = " ".join(self.sents[j] for j in (p.at - 1, p.at, p.at + 1) if 0 <= j < len(self.sents))
        mine = [w for w in _whens(text) if w.year == p.year and not w.season]
        theirs = [w for w in _whens(passage) if w.year == yb and not w.season]
        if mine and theirs:
            return replace_when(text, mine[0], theirs[0])
        ys = [z for z in _statement_years(text) if z[2] == p.year]
        if not ys:
            return None
        a, b = ys[0][0], ys[0][1]
        return text[:a] + str(yb) + text[b:]

    def rewrite(self, p: "_Pairing", text: str) -> Optional[str]:
        """The article's own sentence of the event (without brackets), or its clause that names the entity with the
        sentence's date in front — at most 32 words; None when there is none fit to stand on a slide."""
        if p.at < 0 or p.at >= len(self.sents):
            return None
        return article_clause(self.sents[p.at], p.entity.prefs if p.entity else (), want_year=bool(_statement_years(text)))


# a year or a range of years — never a decade («конце 1990-х годов»)
_Y_RE = re.compile(r"(?<![\d.,])(1\d{3}|20\d{2})(?:(?:\s*[—–-]\s*|\s+по\s+)(1\d{3}|20\d{2}))?(?![\d.,])(?!\s*[-‑]\s*(?:х|е|ые|ых|ым|ми)(?![а-яё]))")


def _year_spans(text: str) -> list[tuple[int, int, int, int]]:
    """(start, end, first year, last year) of every year or range of years of a text («1997—1998», «с 2005 по 2010»)."""
    out = []
    for m in _Y_RE.finditer(text or ""):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a or b - a > 40:
            b = a
        out.append((m.start(), m.end(), a, b))
    return out


def _statement_years(text: str) -> list[tuple[int, int, int, int]]:
    """The years of a statement outside quoted names («Москва 2030» is a name)."""
    quoted = [(m.start(), m.end()) for m in re.finditer(r"«[^«»]*»", text or "")]
    return [y for y in _year_spans(text) if not any(a <= y[0] < b for a, b in quoted)]


def _heading(sentence: str) -> bool:
    """A section heading of the article (a line without a full stop, a few words)."""
    s = (sentence or "").strip()
    return bool(s) and not s.endswith((".", "!", "?", "…", "»", ")")) and len(s.split()) <= 8


def _dist(p: int, y: tuple) -> int:
    a, b = y[0], y[1]
    return a - p if a >= p else max(0, p - b)


_FORMER_RE = re.compile(r"до\s+(?:\d{1,2}\s+[а-яё]+\s+)?(1\d{3}|20\d{2})\s+года?\s+[—–-]\s+([^,;()]+?)\s*(?=[,;)])")


def _former_names(lead: str) -> list[tuple[str, int]]:
    """The former names the lead gives («VK (до 12 октября 2021 года — Mail.ru Group, до 2010 года — Digital Sky
    Technologies)»): [(«Mail.ru Group», 2021), («Digital Sky Technologies», 2010)]."""
    head = (lead or "")[:400]
    return [(m.group(2).strip(), int(m.group(1))) for m in _FORMER_RE.finditer(head) if 2 <= len(m.group(2).strip()) <= 60]


_MONTH_ALT = r"(?:январ[а-яё]*|феврал[а-яё]*|март[а-яё]*|апрел[а-яё]*|ма[йяе](?![а-яё])|июн[а-яё]*|июл[а-яё]*|август[а-яё]*|сентябр[а-яё]*|октябр[а-яё]*|ноябр[а-яё]*|декабр[а-яё]*)"
_MD_RE = re.compile(
    rf"(?<![\d.,])(?:\d{{1,2}}\s*[—–-]\s*)?(?:(\d{{1,2}})\s+)?({_MONTH_ALT})(?:\s*[—–-]\s*(?:(\d{{1,2}})\s+)?({_MONTH_ALT}))?\s+(1\d{{3}}|20\d{{2}})(?![\d.,])",
    re.I,
)
_SEASON_RE = re.compile(r"(?<![\wё])(летом|весной|осенью|зимой|лето|весна|осень|зима|в\s+начале|в\s+конце|в\s+середине)\s+(1\d{3}|20\d{2})(?![\d.,])", re.I)
_SEASON_MONTHS = (("лет", {6, 7, 8}), ("весн", {3, 4, 5}), ("осен", {9, 10, 11}), ("зим", {12, 1, 2}), ("начал", {1, 2, 3, 4}),
                  ("конц", {9, 10, 11, 12}), ("середин", {5, 6, 7, 8}))
_SEASON_NOM = {"лет": "Лето", "весн": "Весна", "осен": "Осень", "зим": "Зима"}
_MONTH_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
_MONTH_PREP = ("январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре")
_MONTH_NOM = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


@dataclass
class _When:
    start: int
    end: int
    year: int
    months: frozenset
    day: int = 0
    month: int = 0  # the first month (0 for a season)
    last: int = 0  # the last month of a range
    season: str = ""  # «летом», «в начале» …


_BARE_MONTH_RE = re.compile(rf"(?<![\d.,])(?:(\d{{1,2}})\s+)?({_MONTH_ALT})(?!\s*[—–-]?\s*(?:\d{{1,2}}\s+{_MONTH_ALT}\s+)?(?:1\d{{3}}|20\d{{2}}))", re.I)


def _whens(text: str, inherit: bool = False, default_year: int = 0) -> list[_When]:
    """The month dates (a day, a month, a range of months) and the seasons of a text, with their years; `inherit` (an
    article's sentence): a day or a month written without its year takes the year written before it in the sentence
    («В июне 1940 года Гитлер приказал …, и ОКХ 22 июля начало разработку плана» — 22 июля 1940)."""
    out: list[_When] = []
    if inherit:
        quoted = [(q.start(), q.end()) for q in re.finditer(r"«[^«»]*(?:«[^«»]*»[^«»]*)*»?", text or "")]
        for m in _BARE_MONTH_RE.finditer(text or ""):
            if m.group(1) is None and not re.search(r"(?:^|\s)(?:[ВвКк]|[Сс]|[Дд]о|[Пп]о)\s+$", text[: m.start()]):
                continue  # a month's name without a day or a «в»: not a date («Май» of a name)
            if any(a <= m.start() < b for a, b in quoted):
                continue  # a date inside a quotation (a letter quoted) is not the sentence's
            before = [int(y.group(1)) for y in re.finditer(r"(?<![\d.,])(1\d{3}|20\d{2})(?![\d.,])", text[: m.start()])]
            if not before and default_year and not re.search(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?![\d.,])", text):
                before = [default_year]  # a sentence without a year of its own: its paragraph's («6 августа на Хиросиму…»)
            if not before:
                continue
            a = _month_of(m.group(2))
            if a:
                out.append(_When(m.start(), m.end(), before[-1], frozenset({a}), int(m.group(1) or 0), a))
    for m in _MD_RE.finditer(text or ""):
        a, b = _month_of(m.group(2)), _month_of(m.group(4)) if m.group(4) else 0
        if not a:
            continue
        months = frozenset(range(a, b + 1)) if b and b >= a else frozenset({a, b} - {0})
        out.append(_When(m.start(), m.end(), int(m.group(5)), months, int(m.group(1) or 0) if not b else 0, a, b))
    for m in _SEASON_RE.finditer(text or ""):
        w = m.group(1).lower()
        months = next((ms for st, ms in _SEASON_MONTHS if st in w), set())
        if months and not any(x.start <= m.start() < x.end for x in out):
            out.append(_When(m.start(), m.end(), int(m.group(2)), frozenset(months), season=" ".join(w.split())))
    return out


def _date_phrase(w: _When, nominative: bool = False) -> str:
    """How a date is written in a sentence («6 апреля 1941 года», «в апреле 1941 года», «летом 1944 года») or as a
    timeline's date (`nominative`: «6 апреля 1941», «Апрель 1941», «Лето 1944»)."""
    if w.season:
        if nominative:
            nom = next((v for k, v in _SEASON_NOM.items() if w.season.startswith(k)), None)
            return f"{nom} {w.year}" if nom else f"{H.cap_first(w.season)} {w.year}"
        return f"{w.season} {w.year} года"
    if w.day and not w.last:
        return f"{w.day} {_MONTH_GEN[w.month - 1]} {w.year}" + ("" if nominative else " года")
    if w.last:
        if nominative:
            return f"{H.cap_first(_MONTH_NOM[w.month - 1])} — {_MONTH_NOM[w.last - 1]} {w.year}"
        return f"в {_MONTH_PREP[w.month - 1]} — {_MONTH_PREP[w.last - 1]} {w.year} года"
    return f"{H.cap_first(_MONTH_NOM[w.month - 1])} {w.year}" if nominative else f"в {_MONTH_PREP[w.month - 1]} {w.year} года"


def replace_when(text: str, old: _When, new: _When) -> str:
    """The text with its date phrase `old` («В марте 1941 года») written as the article's `new` («6 апреля 1941
    года»); a timeline's date (no preposition, no «года») in the nominative."""
    a, b = old.start, old.end
    pre = re.search(r"(?:^|(?<=\s))[ВвСс]\s+$", text[:a])
    tail = re.match(r"\s*(?:года|году|г\.)", text[b:])
    dated = bool(pre or tail)
    if pre:
        a = pre.start()
    if tail:
        b += tail.end()
    phrase = _date_phrase(new, nominative=not dated)
    if a == 0 or not text[:a].strip() or re.search(r"[.!?:]\s*$", text[:a]):
        phrase = H.cap_first(phrase)
    elif not new.season and not (new.day and not new.last):
        phrase = phrase[:1].lower() + phrase[1:]  # «(июнь 1942 — …)» inside a sentence
    return text[:a] + phrase + text[b:]


# an adjective of a name («Красная армия», «Восточного фронта», «Ялтинской конференции»): too many events to date by it
_ADJ_NAME_RE = re.compile(r"(?:ая|яя|ое|ее|ый|ий|ой|ого|его|ому|ему|ых|их|ую|юю|ыми|ими)$")

# a place other than the topic's: the world, a country, a continent
_PLACE_WORD_RE = re.compile(
    r"(?<![\wё])(?:в\s+мире|мирово\w*|мировы\w*|глобальн\w*|в\s+Китае|в\s+США|в\s+Европе|в\s+Норвегии|в\s+Германии|в\s+Японии|"
    r"Китая|США|Европ\w*|Норвеги\w*)(?![\wё])")


_MEASURE_RE = re.compile(r"(?<![\wё])(?:стоимост\w*|цен[аыуе]\w*|продаж\w*|дол[яиюей]|количеств\w*|числ[оа]\w*|объ[её]м\w*|парк\w*|"
                         r"регистрац\w*|выручк\w*|доход\w*)(?![\wё])", re.I)


def _has_figure(text: str) -> bool:
    from verstka.planning.grounding import figures

    return bool(figures(text or ""))


_FOUNDER_RE = re.compile(r"(?<![\wё])(?:основател\w*|основал[аи]?|основанн\w*)(?![\wё])", re.I)
_CREATE_RE = re.compile(r"(?<![\wё])(?:основал[аио]?|основан[аоы]?|создал[аио]?|создан[аоы]?|запустил[аио]?|запуская|запущен[аоы]?|разработал[аио]?|учредил[аио]?)(?![\wё])", re.I)
_ACQUIRE_RE = re.compile(
    r"(?<![\wё])(?:приобр\w+|купил\w*|покупк\w*|выкуп\w*|консолидир\w*|капитал\w*|поглотил\w*|доля|долю|доли|сделк\w*|"
    r"получил\w*\s+(?:полный\s+)?контроль)(?![\wё])", re.I)


def cut_list_item(text: str, e: Optional["_Ent"]) -> Optional[str]:
    """The statement without one item of its enumeration («…: «Одноклассники», «Мой мир», мессенджеры и «Юла»» →
    «…: «Мой мир», мессенджеры и «Юла»»); None when the name is not an item of a list of three or more."""
    if e is None:
        return None
    a, b = e.start, e.end
    if a > 0 and text[a - 1] == "«" and b < len(text) and text[b:b + 1] == "»":
        a, b = a - 1, b + 1
    before, after = text[:a], text[b:]
    items = len(re.findall(r",\s", text)) + len(re.findall(r"\sи\s", text))
    if items < 2:
        return None
    m = re.match(r"\s*,\s*", after)
    if m:
        out = before + after[m.end():]
    else:
        m2 = re.search(r",\s*$", before)
        m3 = re.search(r"\s+и\s+$", before)
        if m3:
            prev = re.search(r",\s*([^,]+?)\s+и\s+$", before)
            if not prev:
                return None
            out = before[: prev.start()] + " и " + prev.group(1) + after
        elif m2:
            out = before[: m2.start()] + after
        else:
            return None
    out = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(out.split()))
    return out if len(out.split()) >= 4 else None


_RENAME_RE = re.compile(r"переименова|получил\w*\s+(?:новое\s+)?назван|сменил\w*\s+назван", re.I)
# the words of a name that say what kind of thing it is, not which one («Операция Барбаросса», «Битва за Москву»)
_GENERIC_NAME_WORDS = frozenset({"опера", "плана", "план", "битва", "битве", "битвы", "сраже", "догов", "компа", "групп", "корпо", "фонда",
                                 "завод", "проек", "прогр", "конфе", "пакта", "пакт"})

_SYNONYM_GROUPS = (
    ("погиб", "потер", "жертв", "убит", "гибел", "унесл"),
    ("закон", "завер", "оконч", "капит"),
    ("начал", "вторг", "вторж", "напал", "напад"),
    ("основ", "созда", "учред"),
    ("переи", "назва", "ребре"),
    ("запус", "старт", "откры"),
    ("приоб", "купил", "покуп", "купле"),
)
_SYN: dict[str, tuple[str, ...]] = {w: g for g in _SYNONYM_GROUPS for w in g}


def _synonyms(stem5: str) -> tuple[str, ...]:
    for w, g in _SYN.items():
        if stem5.startswith(w) or (len(stem5) >= 4 and w.startswith(stem5)):
            return tuple(dict.fromkeys((stem5,) + g))
    return (stem5,)


_FUTURE_RE = re.compile(
    r"(?<![\wё])(?:начн[её]тся|начнут|начн[её]т|будет|будут|планиру\w*|запланирован\w*|станет|станут|откро[её]тся|появится|"
    r"намерен\w*|ожида\w*|предполага\w*|собира\w*ся|выпуст(?:ит|ят)|произвед(?:[её]т|ут)|о\s+планах|планы\s+(?:по|на|производить|выпуска\w*|начать|запустить|продолжать))(?![\wё])",
    re.I,
)
_PAST_RE = re.compile(
    r"(?<![\wё])(?:начал(?:ся|ось|ась|ись|а|и)?|стартовал\w*|запущен\w*|запустил\w*|выпустил\w*|выпущен\w*|представлен\w*|"
    r"представил\w*|открыт[аоы]?|открыл\w*|появил\w*|вышл[аио]|вышел|произв[её]л\w*|произведен[аоы]?|подписал\w*|"
    r"подписан[аоы]?|завершил\w*|расширил\w*|увеличил\w*)(?![\wё])",
    re.I,
)
_GAIN_RE = re.compile(r"передал\w*\s+(?:ей|ему|им)(?![\wё])|(?:получил\w*|приобр[её]л\w*)\s+(?:\w+\s+)?(?:территори|колони|земл|област)", re.I)
_LOSE_RE = re.compile(
    r"передал\w*\s+из\s+(?:её|ее|его|их)\s+состава|потерял\w*|потеряны|лишил\w*|лишен\w*|утратил\w*|отторгнут\w*|отошл\w*\s+к", re.I,
)


@dataclass
class _Ent:
    text: str
    start: int
    end: int
    prefs: tuple[str, ...]


@dataclass
class _Pairing:
    kind: str  # former | rename | year | undated | item | month | event | tense | direction | verb | founder | place
    entity: Optional[_Ent]
    year: int
    at: int  # the article sentence of the event (-1: none to rewrite from)
    why: str
    fix: Any = None  # month: (the statement's date, the article's date)


_ENT_TOKEN_RE = re.compile(r"«|»|[A-Za-zА-ЯЁа-яё0-9][\w+.\-]*[\w+]|[A-Za-zА-ЯЁа-яё]")
_ENT_STOP = frozenset({"слайд", "глава", "статья"})


def _prefix(tok: str) -> str:
    t = tok.lower().replace("ё", "е").rstrip(".-")
    if re.search(r"[a-z]", t):
        return t
    return t[: max(4, min(len(t) - 2, 7))] if len(t) > 4 else t[: max(3, len(t) - 1)]  # «Азии» / «Азией»


def _entities(text: str, cap_mid: Callable[[str], bool], phrase: Optional[Callable[[tuple], bool]] = None) -> list[_Ent]:
    """The names a statement gives: capitalised words inside it (its first word when the article writes it
    capitalised inside a sentence), Latin words («e-Largus», «UMO»), capitalised words in quotes («Москвич»); the
    adjacent ones make one name («Digital Sky Technologies», «Перл-Харбор»). Months are not names."""
    toks: list[tuple[int, int, str, bool]] = []
    quoted = False
    for m in _ENT_TOKEN_RE.finditer(text or ""):
        t = m.group(0)
        if t == "«":
            quoted = True
            continue
        if t == "»":
            quoted = False
            continue
        toks.append((m.start(), m.end(), t, quoted))
    first = next((k for k, x in enumerate(toks) if not x[2].isdigit()), -1)
    named: list[bool] = []
    for k, (a, b, t, q) in enumerate(toks):
        low = t.lower()
        if t.isdigit() or low in _ENT_STOP or _MONTH_WORD_RE.fullmatch(t):
            named.append(False)
            continue
        latin = bool(re.search(r"[A-Za-z]", t)) and len(t) >= 2
        cap = t[:1].isupper() and len(t) >= 3
        initial = k == first or bool(re.search(r"(?:^|[—–:])\s*$", text[:a]))  # «1998 год — Запуск …»: after the date
        # a quoted name goes on to its closing quote («Москвич 3е», «Мой мир»): its model number is part of it
        in_name = q and k > 0 and named and named[-1] and toks[k - 1][3] and not text[toks[k - 1][1]:a].strip(" -")
        if latin or (cap and q) or (cap and (not initial or cap_mid(t))) or (in_name and re.match(r"^\d+[а-яёa-z]{0,3}$", low)):
            named.append(True)
        else:
            named.append(False)
    out: list[_Ent] = []
    k = 0
    while k < len(toks):
        if not named[k]:
            k += 1
            continue
        j = k
        while j + 1 < len(toks) and named[j + 1] and not (text[toks[j][1]:toks[j + 1][0]].strip(" -")):
            j += 1
        prefs = tuple(_prefix(toks[x][2]) for x in range(k, j + 1))
        if j > k and phrase is not None and not phrase(prefs):
            # «В Азии Япония…»: two names side by side, not one
            for x in range(k, j + 1):
                out.append(_Ent(toks[x][2], toks[x][0], toks[x][1], (_prefix(toks[x][2]),)))
        else:
            out.append(_Ent(text[toks[k][0]:toks[j][1]], toks[k][0], toks[j][1], prefs))
        k = j + 1
    return out


_PAREN_RE = re.compile(r"\s*\([^()]*\)")
_CLAUSE_SPLIT_RE = re.compile(r";\s+|,\s+(?:а|но|однако)\s+(?:также\s+)?")
_LEAD_DATE_RE = re.compile(
    r"^(?:(?:[ВвСсКк]|До|После|По\s+итогам)\s+)?(?:(?:начале|конце|середине)\s+)?(?:\d{1,2}\s+)?"
    r"(?:(?:январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*\s+)?"
    r"(?:1\d{3}|20\d{2})(?:\s*[—–-]\s*(?:1\d{3}|20\d{2}))?\s*(?:года|году|годах|годов|г\.)?,?\s+"
)
REWRITE_MAX_WORDS = 32


def clean_article_sentence(t: str) -> str:
    """An article's sentence fit for a slide: no brackets, no footnote marks, no list label in front («Стоимость: по
    состоянию на 2025 год…»), one space, a full stop."""
    t = re.sub(r"\[\d+\]", "", t or "")
    t = re.sub(r"^\s*[А-ЯЁA-Z][^.:;!?]{0,28}:\s+(?=\S)", "", t)
    prev = None
    while prev != t:
        prev, t = t, _PAREN_RE.sub("", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(t.split())).strip(" ,;:—–-")
    return _sentence(H.cap_first(t)) if t else ""


def article_clause(sentence: str, prefs: Iterable[str] = (), want_year: bool = False, max_words: int = REWRITE_MAX_WORDS) -> Optional[str]:
    """The article's sentence (clean_article_sentence) when it has at most `max_words` words, else its clause that names
    the entity (`prefs`) — «…, а компания АвтоВАЗ сообщила о первой продаже электромобиля e-Largus…» — with the
    sentence's date in front when the clause has none («В феврале 2025 года компания АвтоВАЗ сообщила…»). None for a
    heading, a sentence that leans on the one before it, a long quotation, or a clause of fewer than 5 words."""
    from verstka.planning.reference import drop_quotations

    s = clean_article_sentence(sentence)
    if not s or len(s.split()) < 5 or anaphoric(s) or drop_quotations(s).strip() != s.strip():
        return None
    has_year = bool(_year_spans(s))
    if len(s.split()) <= max_words and (has_year or not want_year):
        return s
    prefs = [p for p in prefs if p]
    body = s.rstrip(".")
    parts = [p.strip(" ,") for p in _CLAUSE_SPLIT_RE.split(body) if p.strip(" ,")]
    if len(parts) < 2:
        return None
    lead = _LEAD_DATE_RE.match(body)
    pick = None
    for k, p in enumerate(parts):
        low = p.lower().replace("ё", "е")
        if prefs and not all(re.search(r"(?<![\wё])" + re.escape(x), low) for x in prefs):
            continue
        pick = (k, p)
        break
    if pick is None:
        return None
    k, p = pick
    if k > 0 and lead and not _year_spans(p):
        p = lead.group(0).rstrip(", ") + " " + (p[:1].lower() + p[1:] if not _keeps_capital(p) else p)
    out = _sentence(H.cap_first(p))
    n = len(out.split())
    if n < 5 or n > max_words or anaphoric(out) or (want_year and not _year_spans(out)):
        return None
    return out


def _keeps_capital(clause: str) -> bool:
    w = (clause.split() or [""])[0]
    return bool(re.search(r"[A-Z]", w)) or w.isupper() or (w[:1].isupper() and len(w) > 1 and not w[1:].islower())


_YEAR_ADVERB_RE_T = (
    r"(?:^|(?<=[\s,]))\s*(?:[Вв]|[Кк]|[Сс]|[Пп]о\s+состоянию\s+на)\s+(?:(?:начале|конце|середине)\s+)?"
    r"(?:(?:\d{{1,2}}\s+)?(?:январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*\s+)?"
    r"{y}(?:\s*(?:года|году|год|г\.)|(?!\s*(?:года|году|год|г\.)))(?:,\s*|\s+|(?=[.!?;:]|$))"
)


def cut_year(text: str, year: int) -> Optional[str]:
    """The statement without the phrase that dates it with `year` («В 1998 году Дмитрий Андрианов добавил…» →
    «Дмитрий Андрианов добавил…»); None when the year is not in such a phrase or too little is left."""
    rx = re.compile(_YEAR_ADVERB_RE_T.format(y=year))
    m = rx.search(text)
    if not m:
        return None
    out = (text[: m.start()] + " " + text[m.end():]).strip()
    out = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(out.split())).strip(" ,")
    if m.start() == 0 or not text[: m.start()].strip():
        out = H.cap_first(out)
    if len(out.split()) < 4 or str(year) in out:
        return None
    return _sentence(out)


def cut_thing_year(text: str, year: int) -> Optional[str]:
    """The statement without a year that dates a named thing («…условиями Версальского договора 1919 года» → «…условиями
    Версальского договора»): a genitive year or a year in brackets right after a word, never an event's date."""
    m = re.search(rf"(?<=[А-Яа-яЁёA-Za-z»])\s*(?:\(\s*{year}\s*(?:г\.|года)?\s*\)|\s{year}\s*(?:года|г\.))(?![\wё])", text)
    if not m or _DATING_PREV_RE.search(text[: m.start()]):
        return None
    out = re.sub(r"\s+([,.;:!?)])", r"\1", " ".join((text[: m.start()] + text[m.end():]).split()))
    return _sentence(out) if len(out.split()) >= 4 and str(year) not in out else None


def cut_apposition(text: str, e: Optional[_Ent]) -> Optional[str]:
    """The statement without the phrase that names the entity «как …» / «под названием …» («VK была основана в 1998
    году как компания Digital Sky Technologies» → «VK была основана в 1998 году»); None when it is not such a phrase."""
    if e is None:
        return None
    m = re.search(r"[,\s]+(?:как|под\s+(?:кодовым\s+)?(?:названием|наименованием|именем)|в\s+качестве)\s+(?:компани\w+\s+|фонд\w*\s+|организаци\w+\s+)?«?$", text[: e.start])
    if not m:
        return None
    rest = text[e.end:]
    stop = re.search(r"[,;.!?]", rest)
    tail = rest[stop.start():] if stop else ""
    out = (text[: m.start()] + tail).strip()
    out = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(out.split())).strip(" ,")
    return _sentence(out) if len(out.split()) >= 4 else None


def _supported_or_none(text: Optional[str], support: ArticleSupport) -> Optional[str]:
    """A statement left after its wrong year was cut, when the article states the rest (a wrong year often dates a wrong
    event: «В 2006 году компания запустила «ВКонтакте»» — it did not, DST bought into it in 2007)."""
    return text if text and support.supported(text) else None


def _repair(sn: str, p: _Pairing, support: ArticleSupport) -> Optional[str]:
    """A statement the pairing check caught, repaired in the article's words or by cutting the wrong part: a former
    name told as the founding one or a year the article gives another name — the «как …» phrase cut, else the
    article's own sentence (clause) of the event, else the year's phrase cut; an event the article does not date — its
    year's phrase cut; a tense or a direction — the article's sentence. None: the statement goes."""
    ent = p.entity
    if p.kind == "former":
        names = [nm.lower() for nm, _ in support.former]
        ent = next((e for e in _entities(sn, support._cap_mid) if any(nm.startswith(e.text.lower()[:6]) for nm in names)), None)
    tries: list[Callable[[], Optional[str]]] = []
    if p.kind == "rename":
        tries = [lambda: support.rename_fixed(sn)]
    elif p.kind == "month":
        tries = [lambda: replace_when(sn, p.fix[0], p.fix[1])]
    elif p.kind == "event":
        tries = [lambda: support.event_year_fixed(sn, p)]
    elif p.kind == "item":
        tries = [lambda: cut_list_item(sn, p.entity)]
    elif p.kind == "verb":
        def cut_all() -> Optional[str]:
            # every bought thing out of the list («запустила «ВКонтакте», «Одноклассники», «Мой мир»» → «Мой мир»)
            cur, q = sn, p
            for _ in range(4):
                nxt = cut_list_item(cur, q.entity)
                if nxt is None:
                    return None
                cur, q = nxt, support.pair_issue(nxt)
                if q is None:
                    return cur
                if q.kind != "verb":
                    return None
            return None

        tries = [cut_all]
    elif p.kind in ("founder", "place"):
        tries = [lambda: support.rewrite(p, sn)]
    elif p.kind in ("former", "year"):
        tries = [lambda: cut_apposition(sn, ent), lambda: support.rewrite(p, sn), lambda: _supported_or_none(cut_year(sn, p.year), support),
                 lambda: cut_thing_year(sn, p.year)]
    elif p.kind == "undated":
        tries = [lambda: _supported_or_none(cut_year(sn, p.year), support), lambda: cut_thing_year(sn, p.year), lambda: cut_apposition(sn, ent)]
    else:
        tries = [lambda: support.rewrite(p, sn)]
    for t in tries:
        new = t()
        if new and new != sn and support.pair_issue(new) is None:
            return new
    return None


def fix_pairings(
    deck: _Deck, support: ArticleSupport, removed: Optional[list[dict]] = None, edits: Optional[list[dict]] = None, first: int = 1,
) -> int:
    """Every written statement whose years, tense or direction the article pairs otherwise (ArticleSupport.pair_issue):
    repaired in the article's words or by cutting the wrong part (`edits`), else removed (a sentence that leans on it
    goes too); a timeline entry is removed. The user's theses stay. Returns how many statements were changed."""
    from verstka.planning.agent import said_in, same_text

    removed = removed if removed is not None else []
    n = 0
    for i, s in enumerate(deck.slides, first):
        drop: dict[str, str] = {}
        out: list[str] = []
        for sn in s.sentences:
            if sn in s.theses:
                out.append(sn)
                continue
            p = support.pair_issue(sn)
            if p is None:
                out.append(sn)
                continue
            new = _repair(sn, p, support)
            others = [x for sl in deck.slides for x in sl.sentences if x != sn] + out
            if new and not any(same_text(new, x) or said_in(x, new, 0.75) or said_in(new, x, 0.75) for x in others):
                if edits is not None:
                    edits.append({"where": f"{i}", "text": sn, "now": new, "why": f"{p.kind}: {p.why}"})
                out.append(new)
            else:
                drop[sn] = f"{p.kind}: {p.why}"
                out.append(sn)
            n += 1
        s.sentences = out
        if drop:
            _prune(s, lambda sn, drop=drop: drop.get(sn), removed, f"{i}")
        if s.timeline:
            tl = []
            for e in s.timeline:
                line = f"{e['when']} — {e['what']}"
                p = support.pair_issue(line)
                if p is not None and p.kind == "month":
                    new_when = _date_phrase(p.fix[1], nominative=True)
                    if support.pair_issue(f"{new_when} — {e['what']}") is None:
                        if edits is not None:
                            edits.append({"where": f"{i}", "text": line, "now": f"{new_when} — {e['what']}", "why": f"month: {p.why}"})
                        tl.append({**e, "when": new_when})
                        n += 1
                        continue
                if p is not None:
                    _removed(removed, f"{i}", line, f"{p.kind}: {p.why}")
                    n += 1
                else:
                    tl.append(e)
            s.timeline = tl if len(tl) >= 3 else None
    deck.slides = [s for s in deck.slides if not s.empty or s.theses]
    return n


# the check's own words that it found nothing wrong («…which is correct, so this is not an issue»)
ACCEPT_RE = re.compile(
    r"is\s+correct|are\s+correct|not\s+an?\s+(?:issue|error|problem)|no\s+(?:issue|error|problem)|is\s+supported|is\s+accurate|"
    r"consistent\s+with|matches\s+the\s+reference|(?<![\wё])верн[оаы](?![\wё])|соответству|не\s+ошибк|подтвержда|корректн",
    re.I,
)
DEGENERATE_SHARE = 0.35  # a check that reports more than this share of the statements says nothing
DEGENERATE_MIN = 5  # … and at least this many (on a tiny text a share means nothing)


def _statements(deck: _Deck, first: int = 1) -> set[tuple[int, str, int]]:
    out = set()
    for i, s in enumerate(deck.slides, first):
        out |= {(i, "s", j) for j in range(1, len(s.sentences) + 1)}
        out |= {(i, "t", k) for k in range(1, len(s.timeline or []) + 1)}
        out |= {(i, "d", k) for k in range(1, len((s.data or {}).get("rows") or []) + 1)}
    return out


def _evidence_sentence(evidence: str, support: Optional[ArticleSupport]) -> Optional[int]:
    """The article sentence the check quoted as its evidence: most of the quote's words in one sentence (None when the
    quote is not the article's)."""
    if support is None or not (evidence or "").strip():
        return None
    from verstka.planning.grounding import content_stems

    want = {x[:5] for x in content_stems(evidence, neutral=True) if not re.match(r"^\d", x)}
    if len(want) < 3:
        return None
    best, at = 0, None
    for i, st in enumerate(support.sstems):
        k = len(want & st)
        if k > best:
            best, at = k, i
    return at if best >= max(3, int(0.7 * len(want) + 0.5)) else None


def apply_check(
    deck: _Deck, issues: list[Any], removed: Optional[list[dict]] = None, first: int = 1,
    support: Optional[ArticleSupport] = None, overruled: Optional[list[dict]] = None, edits: Optional[list[dict]] = None,
    stats: Optional[dict] = None,
) -> int:
    """The fact check's verdicts, applied so that they never do more harm than good:
    - a verdict without a reason, or whose reason says the statement is right («…which is correct», «верно»), is
      ignored; so is a verdict on an unknown id or on the user's theses;
    - an answer that reports more than DEGENERATE_SHARE of the statements is degenerate (gate 2: 17 of ~25 with empty
      reasons, ten true sentences removed): none of it is applied (`stats["degenerate"]`);
    - with `support` (the full articles), a reported statement the full article states stays (`overruled`);
    - a reported statement whose evidence (the article's words the check quotes) is an article sentence is replaced by
      that sentence (or its clause), the article's own words (`edits`); any other is removed, and a sentence right after
      it that leans on it goes too. A slide left with nothing goes. Returns how many statements were removed or
      replaced."""
    removed = removed if removed is not None else []
    stats = stats if stats is not None else {}
    known = _statements(deck, first)
    flagged: set[tuple[int, str, int]] = set()
    kill: dict[tuple[int, str, int], str] = {}
    fix_of: dict[tuple[int, str, int], int] = {}
    ignored = 0
    for it in issues:
        def get(name: str) -> str:
            return str((getattr(it, name, None) if not isinstance(it, dict) else it.get(name)) or "")

        m = _ID_RE.match(get("id"))
        if not m:
            continue
        key = (int(m.group(1)), (m.group(2) or "s").lower(), int(m.group(3)))
        if key not in known:
            continue
        flagged.add(key)
        verdict, problem, evidence = get("verdict"), " ".join(get("problem").split()), get("evidence")
        if not problem or ACCEPT_RE.search(problem):
            ignored += 1
            continue
        kill[key] = f"check: {verdict or 'issue'} — {problem[:100]}"
        at = _evidence_sentence(evidence, support)
        if at is not None:
            fix_of[key] = at
    stats.update({"statements": len(known), "flagged": len(flagged), "ignored": ignored})
    if known and len(flagged) > DEGENERATE_SHARE * len(known) and len(flagged) >= DEGENERATE_MIN:
        # the answer flags nearly everything (gate 2: 17 of 27, reasons empty): its verdicts say nothing — the full
        # article decides alone (a flagged statement it states stays, one it does not goes); without it nothing goes
        stats["degenerate"] = True
        if support is None:
            return 0
        kill = {key: "check (a degenerate answer): the full article does not state it" for key in flagged}
        fix_of = {}

    def stays(where: str, text: str, why: str) -> bool:
        if support is None or not support.supported(text):
            return False
        if overruled is not None:
            overruled.append({"where": where, "text": text, "why": why, "kept": "the full article states it"})
        return True

    from verstka.planning.agent import said_in, same_text

    n = 0
    for i, s in enumerate(deck.slides, first):
        pos: dict[str, int] = {}
        for j, sn in enumerate(s.sentences, 1):
            pos.setdefault(sn, j)
        # the article's own words first: a reported sentence the check gave the article's evidence for is replaced
        out = []
        for sn in s.sentences:
            j = pos.get(sn)
            key = (i, "s", j)
            if j and key in kill and key in fix_of and sn not in s.theses and not stays(f"{i}.{j}", sn, kill[key]):
                new = article_clause(support.sents[fix_of[key]], want_year=bool(_statement_years(sn))) if support is not None else None
                others = [x for sl in deck.slides for x in sl.sentences if x != sn] + out
                if new and not any(same_text(new, x) or said_in(x, new, 0.75) or said_in(new, x, 0.75) for x in others) and (support is None or support.pair_issue(new) is None):
                    if edits is not None:
                        edits.append({"where": f"{i}.{j}", "text": sn, "now": new, "why": kill[key]})
                    kill.pop(key)
                    out.append(new)
                    n += 1
                    continue
                kill[key] += " (kept out: the check's evidence is not an article sentence fit for a slide)"
                fix_of.pop(key, None)
            out.append(sn)
        s.sentences = out
        pos = {}
        for j, sn in enumerate(s.sentences, 1):
            pos.setdefault(sn, j)

        def why_of(sn: str, i: int = i, pos: dict = pos) -> Optional[str]:
            j = pos.get(sn)
            why = kill.get((i, "s", j)) if j else None
            if why and stays(f"{i}.{j}", sn, why):
                return None
            return why

        n += _prune(s, why_of, removed, lambda sn, i=i, pos=pos: f"{i}.{pos.get(sn, 0)}")
        if s.timeline:
            tl = []
            for k, e in enumerate(s.timeline, 1):
                why = kill.get((i, "t", k))
                line = f"{e['when']} — {e['what']}"
                if why and not stays(f"{i}.t{k}", line, why):
                    _removed(removed, f"{i}.t{k}", line, why)
                    n += 1
                else:
                    tl.append(e)
            s.timeline = tl if len(tl) >= 3 else None
        if s.data:
            rows = []
            unit = s.data.get("unit") or ""
            for k, r in enumerate(s.data.get("rows") or [], 1):
                why = kill.get((i, "d", k))
                if why and not stays(f"{i}.d{k}", f"{r['label']} — {fmt_value(r['value'])} {unit}".strip(), why):
                    _removed(removed, f"{i}.d{k}", f"{r['label']} — {fmt_value(r['value'])}", why)
                    n += 1
                else:
                    rows.append(r)
            s.data = _data_ok({**s.data, "rows": rows})
            _caption_gone(s)
    deck.slides = [s for s in deck.slides if not s.empty]
    return n


# ------------------------------------------------------------------ a figure is told once (gate 2: 62 / 80 % / 70 млн ×3)


def _figure_keys(text: str) -> set[tuple]:
    """The figures of a text that are not years or dates, as (value in full, unit class)."""
    from verstka.planning.grounding import _is_year, figures

    out = set()
    for f in figures(text or ""):
        if f.date is not None or _is_year(f):
            continue
        out.add((round(f.mag, 6), f.unit or ""))
    return out


_TOTAL_RE = re.compile(r"(?<![\wё])(?:погиб\w*|гибел\w*|потер[ьия]\w*|жертв\w*|унесл\w*)", re.I)


def _totals(text: str) -> set[tuple]:
    """The death tolls / losses a sentence gives: (value in full, unit) of every figure of it when it names one."""
    if not _TOTAL_RE.search(text or ""):
        return set()
    return {k for k in _figure_keys(text) if k[0] >= 1e5}


def dedupe_totals(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """One total of a measure per deck: a sentence that gives the war's losses as another figure than an earlier slide
    («погибло более 70 миллионов» on one slide, «около 60—65 миллионов» on the next — both the article's, gate 2) goes;
    the first one stays. The user's theses stay. Returns how many went."""
    removed = removed if removed is not None else []
    told: Optional[tuple[int, set]] = None
    n = 0
    for i, s in enumerate(deck.slides, first):
        def why_of(sn: str, i: int = i) -> Optional[str]:
            nonlocal told
            got = _totals(sn)
            if not got:
                return None
            if told is None:
                told = (i, got)
                return None
            if got & told[1]:
                return None
            return f"another total than slide {told[0]} gives"

        n += _prune(s, why_of, removed, f"{i}")
    deck.slides = [s for s in deck.slides if not s.empty or s.theses]
    return n


def dedupe_figures(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """A figure is told on one slide: a sentence whose every figure (not a year, not a date) an earlier slide already
    gives goes; the summing-up slide may restate one such sentence. The user's theses stay. Returns how many went."""
    removed = removed if removed is not None else []
    told: dict[tuple, int] = {}
    n = 0
    for i, s in enumerate(deck.slides, first):
        summary = bool(SUMMARY_TITLE_RE.match(s.title or ""))
        allowed = [1 if summary else 0]

        def why_of(sn: str, i: int = i, allowed: list = allowed) -> Optional[str]:
            keys = _figure_keys(sn)
            if not keys:
                return None
            earlier = {told[k] for k in keys if k in told and told[k] < i}
            if len(earlier) and all(k in told and told[k] < i for k in keys):
                if allowed[0] > 0:
                    allowed[0] -= 1
                    return None
                return f"repeats the figures of slide {min(earlier)}"
            return None

        n += _prune(s, why_of, removed, f"{i}")
        for sn in s.sentences:
            for k in _figure_keys(sn):
                told.setdefault(k, i)
    deck.slides = [s for s in deck.slides if not s.empty or s.theses]
    return n


# ------------------------------------------------------------------ the living politician's neutral biography (§6.4)

POLITICIAN_TITLE_RE = re.compile(r"политик|отношени|конфликт|войн|критик|оценк|санкци|реформ|рейтинг|скандал", re.I)
POLITICIAN_LEXICON = re.compile(
    r"вторжени|аннекси|агресси|диктатур|авторитар|путинизм|ордер|арест|уголовн\w+\s+суд|санкци|оккупир|репресси|"
    r"пропаганд|цензур|оппозици|протест|коррупц|фальсификац|украин|крым|донбасс|военн\w+\s+(?:операци|вмешательств|контрол)|"
    r"конфронтац|критик|обвин|скандал|убийств|отравлен|политзаключ|иноагент|экстремист",
    re.I,
)


def guard_politician(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """A living politician: the biography only (the owner's «neutral biography»). A slide about politics, relations,
    conflicts, criticism or ratings goes; so does every sentence and timeline entry of the lexicon (wars, annexations,
    courts, sanctions, assessments). Returns how many statements were removed."""
    removed = removed if removed is not None else []
    n = 0
    keep_slides = []
    for i, s in enumerate(deck.slides, first):
        if POLITICIAN_TITLE_RE.search(s.title or "") and not s.theses:
            for sn in s.sentences:
                _removed(removed, f"{i}", sn, "politician: not biography")
            n += len(s.sentences) + len(s.timeline or []) + len((s.data or {}).get("rows") or [])
            continue
        n += _prune(s, lambda sn: "politician: not biography" if POLITICIAN_LEXICON.search(sn) else None, removed, f"{i}")
        if s.timeline:
            tl = []
            for e in s.timeline:
                line = f"{e['when']} — {e['what']}"
                if POLITICIAN_LEXICON.search(line):
                    _removed(removed, f"{i}", line, "politician: not biography")
                    n += 1
                else:
                    tl.append(e)
            s.timeline = tl if len(tl) >= 3 else None
        if not s.empty:
            keep_slides.append(s)
    deck.slides = keep_slides
    return n


# ------------------------------------------------------------------ a company: no slide about criticism (spec L2)

COMPANY_LEXICON = re.compile(
    r"санкц|(?<![\wё])суд(?:а|у|ом|е|ы|ов|ам|ами|ах|ебн\w*)?(?![\wё])|штраф|блокир|иск(?:а|у|ом|и|ов)?\s+(?:к|против|о)\s|"
    r"удал[её]н\w*(?:\s+\S+){0,3}?\s+из\s+(?:App\s*Store|Google\s*Play|магазин)|(?:App\s*Store|Google\s*Play)\W+(?:удал|недоступ)|"
    r"недоступн\w*\s+в\s+(?:App\s*Store|Google\s*Play)|скандал|уголовн|"
    # layoffs and the gossip around them, a ranking of losses (a company's history is not its troubles' chronicle)
    r"увольн\w*|уволить|уволил\w*|покинули\s+несколько|сокращени\w+\s+(?:сотрудник|персонал|штат)|не\s+проводит\s+никаких|"
    r"самых\s+убыточных",
    re.I,
)


def guard_company(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """A company's history is not a slide about criticism (spec L2): sanctions, courts, fines, blockings, the apps
    removed from the stores stay out of the sentences — out of the summary slide and of every sentence a designer may
    make a headline of — and at most one chronology line keeps the fact (the first). The user's theses stay. Returns
    how many statements were removed."""
    removed = removed if removed is not None else []
    n = 0
    kept_line = False
    for i, s in enumerate(deck.slides, first):
        n += _prune(s, lambda sn: "company: not about criticism" if COMPANY_LEXICON.search(sn) else None, removed, f"{i}")
        if s.timeline:
            tl = []
            for e in s.timeline:
                line = f"{e['when']} — {e['what']}"
                if COMPANY_LEXICON.search(line) and kept_line:
                    _removed(removed, f"{i}", line, "company: one chronology line is enough")
                    n += 1
                    continue
                kept_line = kept_line or bool(COMPANY_LEXICON.search(line))
                tl.append(e)
            s.timeline = tl if len(tl) >= 3 else None
    deck.slides = [s for s in deck.slides if not s.empty]
    return n


# ------------------------------------------------------------------ the chronology is the one dated list (G1-11)

CHRONOLOGY_TITLE_RE = re.compile(r"хронолог|ключев\w*\s+дат|основн\w*\s+дат|главн\w*\s+дат|летопис|даты", re.I)


def _date_keys(text: str, context: str = "") -> tuple[set[tuple], set[int]]:
    """(the full dates, the years) a text writes: «1 сентября 1939 года» → (1, 9, 1939); «в 1998 году» → 1998; a day of
    a month without its year («3 сентября Великобритания…») takes each year its `context` (the slide's text) writes."""
    from verstka.planning.grounding import _is_year, figures

    dates: set[tuple] = set()
    years: set[int] = set()
    bare: list[tuple] = []
    for f in figures(text or ""):
        if f.date is not None and f.date[2]:
            dates.add(f.date)
        elif f.date is not None:
            bare.append(f.date)
        elif _is_year(f):
            years.add(int(f.value))
    for m in re.finditer(r"(?<![\d.,])(1\d{3}|20\d{2})(?![\d.,])", text or ""):
        years.add(int(m.group(1)))
    if bare:
        ctx_years = {int(m.group(1)) for m in re.finditer(r"(?<![\d.,])(1\d{3}|20\d{2})(?![\d.,])", f"{text} {context}")}
        dates |= {(d, mo, y) for d, mo, _ in bare for y in ctx_years}
    return dates, years


def _stems5(text: str) -> set[str]:
    from verstka.planning.grounding import content_stems

    return {x[:5] for x in content_stems(text or "", neutral=True) if not re.match(r"^\d", x)}


def _tells(entry: dict, text: str, context: str = "") -> bool:
    """The text tells the timeline entry: the same full date, or the same year and a content word of the event."""
    when, what = entry.get("when") or "", entry.get("what") or ""
    ed, ey = _date_keys(when)
    td, ty = _date_keys(text, context)
    if ed:
        return bool(ed & td)
    if not ey or not (ey & (ty | {d[2] for d in td})):
        return False
    return bool(_stems5(what) & _stems5(text))


def _slide_tells(entry: dict, s: "_Slide") -> bool:
    context = " ".join(s.sentences)
    return any(_tells(entry, x, context) for x in s.sentences) or any(_tells(entry, f"{x['when']} — {x['what']}") for x in s.timeline or [])


def _dated(s: "_Slide") -> bool:
    return any(any(_date_keys(x)) for x in s.sentences)


def dedupe_chronology(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1, short: bool = False) -> int:
    """The chronology is the deck's one dated list, over the whole story: of its entries that an earlier slide already
    tells (in a sentence or in its own timeline), only the first per slide stays («1, 3, 17 сентября 1939» of the
    slide «Начало» is not the first half of the chronology again) — the first and the last entry always, at least 4
    entries (3 of a shorter one); and the summing-up
    slide restates at most one of its entries (not the chronology once more in sentences). Returns how many went."""
    removed = removed if removed is not None else []
    tl_slides = [k for k, s in enumerate(deck.slides) if s.timeline]
    if not tl_slides:
        return 0
    named = [k for k in tl_slides if CHRONOLOGY_TITLE_RE.search(deck.slides[k].title or "")]
    k = (named or tl_slides)[-1]
    chron = deck.slides[k]
    entries = list(chron.timeline or [])
    n = 0
    if short:
        # a deck of ≤ 10 slides (gate 2: «Хронология» told the dates of three slides again): a chronology slide goes
        # when ≥ 3 narrative slides carry dates; any other timeline keeps only the events no other slide dates
        others = [j for j in range(len(deck.slides)) if j != k]
        if named and sum(1 for j in others if _dated(deck.slides[j])) >= 3:
            for e in entries:
                _removed(removed, f"{k + first}", f"{e['when']} — {e['what']}", "a short deck: its narrative slides carry the dates")
            n += len(entries)
            chron.timeline = None
            if len(chron.sentences) <= 1 and not chron.data and not chron.theses:
                for sn in chron.sentences:
                    _removed(removed, f"{k + first}", sn, "a short deck: the chronology slide goes")
                n += len(chron.sentences)
                chron.sentences = []
        else:
            keep_e = [e for e in entries if not any(_slide_tells(e, deck.slides[j]) for j in others)]
            for e in entries:
                if e not in keep_e:
                    _removed(removed, f"{k + first}", f"{e['when']} — {e['what']}", "another slide dates it (a short deck)")
                    n += 1
            chron.timeline = keep_e if len(keep_e) >= 3 else None
        deck.slides = [s for s in deck.slides if not s.empty]
        return n
    keep: list[int] = []
    dropped: list[tuple[int, int]] = []  # (entry index, the slide that tells it)
    used: set[int] = set()
    for ei, e in enumerate(entries):
        told = next((j for j in range(k) if _slide_tells(e, deck.slides[j])), None)
        if told is None or told not in used or ei in (0, len(entries) - 1):
            # the first and the last entry stay whatever tells them: the chronology spans the whole story
            keep.append(ei)
            if told is not None:
                used.add(told)
        else:
            dropped.append((ei, told))
    least = 4 if len(entries) >= 5 else 3
    while len(keep) < least and dropped:
        # a chronology of fewer than 4 (3) entries says too little: the dropped entry farthest from the kept ones (the
        # later one of a tie) comes back — the list spreads over the story
        back = max(dropped, key=lambda d: (min(abs(d[0] - x) for x in keep) if keep else 0, d[0]))
        dropped.remove(back)
        keep.append(back[0])
    keep.sort()
    for ei, told in dropped:
        e = entries[ei]
        _removed(removed, f"{k + first}", f"{e['when']} — {e['what']}", f"repeats slide {told + first} (the chronology tells each slide once)")
        n += 1
    chron.timeline = [entries[ei] for ei in keep]
    # the summing-up slide: at most one sentence that restates the chronology
    for i, s in enumerate(deck.slides, first):
        if s is chron or not SUMMARY_TITLE_RE.match(s.title or ""):
            continue
        said = [False]
        context = " ".join(s.sentences)

        def why_of(sn: str, said: list = said, context: str = context) -> Optional[str]:
            if not any(_tells(e, sn, context) for e in entries):
                return None
            if said[0]:
                return "restates the chronology"
            said[0] = True
            return None

        n += _prune(s, why_of, removed, f"{i}")
    deck.slides = [s for s in deck.slides if not s.empty]
    return n


def dedupe_events(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """An event told on two slides (gate 2: the refill's «Перелом на Восточном фронте» told the Stalingrad
    counteroffensive of «Переломные события» again): a later slide's sentence with a full date (day, month, year) of an
    earlier slide's sentence and two of its words, or three quarters of whose words one earlier sentence has, goes; the
    summing-up slide restates by design. The user's theses stay. Returns how many went."""
    from verstka.planning.agent import said_in

    removed = removed if removed is not None else []
    seen: list[tuple[int, set, set, str]] = []
    n = 0
    for i, s in enumerate(deck.slides, first):
        context = " ".join(s.sentences)
        summary = bool(SUMMARY_TITLE_RE.match(s.title or ""))

        def why_of(sn: str, i: int = i, context: str = context, summary: bool = summary) -> Optional[str]:
            if summary:
                return None
            full, _ = _date_keys(sn, context)
            st = _stems5(sn)
            for j, d0, st0, text0 in seen:
                if j >= i:
                    continue
                if full and d0 & full and len(st & st0) >= 2:
                    return f"the event of slide {j} again"
                if len(sn.split()) >= 5 and said_in(sn, text0, 0.75):
                    return f"says slide {j}'s sentence again"
            return None

        n += _prune(s, why_of, removed, f"{i}")
        for sn in s.sentences:
            seen.append((i, _date_keys(sn, context)[0], _stems5(sn), sn))
    deck.slides = [s for s in deck.slides if not s.empty or s.theses]
    return n


# ------------------------------------------------------------------ a sentence left without its subject

_ORPHAN_RE = re.compile(r"^(?:Он|Она|Оно|Они|Его|Её|Ее|Их|Ему|Ей|Им|Него|Неё|Них)(?![\wё])")


def drop_orphans(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """A slide's text never starts with a personal pronoun («Он происходит в хлоропластах») — its subject was in a
    sentence the checks removed (or on another slide): the sentence goes (deletion only, never rewritten)."""
    removed = removed if removed is not None else []
    n = 0
    for i, s in enumerate(deck.slides, first):
        while s.sentences and s.sentences[0] not in s.theses and (_ORPHAN_RE.match(s.sentences[0].strip()) or _PRONOUN_SUBJECT_RE.match(s.sentences[0].strip())):
            _removed(removed, f"{i}", s.sentences.pop(0), "no subject (a pronoun opens the slide)")
            n += 1
        if s.sentences and s.sentences[0] not in s.theses:
            s.sentences[0] = unlinked(s.sentences[0])
    deck.slides = [s for s in deck.slides if not s.empty]
    return n


# ------------------------------------------------------------------ the written text (§7)

CHART_RU = {"column": "столбчатая", "bar": "столбчатая", "line": "линейная", "pie": "круговая"}
RULES_LINE = "Тон нейтральный, энциклопедический. Заголовки — факты из текста, без оценок."


def _sentence(t: str) -> str:
    t = " ".join((t or "").split()).strip()
    return t if not t or t.endswith((".", "!", "?", "…")) else t + "."


def render_text(deck: _Deck, rules: bool = False) -> str:
    """The written text as the analyst reads it best: «Слайд 1. Титульный / Название / Подзаголовок», «Слайд N.
    Заголовок» + sentences, a «Хронология:» dash list, a data dash list with its chart request and «данные
    приблизительные»; `rules`: a closing line of rules (neutral tone, factual headings) — in the brief handed to the
    agent only, never in the text the person sees and edits (writer.md, «Показать текст»)."""
    out = ["Слайд 1. Титульный", f"Название: «{H.strip_end(deck.title)}»."]
    if deck.subtitle.strip():
        out.append(f"Подзаголовок: «{H.strip_end(deck.subtitle)}».")
    for n, s in enumerate(deck.slides, 2):
        out += ["", f"Слайд {n}. {s.title or 'Главное'}"]
        if s.sentences:
            out.append(" ".join(_sentence(x) for x in s.sentences))
        tl = s.timeline or []
        if tl:
            out.append("Хронология:")
            out += [f"— {H.strip_end(e['when'])} — {H.cap_first(H.strip_end(e['what']))}{';' if k < len(tl) - 1 else '.'}" for k, e in enumerate(tl)]
        d = s.data
        if d:
            cap = H.strip_end(d.get("caption") or "") or "Данные"
            unit = H.strip_end(d.get("unit") or "")
            out.append(f"{cap}, {unit}:" if unit else f"{cap}:")
            rows = d["rows"]
            out += [f"— {r['label']} — {fmt_value(r['value'])}{';' if k < len(rows) - 1 else '.'}" for k, r in enumerate(rows)]
            out.append(f"Нужна {CHART_RU.get(d.get('chart') or 'column', 'столбчатая')} диаграмма: {cap[:1].lower() + cap[1:]}.")
            out.append("Укажи, что данные приблизительные.")
    if rules:
        out += ["", RULES_LINE]
    return "\n".join(out) + "\n"


_WRITTEN_RE = re.compile(r"^\s*Слайд\s+1\.\s+Титульный\s*\n\s*Название:\s*«")


def is_written_text(text: str) -> bool:
    """The brief is the agent's written text (writer mode) as the agent reads it (with the rules line)."""
    t = text or ""
    return bool(_WRITTEN_RE.match(t)) and RULES_LINE in t


def with_rules(text: str) -> str:
    """A written text (the agent's, as it is shown or as the person edited it — «Изменить») with the closing rules line
    the agent reads; any other text as it is."""
    t = text or ""
    if not _WRITTEN_RE.match(t) or RULES_LINE in t:
        return t
    return t.rstrip("\n") + "\n\n" + RULES_LINE + "\n"


# ------------------------------------------------------------------ the result


@dataclass
class WriterResult:
    mode: str
    status: str = "skipped"  # written | private | refused | failed | skipped
    topic: str = ""
    theses: list[str] = field(default_factory=list)
    kind: str = "other"
    reason: str = ""  # why not written (plain, for the log): «no_time», «disabled», the model's error
    text: str = ""
    brief: Optional[Brief] = None
    title: str = ""
    slides: int = 0  # content slides written (the deck has slides + 1 with the cover)
    asked: int = 0  # the slide count the person chose (cover included)
    source: Optional[dict] = None  # {"title", "url"} of the main reference page
    pages: list[dict] = field(default_factory=list)
    reference_chars: int = 0
    lang: str = "ru"
    removed: list[dict] = field(default_factory=list)
    edits: list[dict] = field(default_factory=list)  # a year the article does not give, cut out of its sentence
    overruled: list[dict] = field(default_factory=list)  # what the check reported that the full article states (kept)
    check_state: Optional[str] = None  # clean | applied | degenerate (the answer flagged too much: none of it applied)
    check_stats: list[dict] = field(default_factory=list)  # per check call: statements, flagged, ignored, degenerate
    refill: dict = field(default_factory=dict)  # {"asked", "added", "topped", "parts"} of the refill call
    short_by: int = 0  # content slides fewer than asked after the checks and the refill
    checked: Optional[str] = None  # "reference" | "model" | None
    check_skipped: Optional[str] = None
    continuation: bool = False
    salvaged: bool = False
    seconds: dict[str, float] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0})
    model: Optional[str] = None
    model_label: Optional[str] = None
    answers: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    skills: dict[str, dict] = field(default_factory=dict)

    @property
    def written(self) -> bool:
        return self.status == "written" and self.brief is not None

    def meta(self, max_text: int = 8000) -> dict:
        """generation.json `writer` (what the UI reads)."""
        return {
            "mode": self.mode, "status": self.status, "kind": self.kind, "text": self.text[:max_text] if self.text else "",
            "topic": self.topic, "slides": self.slides + 1 if self.slides else 0, "asked": self.asked, "source": self.source,
            "removed": len(self.removed), "checked": self.checked, "model_label": self.model_label,
            "seconds": self.seconds.get("total", 0.0), "short_by": self.short_by,
        }

    def summary(self) -> dict:
        """run_manifest.planner.writer."""
        return {
            "mode": self.mode, "status": self.status, "kind": self.kind, "skills": self.skills, "model": self.model,
            "reference": {"source": "wikipedia", "lang": self.lang, "pages": self.pages} if self.pages else None,
            "slides": self.slides, "asked": self.asked, "removed": len(self.removed), "checked": self.checked,
            "continuation": self.continuation, "seconds": self.seconds, "tokens": self.tokens, "reason": self.reason or None,
        }

    def record(self) -> dict:
        """runs/<id>/writer.json: the answers as written, the reference pages with their revisions, what was removed."""
        return {
            "version": 1, "mode": self.mode, "status": self.status, "kind": self.kind, "topic": self.topic, "theses": self.theses,
            "skills": self.skills, "model": self.model, "model_label": self.model_label, "seconds": self.seconds, "tokens": self.tokens,
            "reference": {"source": "wikipedia", "lang": self.lang, "pages": self.pages, "cut_chars": self.reference_chars} if self.pages else None,
            "answers": self.answers, "removed": self.removed, "edits": self.edits, "overruled": self.overruled, "continuation": self.continuation, "salvaged": self.salvaged,
            "check": self.check_state, "check_stats": self.check_stats, "refill": self.refill or None, "short_by": self.short_by,
            "checked": self.checked, "check_skipped": self.check_skipped, "reason": self.reason or None, "warnings": self.warnings,
        }

    def write_files(self, out_dir: Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.text:
            (out_dir / "writer.md").write_text(self.text, encoding="utf-8")
        (out_dir / "writer.json").write_text(json.dumps(self.record(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def attribution(res: WriterResult) -> str:
    """The cover's notes line naming the source (no digits in it: the figures check never sees a number)."""
    src = (res.source or {}).get("title") or ""
    if src and not re.search(r"\d", src):
        return f"Текст написан агентом Verstka по статье «{src}» из Википедии (лицензия CC BY-SA). Проверьте факты перед выступлением."
    if src:
        return "Текст написан агентом Verstka по статье из Википедии (лицензия CC BY-SA). Проверьте факты перед выступлением."
    topic = H.strip_end(" ".join(res.topic.split()))
    if topic and not re.search(r"\d", topic) and len(topic) <= 80:
        return f"Текст написан агентом Verstka по теме «{topic}». Проверьте факты перед выступлением."
    return "Текст написан агентом Verstka по теме презентации. Проверьте факты перед выступлением."


# ------------------------------------------------------------------ the writer phase


def _complete(provider: Any, messages: list, *, label: str, temperature: float, max_tokens: int, deadline: Optional[float]) -> Any:
    kw: dict[str, Any] = {"schema": None, "temperature": temperature, "max_tokens": max_tokens, "deadline": deadline}
    if getattr(type(provider), "labels_calls", False):
        kw["skill"] = label  # the recorder counts the call under the skill's answer (run_manifest by_skill)
    return provider.complete(messages, **kw)


def _short(text: str, n: int = 120) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(" ,;:—–-") + "…"


def _titles_list(titles: list[str], k: int = 6) -> str:
    shown = [f"«{t}»" for t in titles[:k] if t]
    return ", ".join(shown) + ("…" if len(titles) > k else "")


def _count_ru(n: int, one: str, few: str, many: str) -> str:
    from verstka.ru import ru_count

    return ru_count(n, one, few, many)


# ------------------------------------------------------------------ the refill (the asked slide count is a promise)

REFILL_MIN_S = 18.0  # a refill call starts only with this much writer time left
REFILL_MAX_TOP = 3  # at most this many one-sentence slides topped up per call
REFILL_REF_CHARS = 9000


def _thin(s: _Slide) -> bool:
    """A slide of one sentence (no timeline, no chart, no thesis of the user; not the summing-up slide)."""
    return len(s.sentences) <= 1 and not s.timeline and not s.data and not s.theses and not SUMMARY_TITLE_RE.match(s.title or "")


def _ref_limit(rcfg: dict, kind: Optional[str]) -> int:
    """What the writer reads of the article(s): more for a history (its subsections' openings carry the turning
    points — reference.DEEP_KINDS)."""
    from verstka.planning.reference import DEEP_KINDS

    if kind in DEEP_KINDS:
        return int(rcfg.get("max_chars_history", 18000))
    return int(rcfg.get("max_chars", 12000))


def _insert_at(deck: _Deck, part: int) -> int:
    """Where a refilled slide of storyline part `part` goes: before the first slide of a later part; a part of its own
    (−1) before the summing-up slide at the end."""
    if part >= 0:
        k = next((j for j, s in enumerate(deck.slides) if s.part > part), None)
        if k is not None:
            return k
    if deck.slides and SUMMARY_TITLE_RE.match(deck.slides[-1].title or "") and not (part >= 0 and deck.slides[-1].part >= 0 and deck.slides[-1].part < part):
        return len(deck.slides) - 1
    return len(deck.slides)


def _refill(
    deck: _Deck, parts: list[_Part], target: int, skills: Any, provider: Any, variables: Callable[..., dict], temperature: float,
    deadline: float, topic: str, ref_text: str, full: list[str], mode: WriterMode, removed: list[dict], *,
    usage: Callable[[Any], None], keep_raw: Callable[..., None], answers: list[str], checks: Callable[[_Deck], Any],
    model_check: Optional[Callable[[_Deck, str], Any]] = None, check_time: Callable[[], bool] = lambda: False,
    focus: Optional[str] = None,
) -> dict:
    """One continuation call that writes the slides the checks emptied or dropped (their storyline parts, from the
    article sections the deck does not use yet — reference.fresh_cut — with the facts already told listed) and tops up
    the slides left with one sentence; the new text goes through the same checks (the deterministic ones, and the
    model's when there is time) before it joins the deck. Returns {"asked", "added", "topped"}."""
    from verstka.planning.agent import same_text
    from verstka.planning.reference import fresh_cut

    present = {s.part for s in deck.slides if s.part >= 0}
    missing = max(0, target - len(deck.slides))
    free = [i for i in range(len(parts)) if i not in present and not parts[i].timeline]
    story: list[_Part] = []
    req: list[tuple[str, Any]] = []
    for i in free[:missing]:
        before = [s for s in deck.slides if 0 <= s.part < i]
        after = [s for s in deck.slides if s.part > i]
        where = []
        if before:
            where.append(f"after «{before[-1].title}»")
        if after:
            where.append(f"before «{after[0].title}»")
        hint = (parts[i].hint + "; " if parts[i].hint else "") + (
            f"it goes {' and '.join(where)} and tells what the reference says happened between them — none of their events" if where else "")
        story.append(_Part(parts[i].title, data=parts[i].data, hint=hint.strip("; ")))
        req.append(("new", i))
    for _ in range(missing - len(req)):
        story.append(_Part("Другие факты", hint="facts of the reference the deck does not tell yet"))
        req.append(("new", -1))
    for s in [s for s in deck.slides if _thin(s)][:REFILL_MAX_TOP]:
        story.append(_Part(s.title, hint="3–4 more facts about exactly this, not told yet"))
        req.append(("top", s))
    if not story:
        return {}
    told_list = [x for s in deck.slides for x in s.sentences] + [f"{e['when']} — {e['what']}" for s in deck.slides for e in s.timeline or []]
    told = "\n".join(f"— {_short(x, 150)}" for x in told_list)[:3500]
    titles = "; ".join(f"{i}. {s.title}" for i, s in enumerate(deck.slides, 1))
    want = " ".join(f"{p.title} {p.hint}" for p in story)
    ref = (fresh_cut(full, " ".join(told_list), limit=REFILL_REF_CHARS, want=want, focus=focus) if full else "") or ref_text
    v = variables(len(story), story, titles, first_number=len(deck.slides) + 1)
    v.update({"refill": True, "told": told or "—", "reference": ref})
    msgs = skills.build_messages("deck_writer", v)
    r = _complete(provider, msgs, label="WriterAnswer", temperature=temperature, max_tokens=min(4000, 600 + 300 * len(story)), deadline=deadline)
    usage(r)
    keep_raw("deck_writer", r)
    answers.append(r.text or "")
    out = {"asked": len(story), "added": 0, "topped": 0, "parts": [p.title for p in story]}
    more, _ = parse_answer(r.text or "")
    if more is None or more.status != "ok" or not more.slides:
        return out
    sub = normalise_answer(more, topic, ref, [], mode.language, removed, first=len(deck.slides) + 1)
    sub.slides = [s for s in sub.slides if 0 <= s.part < len(req)]
    checks(sub)
    if model_check is not None and sub.slides and check_time():
        try:
            model_check(sub, ref)
        except Exception:  # noqa: BLE001 - the refill keeps what the deterministic checks let through
            log.debug("refill check failed", exc_info=True)
    have = [x for s in deck.slides for x in s.sentences]
    for s in sub.slides:
        what, arg = req[s.part]
        s.sentences = [x for x in s.sentences if not any(same_text(x, y) for y in have)]
        if what == "top":
            old = arg
            add = [x for x in s.sentences if not anaphoric(x)][:4]
            if old in deck.slides and add:
                # the story in time order: the slide's own sentence after the new ones when it tells a later year
                mine = [y[2] for x in old.sentences for y in _statement_years(x)]
                theirs = [y[2] for x in add for y in _statement_years(x)]
                later = bool(mine and theirs and min(mine) > max(theirs))
                old.sentences = add + old.sentences if later and not old.theses else old.sentences + add
                have.extend(add)
                out["topped"] += 1
            continue
        if len(deck.slides) >= target or (len(s.sentences) < 2 and not s.timeline and not s.data):
            continue
        s.part = arg
        deck.slides.insert(_insert_at(deck, arg), s)
        have.extend(s.sentences)
        out["added"] += 1
    return out


def write_deck(
    brief: Brief,
    mode: WriterMode,
    skills: Any,
    providers: Any,
    *,
    budget_end: Optional[float] = None,
    progress: Optional[EventFn] = None,
    raw: Optional[list] = None,
    cache_dir: Optional[Path] = None,
    config: Optional[dict] = None,
    transport: Any = None,
) -> WriterResult:
    """The writer phase: the reference (when on), the deck's text, its checks, the new brief. Never raises: a failure
    is a result with status «failed» (the caller builds today's skeleton or the faithful deck)."""
    t0 = time.monotonic()
    cfg = config or load_config()
    res = WriterResult(mode=mode.kind, topic=mode.topic, theses=list(mode.theses), lang=mode.language)
    if skills is not None:
        try:
            res.skills = {n: {"version": skills.get(n).version, "sha256": skills.get(n).sha256[:16]} for n in SKILLS}
        except Exception:  # noqa: BLE001 - skills missing: the writer cannot run
            res.status, res.reason = "failed", "writer skills are not installed"
            res.warnings.append("deck_writer failed: writer skills are not installed")
            return res
    limits = cfg.get("limits") or {}
    reserve = float(limits.get("agent_reserve_s", AGENT_RESERVE_S))
    max_s = float(limits.get("writer_max_s", WRITER_MAX_S))
    check_left = float(limits.get("check_min_left_s", CHECK_MIN_LEFT_S))
    budget_end = budget_end if budget_end is not None else t0 + 210.0
    deadline = min(budget_end - reserve, t0 + max_s)
    lines: list[str] = []

    def emit(message: str) -> None:
        # the log line names the step («Автор: …»); the event does not (the timeline shows it under «Автор»)
        lines.append(f"Автор: {message}")
        if progress is None:
            return
        try:
            progress({"type": "agent", "step": "writer", "message": H.cap_first(message), "slide": None, "variant": None})
        except Exception:  # noqa: BLE001 - a listener never stops the deck
            log.debug("writer progress listener failed", exc_info=True)

    def finish(status: str, reason: str = "") -> WriterResult:
        res.status = status
        res.reason = reason or res.reason
        res.log_lines = lines
        res.seconds["total"] = round(time.monotonic() - t0, 2)
        return res

    def usage(r: Any) -> None:
        u = getattr(r, "usage", None)
        res.tokens["in"] += int(getattr(u, "prompt_tokens", 0) or 0)
        res.tokens["out"] += int(getattr(u, "completion_tokens", 0) or 0)
        res.model = res.model or getattr(r, "model", None)
        res.model_label = res.model_label or getattr(r, "label", None) or getattr(r, "model", None)

    def keep_raw(step: str, r: Any = None, error: Optional[BaseException] = None) -> None:
        if raw is None:
            return
        e: dict[str, Any] = {"step": "writer", "skill": step}
        if r is not None:
            e.update({"model": getattr(r, "model", None), "label": getattr(r, "label", None), "text": getattr(r, "text", None)})
        else:
            from verstka.providers.status import mask

            e["error"] = mask(str(error))[:2000]
        raw.append(e)

    asked = int(brief.slide_count or DEFAULT_SLIDES)
    res.asked = asked
    if deadline - t0 < WRITER_MIN_S:
        res.warnings.append("deck_writer skipped: the model time budget is spent (not enough time left to write the text)")
        emit("не хватает времени написать текст — соберу каркас по теме.")
        return finish("skipped", "no_time")
    provider = None
    try:
        provider = providers.get("llm") if providers is not None else None
    except Exception:  # noqa: BLE001
        provider = None
    if provider is None or skills is None:
        res.warnings.append("deck_writer skipped: no LLM provider")
        return finish("skipped", "no_model")
    temperature = float(cfg.get("temperature", 0.3))
    rcfg = cfg.get("reference") or {}
    ref_on = bool(rcfg.get("enabled", True)) and not mode.private_hint
    topic = mode.topic
    emit(f"ищу материалы по теме «{_short(topic, 80)}»." if ref_on else f"пишу текст по теме «{_short(topic, 80)}».")

    # 1. the topic's kind and its article titles (a tiny call — also with the reference off: the kind picks the
    # storyline, the politician's biography and the refusal), then Wikipedia when the reference is on
    kind: Optional[str] = None
    reference = None
    tr = time.monotonic()
    if not mode.private_hint:
        ref_deadline = min(deadline, tr + REFERENCE_MAX_S)
        try:
            msgs = skills.build_messages("topic_reference", {"topic": topic, "lang": mode.language})
            r = _complete(provider, msgs, label="ReferenceAnswer", temperature=0.0, max_tokens=int(skills.get("topic_reference").params.get("max_tokens", 150)), deadline=min(ref_deadline, tr + TITLES_MAX_S))
            usage(r)
            keep_raw("topic_reference", r)
            res.answers["reference"] = r.text
            from verstka.providers.openai_compat import extract_json

            ra = ReferenceAnswer.model_validate(extract_json(r.text or "", {"titles", "kind"}))
            kind = ra.kind if ra.kind in KINDS else None
            if kind == "private":
                res.kind = "private"
            elif kind == "conflict":
                res.kind = "conflict"
                res.warnings.append("deck_writer: refused (an ongoing armed conflict)")
                emit("на эту тему текст не пишу.")
                res.seconds["reference"] = round(time.monotonic() - tr, 2)
                return finish("refused", "conflict")
            elif ra.titles and ref_on:
                from verstka.planning.reference import fetch_reference

                reference = fetch_reference(
                    ra.titles, topic, lang=mode.language, contact=str(rcfg.get("contact") or ""), kind=kind,
                    limit=_ref_limit(rcfg, kind or guess_kind(topic)), timeout_s=float(rcfg.get("timeout_s", 6)), cache_dir=cache_dir,
                    cache_days=float(rcfg.get("cache_days", 7)), deadline=ref_deadline, transport=transport,
                )
                res.warnings.extend(reference.warnings)
        except Exception as e:  # noqa: BLE001 - no reference: the writer writes from knowledge
            keep_raw("topic_reference", error=e)
            res.warnings.append(f"reference: {type(e).__name__} ({str(e)[:120]})")
        res.seconds["reference"] = round(time.monotonic() - tr, 2)
        if reference is not None and reference.cut:
            res.pages = [p.meta() for p in reference.pages]
            res.source = {"title": reference.pages[0].title, "url": reference.pages[0].url}
            res.reference_chars = len(reference.cut)
            emit(f"нашёл статью «{reference.pages[0].title}» в Википедии — пишу текст по ней.")
        elif ref_on and kind != "private":
            emit("статьи по теме не нашёл — пишу по своим знаниям.")
    ref_text = reference.cut if reference is not None and reference.cut else ""
    full = reference.full_texts if reference is not None and reference.cut else []
    private_hint = mode.private_hint or kind == "private"
    # the model's kind, else (none, «other», «private» — the writer decides that one) the keywords' guess
    kind = kind if kind and kind not in ("private", "other") else guess_kind(topic)
    res.kind = res.kind if res.kind == "private" else kind

    # 2. the text: one call, a continuation when it is cut or short
    n_content = max(1, asked - 1)
    if kind == "politician":
        n_content = min(n_content, POLITICIAN_MAX_CONTENT)
    parts = storyline_parts(kind, n_content, reference=bool(ref_text))
    n_content = len(parts)
    theses = "\n".join(f"{i}. {t}" for i, t in enumerate(mode.theses, 1))
    from verstka.planning.reference import place_of

    where = place_of(topic) if kind != "politician" else None
    place = where[0] if where else ""  # «Рынок электромобилей в России»: the writer takes Russia's facts first

    def variables(n: int, story: list, written_titles: str = "", first_number: int = 2) -> dict:
        return {
            "topic": topic, "theses": theses, "private_hint": private_hint, "reference": ref_text,
            "audience": (brief.audience or "").strip() or "широкая аудитория", "language": mode.language, "n_content": n,
            "sentences": "3–4" if n_content >= 13 else "4–5", "max_data": 2 if n_content >= 6 else 1,
            "written_titles": written_titles, "first_number": first_number, "place": place,
            "storyline": "\n".join(f"{i}. {p.line}" for i, p in enumerate(story, 1)), "refill": False, "told": "",
        }

    tw = time.monotonic()
    answers: list[str] = []
    try:
        msgs = skills.build_messages("deck_writer", variables(n_content, parts))
        r = _complete(provider, msgs, label="WriterAnswer", temperature=temperature, max_tokens=min(6000, 600 + 280 * n_content), deadline=deadline)
        usage(r)
        keep_raw("deck_writer", r)
        answers.append(r.text or "")
    except Exception as e:  # noqa: BLE001 - the model did not answer: the skeleton (topic) or the faithful deck (expand)
        keep_raw("deck_writer", error=e)
        res.answers["writer"] = answers
        res.seconds["write"] = round(time.monotonic() - tw, 2)
        res.warnings.append(f"deck_writer failed: {str(e)[:300]}")
        emit("модель не ответила — соберу каркас по теме." if mode.kind == "topic" else "модель не ответила — соберу по вашему тексту.")
        return finish("failed", str(e)[:200])
    ans, salvaged = parse_answer(answers[0])
    res.salvaged = salvaged
    if ans is None:
        res.answers["writer"] = answers
        res.seconds["write"] = round(time.monotonic() - tw, 2)
        res.warnings.append("deck_writer failed: the model answer is not a deck text (invalid JSON)")
        emit("модель не написала текст — соберу каркас по теме." if mode.kind == "topic" else "модель не написала текст — соберу по вашему тексту.")
        return finish("failed", "no JSON")
    if ans.status == "private":
        res.answers["writer"] = answers
        res.seconds["write"] = round(time.monotonic() - tw, 2)
        res.warnings.append("deck_writer: private (the topic is the user's own)")
        emit("тема — о вашем проекте, факты о нём знаете только вы.")
        res.kind = "private"
        return finish("private", "private")
    if ans.status == "refuse" or (ans.kind or "").lower() == "conflict":
        res.answers["writer"] = answers
        res.seconds["write"] = round(time.monotonic() - tw, 2)
        res.warnings.append("deck_writer: refused")
        emit("на эту тему текст не пишу.")
        return finish("refused", "refuse")
    writer_kind = (ans.kind or "").lower()
    removed: list[dict] = []
    deck = normalise_answer(ans, topic, ref_text, mode.theses, mode.language, removed)
    missing = n_content - len(deck.slides)
    if missing >= 2 and deadline - time.monotonic() >= CONTINUE_MIN_S:
        titles = [s.title for s in deck.slides]
        rest_start = len(deck.slides) if len(parts) > len(deck.slides) else max(0, len(parts) - missing)
        rest = parts[rest_start:][:missing]
        try:
            msgs = skills.build_messages("deck_writer", variables(
                missing, rest, "; ".join(f"{i}. {t}" for i, t in enumerate(titles, 1)), first_number=len(titles) + 1,
            ))
            r = _complete(provider, msgs, label="WriterAnswer", temperature=temperature, max_tokens=min(6000, 600 + 280 * missing), deadline=deadline)
            usage(r)
            keep_raw("deck_writer", r)
            answers.append(r.text or "")
            more, _ = parse_answer(r.text or "")
            if more is not None and more.status == "ok" and more.slides:
                extra = normalise_answer(more, topic, ref_text, [], mode.language, removed, first=len(deck.slides) + 1)
                from verstka.planning.agent import same_text

                have = [sn for s in deck.slides for sn in s.sentences]
                for s in extra.slides[:missing]:
                    s.part = rest_start + s.part if s.part >= 0 else -1
                    s.sentences = [sn for sn in s.sentences if not any(same_text(sn, x) for x in have)]
                    if not s.empty:
                        deck.slides.append(s)
                        have.extend(s.sentences)
                res.continuation = True
                emit(f"дописал ещё {_count_ru(len(extra.slides[:missing]), 'слайд', 'слайда', 'слайдов')}.")
        except Exception as e:  # noqa: BLE001 - the deck stays as long as what was written
            keep_raw("deck_writer", error=e)
            res.warnings.append(f"deck_writer continuation failed: {str(e)[:160]}")
    res.answers["writer"] = answers
    res.seconds["write"] = round(time.monotonic() - tw, 2)
    deck.title = deck.title or H.cap_first(_lead_free_title(topic))
    if not deck.slides:
        res.warnings.append("deck_writer failed: model answer rejected (no slide in it)")
        emit("модель не написала текст — соберу каркас по теме." if mode.kind == "topic" else "модель не написала текст — соберу по вашему тексту.")
        return finish("failed", "no slides")
    emit(f"написал текст на {_count_ru(len(deck.slides) + 1, 'слайд', 'слайда', 'слайдов')} — {_titles_list([s.title for s in deck.slides])}.")

    # 3. checks — the deterministic ones first (every figure and name against the full article, then the pairings: a
    # year next to a name, done vs planned, the direction of a transfer — repaired in the article's words or cut),
    # then the model's fact check (never more harm than good: apply_check), the guards; then the slides the checks
    # emptied, dropped or left with one sentence are written again from the article's unused sections (refill)
    support = ArticleSupport(full, topic) if full else None
    target = n_content
    check_on = bool((cfg.get("check") or {}).get("enabled", True))

    def det_checks(d: _Deck) -> tuple[int, int]:
        """(removed, repaired) by the deterministic checks of `d`."""
        if not full:
            return 0, 0
        b_rm, b_ed = len(removed), len(res.edits)
        verify_against(d, full, topic, removed, edits=res.edits, support=support)
        fix_pairings(d, support, removed, res.edits)
        return len(removed) - b_rm, len(res.edits) - b_ed

    def model_check(d: _Deck, reference_text: str, label: str) -> tuple[int, dict]:
        """The fact check on `d`: (how many statements it removed or replaced, its stats)."""
        msgs = skills.build_messages("writer_check", {"topic": topic, "reference": reference_text, "numbered": numbered(d)})
        r = _complete(provider, msgs, label="WriterCheckAnswer", temperature=0.0, max_tokens=int(skills.get("writer_check").params.get("max_tokens", 1500)), deadline=min(time.monotonic() + CHECK_MAX_S, deadline))
        usage(r)
        keep_raw("writer_check", r)
        if "check" not in res.answers:
            res.answers["check"] = r.text
        else:
            res.answers.setdefault("checks", []).append(r.text)
        from verstka.providers.openai_compat import extract_json

        ca = WriterCheckAnswer.model_validate(extract_json(r.text or "", {"issues"}))
        stats: dict[str, Any] = {"label": label}
        k = apply_check(d, ca.issues, removed, support=support, overruled=res.overruled, edits=res.edits, stats=stats)
        res.check_stats.append(stats)
        return k, stats

    def check_time() -> bool:
        return budget_end - time.monotonic() >= check_left and deadline - time.monotonic() >= 6

    k_rm, k_ed = det_checks(deck)
    if full:
        which = "которого" if k_rm % 10 == 1 and k_rm % 100 != 11 else "которых"
        said = []
        if k_ed:
            said.append(f"поправил по статье {_count_ru(k_ed, 'утверждение', 'утверждения', 'утверждений')}")
        if k_rm:
            said.append(f"убрал {_count_ru(k_rm, 'утверждение', 'утверждения', 'утверждений')}, {which} в ней нет")
        emit("сверил текст со статьёй — " + ", ".join(said) + "." if said else "сверил текст со статьёй — всё подтверждается.")
    tc = time.monotonic()
    if check_on and deck.slides:
        if check_time():
            try:
                before = len(removed)
                k, stats = model_check(deck, ref_text, "deck")
                res.checked = "reference" if ref_text else "model"
                if stats.get("degenerate"):
                    res.check_state = "degenerate"
                    emit(f"проверка фактов отметила {stats.get('flagged')} из {stats.get('statements')} утверждений — такой ответ не применяю, оставил сверку со статьёй.")
                elif k:
                    res.check_state = "applied"
                    first_text = next((x["text"] for x in removed[before:] if x["text"]), "")
                    emit(f"проверил факты — поправил или убрал {_count_ru(k, 'утверждение', 'утверждения', 'утверждений')}" + (f": «{_short(first_text, 120)}»." if first_text else "."))
                else:
                    res.check_state = "clean"
                    emit("проверил факты — всё подтверждается статьёй." if res.overruled else "проверил факты — замечаний нет.")
            except Exception as e:  # noqa: BLE001 - no check: the deck is built anyway
                keep_raw("writer_check", error=e)
                res.check_skipped = f"failed: {str(e)[:120]}"
                res.warnings.append(f"writer_check failed: {str(e)[:160]}")
                emit("проверка фактов не удалась — текст оставлен как есть.")
        else:
            res.check_skipped = "no_time"
            emit("проверка фактов пропущена — не хватает времени.")
    res.seconds["check"] = round(time.monotonic() - tc, 2)

    def guards(d: _Deck) -> None:
        if "politician" in (kind, writer_kind):
            k = guard_politician(d, removed)
            if k:
                emit(f"оставил только биографию — убрал {_count_ru(k, 'утверждение', 'утверждения', 'утверждений')} о политике.")
        if "company" in (kind, writer_kind) and res.kind != "private":
            guard_company(d, removed)

    guards(deck)
    if "politician" in (kind, writer_kind):
        res.kind = "politician"
    short = target <= SHORT_DECK_CONTENT
    dedupe_chronology(deck, removed, short=short)
    dedupe_events(deck, removed)
    dedupe_totals(deck, removed)
    dedupe_figures(deck, removed)
    drop_orphans(deck, removed)

    # 4. the refill: the asked slide count is a promise
    tf = time.monotonic()
    if deck.slides and (len(deck.slides) < target or any(_thin(s) for s in deck.slides)) and deadline - time.monotonic() >= REFILL_MIN_S:
        try:
            got = _refill(
                deck, parts, target, skills, provider, variables, temperature, deadline, topic, ref_text, full, mode, removed,
                usage=usage, keep_raw=keep_raw, answers=answers, checks=det_checks,
                model_check=(lambda d, rt: model_check(d, rt, "refill")) if check_on and ref_text else None, check_time=check_time,
                focus=where[1] if where else None,
            )
            res.refill = got
            if got.get("added") or got.get("topped"):
                guards(deck)
                dedupe_chronology(deck, removed, short=short)
                dedupe_events(deck, removed)
                dedupe_totals(deck, removed)
                dedupe_figures(deck, removed)
                drop_orphans(deck, removed)
                said = []
                if got.get("added"):
                    said.append(f"дописал {_count_ru(got['added'], 'слайд', 'слайда', 'слайдов')} вместо убранных")
                if got.get("topped"):
                    said.append(f"дополнил {_count_ru(got['topped'], 'слайд', 'слайда', 'слайдов')} из одного предложения")
                emit(" и ".join(said) + " — по разделам статьи, которые ещё не использованы." if full else " и ".join(said) + ".")
        except Exception as e:  # noqa: BLE001 - the deck stays as it is
            keep_raw("deck_writer", error=e)
            res.warnings.append(f"deck_writer refill failed: {str(e)[:160]}")
    res.seconds["refill"] = round(time.monotonic() - tf, 2)
    res.removed = removed
    if len(deck.slides) < 2:
        res.warnings.append("deck_writer failed: model answer rejected (fewer than 2 slides left after the checks)")
        emit("после проверки от текста почти ничего не осталось — соберу каркас по теме." if mode.kind == "topic" else "после проверки от текста почти ничего не осталось — соберу по вашему тексту.")
        return finish("failed", "too short")
    if len(deck.slides) < target:
        res.short_by = target - len(deck.slides)
        emit(f"вышло {_count_ru(len(deck.slides) + 1, 'слайд', 'слайда', 'слайдов')} вместо {target + 1}: на остальные не хватило проверенных фактов.")

    # 4. the written text becomes the brief
    res.text = render_text(deck)
    res.title = deck.title
    res.slides = len(deck.slides)
    purpose = brief.purpose if res.kind in ("company", "market") else "other"
    res.brief = Brief(
        text=render_text(deck, rules=True), slide_count=res.slides + 1, audience=brief.audience, purpose=purpose, language=brief.language,
        title_hint=None, tone=brief.tone, extra_instructions=brief.extra_instructions,
    )
    return finish("written")


def _lead_free_title(topic: str) -> str:
    from verstka.planning.reference import lead_free

    t = lead_free(topic) or topic
    words = t.split()
    return " ".join(words[:6])


__all__ = [
    "AGENT_RESERVE_S", "CHECK_MIN_LEFT_S", "POLITICIAN_LEXICON", "STORYLINES", "WRITER_MIN_S", "WriterMode", "WriterResult",
    "ArticleSupport", "COMPANY_LEXICON", "anaphoric", "apply_check", "attribution", "dedupe_chronology", "drop_orphans",
    "filler_sentence", "guard_company", "guard_politician", "guess_kind", "junk_sentence", "load_config",
    "normalise_answer", "numbered", "parse_answer", "render_text", "salvage_slides", "storyline", "storyline_parts",
    "verify_against", "write_deck", "writer_mode",
]
