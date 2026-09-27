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
from typing import Any, Callable, Literal, Optional

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

    @property
    def line(self) -> str:
        return self.title + (" (timeline)" if self.timeline else " (data)" if self.data else "")


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
    parts = [p for p in _parts(kind) if not p.data or reference or kind in ("market", "company")]
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
_PRONOUN_SUBJECT_RE = re.compile(r"^(?:[^\s,.;:]+\s+){1,4}?(?:он|она|оно|они)(?![\wё])")


def anaphoric(sentence: str) -> bool:
    """The sentence leans on the one before it (a pronoun or a demonstrative opens it, or a personal pronoun is its
    subject): without that sentence it has no antecedent."""
    s = (sentence or "").strip()
    return bool(_ANAPHOR_RE.match(s) or _PRONOUN_SUBJECT_RE.match(s))


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
            keep.append(sn)
            gone = False
    s.sentences = keep
    return n


def _deck_of(a: WriterAnswer) -> _Deck:
    d = _Deck(title=a.title.strip(), subtitle=a.subtitle.strip(), kind=(a.kind or "other").lower())
    for s in a.slides:
        d.slides.append(_Slide(
            title=s.title.strip(),
            sentences=sentences_of(s.text or ""),
            timeline=[e.model_dump() for e in s.timeline] if s.timeline else None,
            data=s.data.model_dump() if s.data else None,
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
        seen: list[str] = [x for x in s.sentences if x in s.theses]

        def why_of(sn: str, earlier: list[str] = earlier, seen: list[str] = seen) -> Optional[str]:
            why = junk_sentence(sn, known, language, strict)
            if why:
                return f"junk: {why}"
            if filler_sentence(sn):
                return "filler"
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
    человек», «61 государство, 80 % населения», the atomic bombings). A statement is supported when it has at least one
    figure, every figure is the article's (value level, dates and years included), every proper noun of it is in the
    article, and each figure stands in the article next to the statement's own words (its sentence or the one before or
    after it: «61 государство (80 % населения Земного шара)» for «61 страну и около 80 % населения Земли») — words the
    article uses rarely (not «компания», «Mail.ru» of the VK article: «В 2006 году компания была переименована в Mail.ru
    Group» is not supported by 2006 standing next to «компания»); two of them when the statement has three or more."""

    COMMON_SHARE = 0.03  # a word of more than this share of the article's sentences is no evidence

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

    def _near(self, group: int) -> set[str]:
        got = self._ctx.get(group)
        if got is None:
            got = set().union(*(self._group.get(g, set()) for g in (group - 1, group, group + 1)))
            self._ctx[group] = got
        return got

    @staticmethod
    def _meets(a: str, near: set[str]) -> bool:
        return any(n.startswith(a) or a.startswith(n) for n in near if min(len(a), len(n)) >= 3)

    def supported(self, text: str) -> bool:
        from verstka.planning.grounding import content_stems, figures

        text = " ".join((text or "").split())
        figs = figures(text)
        if not figs or unknown_names(text, self.stems) or unknown_names(f"x {text}", self.stems):
            return False
        mine = {x[:5] for x in content_stems(text, neutral=True) if not re.match(r"^\d", x)} - self.topic
        for f in figs:
            try:
                if self.idx.verdict(f) == "bad":
                    return False
                places = self.idx._same(f)
            except Exception:  # noqa: BLE001 - a figure the index cannot judge: not supported
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


def apply_check(
    deck: _Deck, issues: list[Any], removed: Optional[list[dict]] = None, first: int = 1,
    support: Optional[ArticleSupport] = None, overruled: Optional[list[dict]] = None,
) -> int:
    """Remove every reported sentence, timeline entry and data row (any verdict); never replace a word. Unknown ids
    and the user's theses are ignored; with `support` (the full articles), a reported statement the full article states
    stays (recorded in `overruled`). A sentence right after a removed one that leans on it goes too. A slide left with
    nothing goes. Returns how many were removed."""
    removed = removed if removed is not None else []
    kill: dict[tuple[int, str, int], str] = {}
    for it in issues:
        ident = getattr(it, "id", None) if not isinstance(it, dict) else it.get("id")
        verdict = (getattr(it, "verdict", None) if not isinstance(it, dict) else it.get("verdict")) or ""
        problem = (getattr(it, "problem", None) if not isinstance(it, dict) else it.get("problem")) or ""
        m = _ID_RE.match(str(ident or ""))
        if not m:
            continue
        kill[(int(m.group(1)), (m.group(2) or "s").lower(), int(m.group(3)))] = f"check: {verdict or 'issue'}" + (f" — {problem[:100]}" if problem else "")

    def stays(where: str, text: str, why: str) -> bool:
        if support is None or not support.supported(text):
            return False
        if overruled is not None:
            overruled.append({"where": where, "text": text, "why": why, "kept": "the full article states it"})
        return True

    n = 0
    for i, s in enumerate(deck.slides, first):
        pos: dict[str, int] = {}
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
    r"недоступн\w*\s+в\s+(?:App\s*Store|Google\s*Play)|скандал|уголовн",
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


def dedupe_chronology(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
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


# ------------------------------------------------------------------ a sentence left without its subject

_ORPHAN_RE = re.compile(r"^(?:Он|Она|Оно|Они|Его|Её|Ее|Их|Ему|Ей|Им|Него|Неё|Них)(?![\wё])")


def drop_orphans(deck: _Deck, removed: Optional[list[dict]] = None, first: int = 1) -> int:
    """A slide's text never starts with a personal pronoun («Он происходит в хлоропластах») — its subject was in a
    sentence the checks removed (or on another slide): the sentence goes (deletion only, never rewritten)."""
    removed = removed if removed is not None else []
    n = 0
    for i, s in enumerate(deck.slides, first):
        while s.sentences and s.sentences[0] not in s.theses and _ORPHAN_RE.match(s.sentences[0].strip()):
            _removed(removed, f"{i}", s.sentences.pop(0), "no subject (a pronoun opens the slide)")
            n += 1
    deck.slides = [s for s in deck.slides if not s.empty]
    return n


# ------------------------------------------------------------------ the written text (§7)

CHART_RU = {"column": "столбчатая", "bar": "столбчатая", "line": "линейная", "pie": "круговая"}
RULES_LINE = "Тон нейтральный, энциклопедический. Заголовки — факты из текста, без оценок."


def _sentence(t: str) -> str:
    t = " ".join((t or "").split()).strip()
    return t if not t or t.endswith((".", "!", "?", "…")) else t + "."


def render_text(deck: _Deck) -> str:
    """The written text as the analyst reads it best: «Слайд 1. Титульный / Название / Подзаголовок», «Слайд N.
    Заголовок» + sentences, a «Хронология:» dash list, a data dash list with its chart request and «данные
    приблизительные», and a closing line of rules (neutral tone, factual headings)."""
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
    out += ["", RULES_LINE]
    return "\n".join(out) + "\n"


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
            "seconds": self.seconds.get("total", 0.0),
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
                    limit=int(rcfg.get("max_chars", 12000)), timeout_s=float(rcfg.get("timeout_s", 6)), cache_dir=cache_dir,
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
            "storyline": "\n".join(f"{i}. {p.line}" for i, p in enumerate(story, 1)),
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
        rest = parts[len(deck.slides):] if len(parts) > len(deck.slides) else parts[-missing:]
        rest = rest[:missing]
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

    # 3. checks: the figures and names against the full article; the fact check (deletion-only); the politician guard
    support = ArticleSupport(full, topic) if full else None
    if full:
        before = len(removed)
        verify_against(deck, full, topic, removed, edits=res.edits, support=support)
        k = len(removed) - before
        which = "которого" if k % 10 == 1 and k % 100 != 11 else "которых"
        emit(f"сверил текст со статьёй — убрал {_count_ru(k, 'утверждение', 'утверждения', 'утверждений')}, {which} в ней нет." if k else "сверил текст со статьёй — всё подтверждается.")
    check_on = bool((cfg.get("check") or {}).get("enabled", True))
    tc = time.monotonic()
    if check_on and deck.slides:
        if budget_end - time.monotonic() >= check_left and deadline - time.monotonic() >= 6:
            try:
                msgs = skills.build_messages("writer_check", {"topic": topic, "reference": ref_text, "numbered": numbered(deck)})
                r = _complete(provider, msgs, label="WriterCheckAnswer", temperature=0.0, max_tokens=int(skills.get("writer_check").params.get("max_tokens", 1200)), deadline=min(time.monotonic() + CHECK_MAX_S, deadline))
                usage(r)
                keep_raw("writer_check", r)
                res.answers["check"] = r.text
                from verstka.providers.openai_compat import extract_json

                ca = WriterCheckAnswer.model_validate(extract_json(r.text or "", {"issues"}))
                before = len(removed)
                k = apply_check(deck, ca.issues, removed, support=support, overruled=res.overruled)
                res.checked = "reference" if ref_text else "model"
                if k:
                    first_text = next((x["text"] for x in removed[before:] if x["text"]), "")
                    emit(f"проверил факты — убрал {_count_ru(k, 'утверждение', 'утверждения', 'утверждений')}: «{_short(first_text, 120)}».")
                else:
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
    if "politician" in (kind, writer_kind):
        k = guard_politician(deck, removed)
        if k:
            emit(f"оставил только биографию — убрал {_count_ru(k, 'утверждение', 'утверждения', 'утверждений')} о политике.")
        res.kind = "politician"
    if "company" in (kind, writer_kind) and res.kind != "private":
        guard_company(deck, removed)
    dedupe_chronology(deck, removed)
    drop_orphans(deck, removed)
    res.removed = removed
    if len(deck.slides) < 2:
        res.warnings.append("deck_writer failed: model answer rejected (fewer than 2 slides left after the checks)")
        emit("после проверки от текста почти ничего не осталось — соберу каркас по теме." if mode.kind == "topic" else "после проверки от текста почти ничего не осталось — соберу по вашему тексту.")
        return finish("failed", "too short")

    # 4. the written text becomes the brief
    res.text = render_text(deck)
    res.title = deck.title
    res.slides = len(deck.slides)
    purpose = brief.purpose if res.kind in ("company", "market") else "other"
    res.brief = Brief(
        text=res.text, slide_count=res.slides + 1, audience=brief.audience, purpose=purpose, language=brief.language,
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
