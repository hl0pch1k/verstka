"""The writer's reference: the topic's encyclopedia article(s) from Wikipedia (MediaWiki API), cached on disk.

Only article titles leave the machine — the ones the `topic_reference` skill proposed (and, in the fallback search,
those titles again and the topic without its lead words) — never the user's text as written. The client is optional
and safe: a short timeout per request, a switch (configs/writer.yaml `reference.enabled`, env VERSTKA_WIKI=0), a
User-Agent with a contact (Wikimedia answers 403 without one), and every failure is a missing reference (the writer
then writes from the model's knowledge), never an error of the deck.

`cut_reference` is what the writer reads (≤ 12 000 characters: the lead and the first paragraph of every section);
the full page texts are kept for the figure check (writer.verify_against)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

API = "https://{lang}.wikipedia.org/w/api.php"
MAX_PAGES = 2
_CACHE_VERSION = 1
# the title resolution's own version, part of its cache key: a resolution made by older ranking rules is not reused
# (gate 4: «Возобновляемая энергетика в России» kept resolving to «Ядерная энергетика России» for 7 days after the
# sibling rule fixed it) — raise it whenever resolve() or sibling_title() changes what they pick
RESOLVE_VERSION = 2

# «Презентация про …», «История …», «Как работает …», «на 10 слайдов»: words that say what to make, not what about
LEAD_WORDS_RE = re.compile(
    r"(?<![\wё])(?:презентаци\w*|доклад\w*|сделай(?:те)?|создай(?:те)?|подготовь(?:те)?|расскажи(?:те)?|про|о|об|обо|на\s+тему|"
    r"по\s+теме|истори[яиюей]|как\s+работа\w*|(?:на\s+)?\d+\s+слайд\w*|для|мне|нужна|нужно|хочу)(?![\wё])",
    re.I,
)
_SKIP_RE = re.compile(
    r"^(?:примечани|литератур|ссылки|см\.\s*также|источник|комментари|галере|фильмограф|библиограф|награды|в\s+культуре|"
    r"в\s+искусстве|notes|references|see also|external links|further reading|bibliography|sources|gallery)",
    re.I,
)
_BIO_RE = re.compile(
    r"биограф|ранние\s+годы|детство|образовани|карьер|служб|трудов|государственн\w+\s+деятельност|выбор|избрани|должност|"
    r"президент|премьер|председател|депутат|губернатор|мэр|early life|education|career",
    re.I,
)
_HEAD_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")


@dataclass
class RefPage:
    title: str
    url: str = ""
    revid: Optional[int] = None
    timestamp: Optional[str] = None
    text: str = ""
    cached: bool = False

    def meta(self) -> dict:
        return {"title": self.title, "url": self.url, "revid": self.revid, "timestamp": self.timestamp}


@dataclass
class Reference:
    """What the writer got: the pages (main first), the cut it reads, and what the lookup did."""

    pages: list[RefPage] = field(default_factory=list)
    cut: str = ""
    lang: str = "ru"
    proposed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requests: int = 0
    seconds: float = 0.0

    @property
    def full_texts(self) -> list[str]:
        return [p.text for p in self.pages if p.text]

    @property
    def main(self) -> Optional[RefPage]:
        return self.pages[0] if self.pages else None


def user_agent(contact: str) -> str:
    try:
        from verstka import __version__ as version
    except Exception:  # noqa: BLE001
        version = "0"
    return f"Verstka/{version} ({contact.strip()})"


def contact_ok(contact: Optional[str]) -> bool:
    """A URL or an e-mail (Wikimedia's policy: the User-Agent must say how to reach the operator), ASCII only."""
    c = (contact or "").strip()
    if not c or not c.isascii():
        return False
    return bool(re.match(r"^https?://\S+\.\S+", c) or re.match(r"^[^@\s]+@[^@\s]+\.\w+$", c))


def tokens(text: str) -> set[str]:
    """The words a title and a query may share: 4-letter stems of words of ≥ 4 letters; Latin and all-caps words count
    from 2 letters («VK», «ИИ»)."""
    out: set[str] = set()
    for w in _TOKEN_RE.findall(text or ""):
        if w.isdigit():
            continue
        latin = w.isascii()
        if len(w) >= 4 or ((latin or w.isupper()) and len(w) >= 2):
            out.add(w.lower()[:4])
    return out


def lead_free(topic: str) -> str:
    """The topic without the words that say what to make («Презентация про историю VK на 10 слайдов» → «VK»)."""
    t = LEAD_WORDS_RE.sub(" ", topic or "")
    t = re.sub(r"[«»\"'“”„]", " ", t)
    return " ".join(t.split()).strip(" .,:;—–-")


# ------------------------------------------------------------------ the cut the writer reads


def _cut_at_sentence(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    part = text[:limit]
    end = max(part.rfind(". "), part.rfind("! "), part.rfind("? "), part.rfind(".\n"))
    if end >= limit * 0.4:
        return part[: end + 1].strip()
    sp = part.rfind(" ")
    return (part[:sp] if sp > 0 else part).rstrip(" ,;:—–-") + "…"


def sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(lead, [(level-2 heading, the section's text with its subsections, headings removed)])."""
    heads = list(_HEAD_RE.finditer(text or ""))
    if not heads:
        return (text or "").strip(), []
    lead = text[: heads[0].start()].strip()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(heads):
        m = heads[i]
        if len(m.group(1)) != 2:
            i += 1
            continue
        j = i + 1
        while j < len(heads) and len(heads[j].group(1)) != 2:
            j += 1
        end = heads[j].start() if j < len(heads) else len(text)
        body = _HEAD_RE.sub("", text[m.end() : end]).strip()
        out.append((m.group(2).strip(), body))
        i = j
    return lead, out


def _section_text(body: str, room: int) -> str:
    """The section's text from its first paragraph longer than 80 characters on, as much as `room` holds (cut at a
    sentence end): the first paragraph, and the next ones while there is room."""
    paras = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
    start = next((i for i, p in enumerate(paras) if len(p) > 80), 0)
    out: list[str] = []
    used = 0
    for p in paras[start:]:
        if out and (len(p) < 80 or used + len(p) + 1 > room):
            break
        out.append(p)
        used += len(p) + 1
    return _cut_at_sentence("\n".join(out), room)


_QUOTE_RE = re.compile(r"«[^«»]*(?:«[^«»]*»[^«»]*)*»")
_SENT_END_RE = re.compile(r"[.!?…](?=\s|$)|\n")
QUOTE_MAX_WORDS = 12


def drop_quotations(text: str, max_words: int = QUOTE_MAX_WORDS) -> str:
    """The text without the sentences that carry a long direct quotation («…» of more than `max_words` words): a
    participant's words («…устранение угрозы с Востока. Польша должна быть захвачена…») are not facts, and the writer
    restated one as one («Целью было устранить угрозу со стороны СССР»). Names and titles in quotes («Юла») stay."""
    spans: list[tuple[int, int]] = []
    for m in _QUOTE_RE.finditer(text or ""):
        if len(re.findall(r"[\wё]+", m.group(0))) <= max_words:
            continue
        a = max(text.rfind(". ", 0, m.start()), text.rfind("! ", 0, m.start()), text.rfind("? ", 0, m.start()), text.rfind("\n", 0, m.start()))
        a = a + 1 if a >= 0 else 0
        e = _SENT_END_RE.search(text, m.end())
        b = e.end() if e else len(text)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(b, spans[-1][1]))
        else:
            spans.append((a, b))
    if not spans:
        return text
    out, pos = [], 0
    for a, b in spans:
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out))


_PLACE_RE = re.compile(r"(?<![\wё])(?:в|во|на)\s+([А-ЯЁ][а-яё]{2,}(?:[\s-][А-ЯЁ][а-яё]+)?)")
_PLACE_ADJ = (("российск", "росси"), ("рф", "росси"), ("московск", "москв"), ("петербургск", "петер"))


def place_of(topic: str) -> Optional[tuple[str, str]]:
    """The country or the city a topic is about — («России», "росси») of «Рынок электромобилей в России», of
    «российский рынок кофе» — or None: the writer then prefers that place's facts and the cut its sections."""
    core = lead_free(topic)
    m = _PLACE_RE.search(core)
    if m:
        word = m.group(1).split()[0].split("-")[0]
        return m.group(1), word.lower()[: max(4, min(5, len(word) - 1))]
    low = core.lower()
    for adj, stem in _PLACE_ADJ:
        if re.search(rf"(?<![\wё]){adj}", low):
            return {"росси": "России", "москв": "Москве", "петер": "Санкт-Петербурге"}[stem], stem
    return None


def focus_sections(text: str, stem: str) -> list[tuple[str, str]]:
    """The sections of any level whose heading names the place (`stem`: «росси» → «Россия», «В России», «Планы
    российских автопроизводителей»), each with its text up to the next heading of its level or above."""
    heads = list(_HEAD_RE.finditer(text or ""))
    out = []
    for i, m in enumerate(heads):
        if stem not in m.group(2).lower() or _SKIP_RE.match(m.group(2).strip()):
            continue
        lvl = len(m.group(1))
        end = next((h.start() for h in heads[i + 1:] if len(h.group(1)) <= lvl), len(text))
        body = _HEAD_RE.sub("", text[m.end():end]).strip()
        if len(body) > 80:
            out.append((m.group(2).strip(), body))
    return out


def _recent(body: str, room: int) -> str:
    """As much of a section as `room` holds, its most recent paragraphs first (a place's section of a market's article
    is its history: «В начале 2000-х…» … «В 2024 году в России было продано 17,8 тысячи электромобилей»), in the
    section's order."""
    paras = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
    if sum(len(p) + 1 for p in paras) <= room:
        return "\n".join(paras)

    def latest(p: str) -> int:
        return max((int(y) for y in re.findall(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", p)), default=0)

    chosen: list[int] = []
    used = 0
    for i in sorted(range(len(paras)), key=lambda i: (-latest(paras[i]), i)):
        if used + len(paras[i]) + 1 <= room:
            chosen.append(i)
            used += len(paras[i]) + 1
    if not chosen:
        return _cut_at_sentence(paras[0], room)
    return "\n".join(paras[i] for i in sorted(chosen))


def _drop_sections(text: str, headings: list[str]) -> str:
    """The text without the sections of those headings (each up to the next heading of its level or above)."""
    heads = list(_HEAD_RE.finditer(text or ""))
    spans = []
    for i, m in enumerate(heads):
        if m.group(2).strip() not in headings:
            continue
        lvl = len(m.group(1))
        end = next((h.start() for h in heads[i + 1:] if len(h.group(1)) <= lvl), len(text))
        spans.append((m.start(), end))
    out, pos = [], 0
    for a, b in sorted(spans):
        if a < pos:
            continue
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    return "".join(out)


DEEP_KINDS = ("history", "conflict")  # a story told by its subsections: the turning points are their first sentences
DEEP_LEAD_MAX = 5000  # a war's lead is its summary: every turning point with its date (WWII: 4 663 characters)
DEEP_INTRO_MAX = 350


def _sections_raw(text: str) -> list[tuple[str, str]]:
    """[(level-2 heading, the section's text with its subsection headings kept)]."""
    heads = list(_HEAD_RE.finditer(text or ""))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(heads):
        if len(m.group(1)) != 2:
            continue
        end = next((h.start() for h in heads[i + 1:] if len(h.group(1)) <= 2), len(text))
        out.append((m.group(2).strip(), text[m.end():end]))
    return out


def _subsections(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """(the section's intro, [(level-3 heading, its text, deeper headings removed)]) of a level-2 section's raw text."""
    heads = [m for m in _HEAD_RE.finditer(raw or "") if len(m.group(1)) == 3]
    if not heads:
        return _HEAD_RE.sub("", raw or "").strip(), []
    intro = _HEAD_RE.sub("", raw[: heads[0].start()]).strip()
    subs = []
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(raw)
        subs.append((m.group(2).strip(), _HEAD_RE.sub("", raw[m.end():end]).strip()))
    return intro, subs


# a turning point of a war told inside a subsection: a dated sentence with a battle, an offensive, a surrender…
_TURN_RE = re.compile(r"(?<![\wё])(?:битв\w*|сражени\w*|наступлени\w*|контрнаступлени\w*|поражени\w*|капитуляци\w*|бомбардировк\w*|"
                      r"высадк\w*|окружени\w*|разгром\w*|освобо\w*|штурм\w*|взяти\w*|блокад\w*)(?![\wё])", re.I)
_DATED_RE = re.compile(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?![\d.,])|(?<![\d.,])\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)", re.I)
TURN_SHARE = 0.45  # the part of a subsection's room its turning points may take


def _turning_text(body: str, room: int) -> str:
    """A war's subsection: its opening, then its turning points further down (a dated sentence with a battle, an
    offensive, a surrender: «30 сентября 1941 года немецкие войска начали наступление на Москву» stands in the middle of
    «Вторжение в СССР», whose opening never reached it — gate 4: no Moscow in the WWII deck), as much as `room` holds."""
    opening = _section_text(body, max(80, int(room * (1 - TURN_SHARE))))
    left = room - len(opening) - 1
    if left < 60:
        return opening
    rest = body[len(opening):] if body.startswith(opening) else body.replace(opening, " ", 1)
    sents = [x for x in re.split(r"(?<=[.!?])\s+", " ".join(rest.split())) if 30 <= len(x) and _TURN_RE.search(x) and _DATED_RE.search(x)]

    def rank(k: int) -> tuple:
        x = sents[k]
        year = bool(re.search(r"(?<![\d.,])(?:1\d{3}|20\d{2})(?![\d.,])", x))
        return (-(2 * year + len({m.group(0).lower()[:5] for m in _TURN_RE.finditer(x)})), len(x), k)

    chosen: list[int] = []
    for k in sorted(range(len(sents)), key=rank):  # a sentence with its year first (the event is dated alone)
        if len(sents[k]) + 1 <= left:
            chosen.append(k)
            left -= len(sents[k]) + 1
        if left < 60:
            break
    extra = [sents[k] for k in sorted(chosen)]  # in the article's order
    return opening + ("\n" + " ".join(extra) if extra else "")


def _deep_section_text(raw: str, room: int) -> str:
    """A level-2 section of a history as its intro (≤ DEEP_INTRO_MAX) and the opening of every subsection under its
    heading («### Перелом на Восточном фронте» + «19 ноября 1942 года Красная армия перешла в контрнаступление под
    Сталинградом…»): the turning points of a war stand in its subsections' first sentences, which the plain cut (the
    first paragraph of each level-2 section) never reached (gate 2: no Сталинград, Курск, Хиросима in the WWII deck)."""
    intro, subs = _subsections(raw)
    subs = [(h, b) for h, b in subs if not _SKIP_RE.match(h) and len(b) > 80]
    if not subs:
        return _section_text(intro, room)
    head = _section_text(intro, min(DEEP_INTRO_MAX, max(150, room // 4))) if len(intro) > 80 else ""
    left = room - len(head) - 2
    per = max(120, left // len(subs) - 8)
    parts = [head] if head else []
    used = len(head)
    for h, b in subs:
        piece = f"### {h}\n{_turning_text(b, max(80, per - len(h)))}"
        if used + len(piece) + 1 > room and parts:
            break
        parts.append(piece)
        used += len(piece) + 1
    return "\n".join(parts)


def cut_reference(text: str, limit: int = 12000, kind: Optional[str] = None, focus: Optional[str] = None) -> str:
    """What the writer reads of one article: the lead (≤ 3 000 characters) and the first paragraph of every level-2
    section outside the skip list («Примечания», «Литература»…), each cut at a sentence end so that every section fits
    in `limit` (taking sections in order covered only the first 7 of ~30 sections of «Вторая мировая война»). A living
    politician (`kind` "politician"): the lead's first two paragraphs and the biography sections only. The sentences
    with a long direct quotation are left out (drop_quotations). `focus` (the stem of the topic's place, «росси»): the
    sections of any level about that place come first, whole as far as a third of the limit holds («Рынок
    электромобилей в России» read only the article's world figures before)."""
    text = drop_quotations(text or "")
    if focus:
        found = focus_sections(text, focus)
        if found:
            share = max(600, limit // 3)
            per = max(300, share // len(found) - 40)
            part = "\n\n".join(f"## {h}\n{_recent(b, per)}" for h, b in found)
            rest = cut_reference(_drop_sections(text, [h for h, _ in found]), limit - len(part) - 2, kind)
            lead_end = rest.find("\n\n## ")
            if lead_end < 0:
                return f"{rest}\n\n{part}".strip()
            return f"{rest[:lead_end]}\n\n{part}{rest[lead_end:]}".strip()
    lead, secs = sections(text)
    secs = [(h, b) for h, b in secs if not _SKIP_RE.match(h) and b.strip()]
    if not secs and kind != "politician":
        return _cut_at_sentence(lead, limit)  # an article without sections: its text, as much as the limit holds
    if kind == "politician":
        paras = [p.strip() for p in re.split(r"\n+", lead) if p.strip()]
        lead = "\n".join(paras[:2])
        secs = [(h, b) for h, b in secs if _BIO_RE.search(h)]
    deep = kind in DEEP_KINDS
    lead = _cut_at_sentence(lead, min(DEEP_LEAD_MAX if deep else 3000, max(600, limit // 3)))
    if not secs:
        return _cut_at_sentence(lead, limit)
    if deep:
        raw = {h: r for h, r in _sections_raw(text)}
        heads = sum(len(h) + 5 for h, _ in secs)
        # a section's share grows with its subsections (a war's periods), never below 350 characters
        weight = {h: 1 + min(10, len(_subsections(raw.get(h, ""))[1])) for h, _ in secs}
        total = sum(weight.values())
        room_all = max(0, limit - len(lead) - heads - 4)
        parts = [lead] + [f"## {h}\n{_deep_section_text(raw.get(h, b), max(350, room_all * weight[h] // total))}" for h, b in secs]
        out = "\n\n".join(p for p in parts if p.strip())
        return out if len(out) <= limit else _cut_at_sentence(out, limit)
    heads = sum(len(h) + 5 for h, _ in secs)
    room = (limit - len(lead) - heads - 4) // len(secs)
    if room < 400:
        # many sections: the lead gives way first (down to 1 500), then every section gets the same smaller share
        lead = _cut_at_sentence(lead, max(1500, limit - heads - 400 * len(secs)))
        room = (limit - len(lead) - heads - 4) // len(secs)
    if room < 120:
        # too many sections for the limit: the first ones, 120 characters each
        n = max(1, (limit - len(lead)) // (120 + 30))
        secs = secs[:n]
        heads = sum(len(h) + 5 for h, _ in secs)
        room = max(80, (limit - len(lead) - heads - 4) // len(secs))
    parts = [lead] + [f"## {h}\n{_section_text(b, room)}" for h, b in secs]
    out = "\n\n".join(p for p in parts if p.strip())
    return out if len(out) <= limit else _cut_at_sentence(out, limit)


def cut_pages(pages: list[RefPage], limit: int = 12000, kind: Optional[str] = None, focus: Optional[str] = None) -> str:
    """The cut of up to two pages: the main page gets 2/3 of the limit when there are two (half when the second is
    the page of the topic's place, `focus`); a third page (a market part's own article: writer.add_part_page) shares
    the second half with the second one."""
    pages = [p for p in pages if p.text][:MAX_PAGES + 1]
    if not pages:
        return ""
    if len(pages) == 1:
        return f"# {pages[0].title}\n{cut_reference(pages[0].text, limit - len(pages[0].title) - 4, kind, focus)}"
    if len(pages) == 2:
        first = int(limit / 2) if focus and focus in pages[1].title.lower() else int(limit * (3 / 4 if kind in DEEP_KINDS else 2 / 3))
        shares = [first, limit - first]
    else:
        first = int(limit / 2)
        rest = (limit - first) // (len(pages) - 1)
        shares = [first] + [rest] * (len(pages) - 1)
    return "\n\n".join(f"# {p.title}\n{cut_reference(p.text, s - len(p.title) - 6, kind, focus)}" for p, s in zip(pages, shares))


def _parts_any_level(text: str) -> list[tuple[str, str]]:
    """[(heading, its own text up to the next heading of any level)] of an article, the lead first as ("", lead)."""
    heads = list(_HEAD_RE.finditer(text or ""))
    if not heads:
        return [("", (text or "").strip())]
    out = [("", text[: heads[0].start()].strip())]
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
        out.append((m.group(2).strip(), text[m.end():end].strip()))
    return out


def _stems5(text: str) -> set[str]:
    return {w.lower()[:5] for w in _TOKEN_RE.findall(text or "") if len(w) >= 5 and not w.isdigit()}


# sections a refill never reads: criticism, lawsuits, sanctions, layoffs, incidents (writer rule 3)
_TROUBLE_HEAD_RE = re.compile(r"критик|скандал|санкц|(?<![\wё])суд|конфликт|увольн|сокращ|инцидент|утечк|блокир|претензи|расследован|"
                              r"противоречи|обвинени|нарушени|controvers|criticism|lawsuit", re.I)


def fresh_cut(full_texts: list[str], used: str, limit: int = 8000, want: str = "", per: int = 700, focus: Optional[str] = None) -> str:
    """What a refill reads (the slides a check emptied are written again): the article sections whose words the deck
    does not use yet — freshest and closest to the slides wanted (`want`: their working titles and hints) first —
    each its opening up to `per` characters, in the article's order, up to `limit`. The lead and the skip sections
    («Примечания», «Литература»…) are left out; with a `focus` (the stem of the topic's place, «росси»), only the
    sections that name the place (the EV deck's refill told the USA's subsidies on its «Инфраструктура» slide)."""
    used_st = _stems5(used)
    want_st = _stems5(want)
    cands: list[tuple[float, int, int, str, str]] = []
    for p, text in enumerate(full_texts or []):
        for k, (h, body) in enumerate(_parts_any_level(drop_quotations(text or ""))):
            if not h or _SKIP_RE.match(h) or _TROUBLE_HEAD_RE.search(h) or len(body) < 120:
                continue
            st = _stems5(body[:1500])
            if not st or (focus and focus not in h.lower() and focus not in body[:1500].lower()):
                continue
            fresh = len(st - used_st) / len(st)
            near = len(_stems5(h) & want_st) + 0.2 * len(st & want_st)
            cands.append((fresh + 0.15 * near, p, k, h, body))
    chosen: list[tuple[int, int, str, str]] = []
    used_chars = 0
    for score, p, k, h, body in sorted(cands, key=lambda x: -x[0]):
        piece = f"## {h}\n{_section_text(body, per)}"
        if used_chars + len(piece) + 2 > limit:
            continue
        chosen.append((p, k, h, piece))
        used_chars += len(piece) + 2
    return "\n\n".join(piece for _p, _k, _h, piece in sorted(chosen))


# ------------------------------------------------------------------ the numbered reference (source-anchored writing)


@dataclass
class RefSentence:
    """One numbered sentence of what the writer reads: its number in the prompt («[41]»), the page it is from, its
    text as the cut gives it and the paragraph (line) of the cut it stands in."""

    id: int
    page: str
    text: str
    line: int


def split_line(line: str) -> list[str]:
    """A paragraph's sentences the way the article index splits them (heuristics.split_sentences), a piece cut inside a
    quotation («Территория будущего. Москва 2030») joined back — so that a numbered sentence is one sentence of
    writer.ArticleSupport."""
    from verstka.planning import heuristics as H

    out: list[str] = []
    for p in H.split_sentences(line) or ([line.strip()] if line.strip() else []):
        if out and (out[-1].count("«") > out[-1].count("»") or JOIN_TAIL_RE.search(out[-1])):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


# a piece that ends with an initial or an abbreviation did not end its sentence («…по инициативе Д.» + «Устинова было
# принято решение…», «им.» + «Дзержинского»)
JOIN_TAIL_RE = re.compile(r"(?:^|[\s(«])(?:[А-ЯЁA-Z]|им|св|ул|проф|акад|ген|др|т\.\s?е|т\.\s?д|т\.\s?п)\.$")


def number_reference(cut: str, start: int = 1) -> tuple[str, list[RefSentence]]:
    """The cut with a compact number before each sentence («[41] 19 ноября 1942 года Красная армия перешла…»), the
    headings («# Вторая мировая война», «## Ход войны») as they are, and the numbered sentences. The writer builds every
    sentence of its own from one or two of them and cites their numbers; `start` continues the numbering of an earlier
    cut (the refill reads other sections of the same articles)."""
    out: list[str] = []
    sents: list[RefSentence] = []
    page = ""
    n = start
    for li, raw in enumerate((cut or "").splitlines()):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", line)
        if m:
            if len(m.group(1)) == 1:
                page = m.group(2).strip()
            out.append(line)
            continue
        parts = split_line(line)
        if not parts:
            continue
        shown = []
        for p in parts:
            sents.append(RefSentence(n, page, p, li))
            shown.append(f"[{n}] {p}")
            n += 1
        out.append(" ".join(shown))
    return "\n".join(out).strip() + "\n", sents


# ------------------------------------------------------------------ the client


class WikiClient:
    """MediaWiki API calls with a short timeout, a User-Agent with the contact and a disk cache of pages and title
    resolutions (`<cache_dir>/<lang>/…`, reused for `cache_days`; a stale entry is used when the network fails)."""

    def __init__(
        self, lang: str, contact: str, *, timeout_s: float = 6.0, cache_dir: Optional[Path] = None, cache_days: float = 7.0,
        transport: Any = None, deadline: Optional[float] = None,
    ) -> None:
        import httpx

        self.lang = lang if lang in ("ru", "en") else "ru"
        self.url = API.format(lang=self.lang)
        self.timeout_s = float(timeout_s)
        self.cache_dir = Path(cache_dir) / self.lang if cache_dir else None
        self.cache_days = float(cache_days)
        self.deadline = deadline
        self.requests = 0
        kw: dict[str, Any] = {"headers": {"User-Agent": user_agent(contact), "Accept": "application/json"}, "follow_redirects": True}
        if transport is not None:
            kw["transport"] = transport
        self.http = httpx.Client(**kw)

    def close(self) -> None:
        try:
            self.http.close()
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------------- cache

    def _path(self, kind: str, key: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{kind}-{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"

    def _cached(self, kind: str, key: str, stale: bool = False) -> Optional[dict]:
        p = self._path(kind, key)
        if p is None or not p.is_file():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if d.get("v") != _CACHE_VERSION:
            return None
        if not stale and time.time() - float(d.get("fetched_at") or 0) > self.cache_days * 86400:
            return None
        return d

    def _store(self, kind: str, key: str, data: dict) -> None:
        p = self._path(kind, key)
        if p is None:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"v": _CACHE_VERSION, "fetched_at": time.time(), **data}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
        except OSError as e:
            log.debug("reference cache not written: %s", e)

    # -------------------------------------------------------------- requests

    def _timeout(self) -> float:
        if self.deadline is None:
            return self.timeout_s
        left = self.deadline - time.monotonic()
        if left < 0.5:
            raise TimeoutError("the reference time is spent")
        return min(self.timeout_s, left)

    def get(self, params: dict) -> dict:
        self.requests += 1
        r = self.http.get(self.url, params={**params, "format": "json", "formatversion": "2"}, timeout=self._timeout())
        if r.status_code == 403:
            raise PermissionError(f"403 from {self.lang}.wikipedia.org: {r.text[:120]}")
        r.raise_for_status()
        return r.json()

    def validate(self, titles: list[str]) -> list[str]:
        """The proposed titles that are existing, non-disambiguation articles (redirects followed), in the given order."""
        titles = [t for t in titles if t][:3]
        if not titles:
            return []
        d = self.get({"action": "query", "titles": "|".join(titles), "redirects": 1, "prop": "pageprops", "ppprop": "disambiguation"})
        q = d.get("query") or {}
        found = [pg.get("title") for pg in q.get("pages") or [] if pg.get("title") and not pg.get("missing") and not pg.get("invalid") and "disambiguation" not in (pg.get("pageprops") or {})]
        back: dict[str, str] = {}
        for r in (q.get("normalized") or []) + (q.get("redirects") or []):
            back[r.get("to", "")] = back.get(r.get("from", ""), r.get("from", ""))
        order = {t: i for i, t in enumerate(titles)}
        found.sort(key=lambda t: order.get(back.get(t, t), order.get(t, len(order))))
        return list(dict.fromkeys(found))

    def search(self, query: str) -> list[tuple[str, int]]:
        d = self.get({"action": "query", "list": "search", "srsearch": query, "srlimit": 5, "srprop": "wordcount"})
        return [(x.get("title", ""), int(x.get("wordcount") or 0)) for x in (d.get("query") or {}).get("search") or [] if x.get("title")]

    def resolve(self, titles: list[str], topic: str) -> tuple[list[str], list[str]]:
        """(the article titles to fetch — at most two, the main first —, warnings). The proposed titles are validated;
        when none exists, each proposed title and the topic without its lead words are searched, and among the hits that
        share at least half of their query's words (not «(значения)») the one with the largest word count wins — the
        main article, not a stub («История ВКонтакте» → «ВКонтакте», not «VK Видео»); when no hit shares that much, the
        search's top hit when it shares a word with its query (a narrow topic's general article: «Рынок электромобилей в
        России» → «Электромобиль»)."""
        titles = [" ".join(t.replace("_", " ").split()) for t in titles if t and t.strip()][:3]
        key = json.dumps([RESOLVE_VERSION, titles, lead_free(topic)], ensure_ascii=False)
        hit = self._cached("resolve", key)
        # a cached resolution is used only when today's rules would keep it (no sibling of the topic among its titles)
        if hit is not None and hit.get("titles") and not any(sibling_title(t, topic) for t in hit["titles"]):
            return list(hit.get("titles") or []), []
        warnings: list[str] = []
        try:
            found = self.validate(titles)[:MAX_PAGES] if titles else []
            if not found:
                queries = list(dict.fromkeys([t for t in titles] + [lead_free(topic)]))
                queries = [q for q in queries if tokens(q)]
                best: list[tuple[int, int, int, str]] = []
                near: list[str] = []  # the search's own order: the most relevant hit sharing a word with its query
                with ThreadPoolExecutor(max_workers=max(1, min(4, len(queries)))) as ex:
                    results = list(ex.map(self._search_safe, queries))
                for q, hits in zip(queries, results):
                    want = tokens(lead_free(q)) or tokens(q)
                    need = max(1, math.ceil(len(want) / 2))
                    first = True
                    for title, words in hits:
                        if "(значения)" in title or "(disambiguation)" in title or sibling_title(title, topic):
                            continue
                        shared = len(tokens(title) & want)
                        if shared >= need:
                            # the most of the query's words, then the fewest words of its own (a qualifier the topic does
                            # not have narrows it to another subject: «Возобновляемая энергетика в России» → not «Ядерная
                            # энергетика России», gate 3 C), then the main article (the largest)
                            best.append((shared, -len(tokens(title) - want), words, title))
                        elif shared and first:
                            near.append(title)  # «Рынок электромобилей в России» → «Электромобиль»
                        first = False  # only the search's top hit may stand for a narrow topic
                if best:
                    found = [max(best)[3]]
                elif near:
                    found = [near[0]]
        except Exception as e:  # noqa: BLE001 - no reference: the writer writes from knowledge
            stale = self._cached("resolve", key, stale=True)
            kept = [t for t in (stale or {}).get("titles") or [] if not sibling_title(t, topic)]
            if kept:
                return kept, [f"reference: network failed, cached titles used ({str(e)[:80]})"]
            raise
        if found:
            self._store("resolve", key, {"titles": found})
        return found, warnings

    def _search_safe(self, q: str) -> list[tuple[str, int]]:
        try:
            return self.search(q)
        except Exception as e:  # noqa: BLE001
            log.info("reference search failed for %r: %s", q, e)
            return []

    def fetch(self, title: str) -> Optional[RefPage]:
        hit = self._cached("page", title)
        if hit is not None:
            return RefPage(title=hit.get("title") or title, url=hit.get("url") or "", revid=hit.get("revid"), timestamp=hit.get("timestamp"), text=hit.get("text") or "", cached=True)
        try:
            d = self.get({
                "action": "query", "prop": "extracts|revisions|info", "explaintext": 1, "exsectionformat": "wiki",
                "rvprop": "ids|timestamp", "inprop": "url", "redirects": 1, "titles": title,
            })
        except Exception:  # noqa: BLE001
            stale = self._cached("page", title, stale=True)
            if stale is not None:
                return RefPage(title=stale.get("title") or title, url=stale.get("url") or "", revid=stale.get("revid"), timestamp=stale.get("timestamp"), text=stale.get("text") or "", cached=True)
            raise
        pages = (d.get("query") or {}).get("pages") or []
        if not pages:
            return None
        p = pages[0]
        if p.get("missing") or not p.get("extract"):
            return None
        rev = (p.get("revisions") or [{}])[0]
        page = RefPage(title=p.get("title") or title, url=p.get("fullurl") or "", revid=rev.get("revid"), timestamp=rev.get("timestamp"), text=p.get("extract") or "")
        self._store("page", title, {"title": page.title, "url": page.url, "revid": page.revid, "timestamp": page.timestamp, "text": page.text})
        return page


def fetch_reference(
    titles: list[str], topic: str, *, lang: str = "ru", contact: str = "", kind: Optional[str] = None, limit: int = 12000,
    timeout_s: float = 6.0, cache_dir: Optional[Path] = None, cache_days: float = 7.0, deadline: Optional[float] = None,
    transport: Any = None,
) -> Optional[Reference]:
    """Resolve and fetch the topic's article(s) and cut them for the writer; None (with the reason in the result's
    warnings is not possible then — the caller logs it) when there is no reference. Never raises. A topic about a
    place («Рынок электромобилей в России»): when no article found names the place, the search's first hit that
    does («Автомобильная промышленность России») is the second page, and the cut puts the place's sections first."""
    t0 = time.monotonic()
    ref = Reference(lang=lang if lang in ("ru", "en") else "ru", proposed=list(titles))
    if not contact_ok(contact):
        ref.warnings.append("reference: no contact configured")
        return ref
    client = WikiClient(ref.lang, contact, timeout_s=timeout_s, cache_dir=cache_dir, cache_days=cache_days, transport=transport, deadline=deadline)
    try:
        found, w = client.resolve(titles, topic)
        ref.warnings.extend(w)
        if not found:
            ref.warnings.append("reference: no article found")
            return ref
        place = place_of(topic)
        focus = place[1] if place else None
        if focus and len(found) < MAX_PAGES and not any(focus in t.lower() for t in found):
            hits = client._search_safe(lead_free(topic))
            extra = next((t for t, _ in hits if focus in t.lower() and t not in found and "(значения)" not in t
                          and not sibling_title(t, topic)), None)
            if extra:
                found = [*found, extra]
        with ThreadPoolExecutor(max_workers=min(MAX_PAGES, len(found))) as ex:
            pages = list(ex.map(_fetch_safe(client, ref), found[:MAX_PAGES]))
        ref.pages = [p for p in pages if p is not None and p.text]
        if not ref.pages:
            ref.warnings.append("reference: the article could not be fetched")
            return ref
        ref.cut = cut_pages(ref.pages, limit, kind, focus)
        return ref
    except PermissionError as e:
        ref.warnings.append(f"reference: refused ({str(e)[:100]})")
        return ref
    except Exception as e:  # noqa: BLE001 - timeout, 5xx, no network: no reference
        name = "timeout" if "timeout" in type(e).__name__.lower() or isinstance(e, TimeoutError) else type(e).__name__
        ref.warnings.append(f"reference: {name} ({str(e)[:100]})")
        return ref
    finally:
        ref.requests = client.requests
        ref.seconds = round(time.monotonic() - t0, 2)
        client.close()


def subject_words(topic: str) -> str:
    """What a place topic is about without its lead words, its place and «рынок» («Рынок электромобилей в России» →
    «электромобилей»): the words a part's page is searched with."""
    core = lead_free(topic)
    where = place_of(topic)
    if where:
        core = re.sub(r"(?<![\wё])(?:в|во|на)\s+" + re.escape(where[0]) + r"(?![\wё])", " ", core)
        core = re.sub(r"(?<![\wё])(?:российск|московск|петербургск)\w*", " ", core, flags=re.I)
    core = re.sub(r"(?<![\wё])(?:рын(?:ок|ка|ке|ку|ком)|отрасл\w*|сфер\w*|индустри\w*)(?![\wё])", " ", core, flags=re.I)
    return " ".join(core.split())


def fetch_part_page(
    part: str, topic: str, known: list[str], *, lang: str = "ru", contact: str = "", timeout_s: float = 6.0,
    cache_dir: Optional[Path] = None, cache_days: float = 7.0, deadline: Optional[float] = None, transport: Any = None,
) -> Optional[RefPage]:
    """The article for a storyline part the topic's articles do not cover (gate 4 G4-9: nothing about charging in
    «Электромобиль» and «Автомобильная промышленность России» — «Зарядная станция для электромобилей» has a «Россия»
    section): the search's top hit for «<part> <subject>» («инфраструктура электромобилей») that is not a page already
    fetched, a sibling or a disambiguation. None on any failure (the part then gives its slide to a covered part)."""
    if not contact_ok(contact):
        return None
    subject = subject_words(topic)
    if not subject:
        return None
    query = f"{part.split()[0].lower()} {subject}"
    client = WikiClient(lang if lang in ("ru", "en") else "ru", contact, timeout_s=timeout_s, cache_dir=cache_dir, cache_days=cache_days,
                        transport=transport, deadline=deadline)
    try:
        hits = client._search_safe(query)
        title = next((t for t, _ in hits[:3] if t not in known and "(значения)" not in t and "(disambiguation)" not in t
                      and not sibling_title(t, topic) and tokens(t) & (tokens(query) | tokens(subject))), None)
        if title is None:
            return None
        page = client.fetch(title)
        return page if page is not None and page.text else None
    except Exception as e:  # noqa: BLE001 - no page: the part is left out
        log.info("part page for %r failed: %s", part, e)
        return None
    finally:
        client.close()


_ADJ_END_RE = re.compile(r"(?:ая|яя|ый|ий|ой|ое|ее|ые|ие)$")


def sibling_title(title: str, topic: str) -> bool:
    """The title names a sibling of the topic, not the topic: the same noun under another adjective («Ядерная
    энергетика России» for «Возобновляемая энергетика в России» — gate 3 C: the whole deck told nuclear power)."""
    tw = [w.lower() for w in _TOKEN_RE.findall(title or "")]
    pw = [w.lower() for w in _TOKEN_RE.findall(lead_free(topic) or "")]
    for i in range(1, len(tw)):
        noun = tw[i][:4]
        adj = tw[i - 1]
        if not _ADJ_END_RE.search(adj) or len(noun) < 4:
            continue
        for j in range(1, len(pw)):
            if pw[j][:4] == noun and _ADJ_END_RE.search(pw[j - 1]) and pw[j - 1][:4] != adj[:4]:
                return True
    return False


def _fetch_safe(client: WikiClient, ref: Reference):
    def run(title: str) -> Optional[RefPage]:
        try:
            return client.fetch(title)
        except Exception as e:  # noqa: BLE001
            ref.warnings.append(f"reference: {title}: {type(e).__name__} ({str(e)[:80]})")
            return None

    return run


__all__ = [
    "LEAD_WORDS_RE", "RefPage", "RefSentence", "Reference", "WikiClient", "contact_ok", "cut_pages", "cut_reference", "fetch_part_page",
    "drop_quotations", "fetch_reference", "focus_sections", "lead_free", "number_reference", "place_of", "sections",
    "sibling_title", "split_line", "tokens", "user_agent",
]
