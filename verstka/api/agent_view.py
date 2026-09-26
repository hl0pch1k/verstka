"""The planning agent's work as the UI shows it (Agent v2).

The pipeline reports each step of the agent through its progress callback as an event
{"type": "agent", "step": "analyst"|"architect"|"designer"|"critic"|"revise"|"compile", "message": "<plain Russian>",
"slide": <int|None>, "variant": "<strategy|None>"} and writes the same messages into DeckOutline.agent_log. Here:
the progress adapter that turns those events into job events (the live timeline of the build screen), agent.json of a
generation (the structured timeline kept for the result screen), and the readers the payloads and the chat helper use.
Runs made before Agent v2 have none of it: every reader falls back to empty lists."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from verstka.ru import ru_count

log = logging.getLogger(__name__)

AGENT_STEPS = ("analyst", "architect", "designer", "critic", "revise", "compile")
STEP_RU = {"analyst": "Аналитик", "architect": "Архитектор", "designer": "Дизайнер", "critic": "Критик", "revise": "Правка", "compile": "Сборка плана"}
AGENT_FILE = "agent.json"
_MAX_MESSAGE = 400
_MAX_EVENTS = 1000

# the forms a designer names, the way a person says them: the slide kinds as the interface's tabs name them (web
# KIND_LABEL, lower case), the chart types by their chart
FORM_RU = {
    "title": "титул", "section": "раздел", "agenda": "повестка", "bullets": "список", "cards": "карточки",
    "two_column": "две колонки", "big_number": "большое число", "stat_row": "ряд чисел", "comparison": "сравнение",
    "timeline": "хронология", "process": "процесс", "table": "таблица", "chart": "диаграмма", "image_text": "картинка и текст",
    "team": "команда", "quote": "цитата", "code": "код", "mockup": "макет экрана", "thanks": "финал", "freeform": "другое",
    "pie": "круговая диаграмма", "doughnut": "кольцевая диаграмма", "column": "столбчатая диаграмма", "bar": "горизонтальная диаграмма",
    "line": "линейный график", "area": "график с заливкой", "formula": "формула",
}


def form_ru(kind: Optional[str]) -> str:
    k = (kind or "").strip()
    return FORM_RU.get(k.lower(), k)


# ---------------------------------------------------------------------------- the agent's words, cleaned

# the layout ids a model leaves in its reasoning → the words the interface uses (whole words, any case)
_TERMS = [
    (re.compile(r"(?<![A-Za-z_])big[_\s-]?numbers?(?![A-Za-z_])", re.I), "большое число"),
    (re.compile(r"(?<![A-Za-z_])stat[_\s-]?rows?(?![A-Za-z_])", re.I), "ряд чисел"),
    (re.compile(r"(?<![A-Za-z_])two[_\s-]?columns?(?![A-Za-z_])", re.I), "две колонки"),
    (re.compile(r"(?<![A-Za-z_])takeaways?(?![A-Za-z_])", re.I), "вывод"),
    (re.compile(r"(?<![A-Za-z_])headlines?(?![A-Za-z_])", re.I), "заголовок"),
    (re.compile(r"(?<![A-Za-z_])subtitles?(?![A-Za-z_])", re.I), "подзаголовок"),
    (re.compile(r"(?<![A-Za-z_])footnotes?(?![A-Za-z_])", re.I), "сноска"),
    (re.compile(r"(?<![A-Za-z_])bullets?(?![A-Za-z_])", re.I), "пункты"),
    (re.compile(r"(?<![A-Za-z_])callouts?(?![A-Za-z_])", re.I), "выноска"),
    (re.compile(r"(?<![А-Яа-яЁё])бриф(а|е|ом|у)?(?![А-Яа-яЁё])", re.I), "текст"),
    # the slide kinds a model may name in its reasoning («Форма cards позволяет…»)
    (re.compile(r"(?<![A-Za-z_])cards?(?![A-Za-z_])", re.I), "карточки"),
    (re.compile(r"(?<![A-Za-z_])charts?(?![A-Za-z_])", re.I), "диаграмма"),
    (re.compile(r"(?<![A-Za-z_])tables?(?![A-Za-z_])", re.I), "таблица"),
    (re.compile(r"(?<![A-Za-z_])timelines?(?![A-Za-z_])", re.I), "хронология"),
    (re.compile(r"(?<![A-Za-z_])comparisons?(?![A-Za-z_])", re.I), "сравнение"),
    (re.compile(r"(?<![A-Za-z_])image_text(?![A-Za-z_])", re.I), "картинка и текст"),
]
_SENTENCE_START = re.compile(r"(?:^|[.!?…]\s+|[«\"(]\s*)$")


def plain_terms(text: str) -> str:
    """The agent's words in the interface's: takeaway → вывод, headline → заголовок, bullets → пункты, big_number →
    большое число…, «бриф(а|е|ом|у)» → «текст(а|е|ом|у)». A capital stays where the original had one or a sentence
    starts."""
    if not text:
        return text
    out = text
    for rx, word in _TERMS:
        def repl(m: re.Match, word: str = word) -> str:
            rep = word + ((m.group(1) or "") if m.re.groups else "")
            if m.group(0)[:1].isupper() or _SENTENCE_START.search(m.string[: m.start()]):
                rep = rep[:1].upper() + rep[1:]
            return rep

        out = rx.sub(repl, out)
    return out


# «Форма ряд чисел позволяет…», «Формат две колонки позволяет…»: the form a reason starts with is quoted as a name, so
# the verb agrees with «Форма» («Форма «ряд чисел» позволяет…»)
_FORM_NAMES = r"большое число|ряд чисел|две колонки|карточки|пункты|список|диаграмма|таблица|хронология|сравнение|картинка и текст|цитата|повестка|процесс"
_FORM_LEAD = re.compile(rf"^Формат?\s+«?({_FORM_NAMES})»?(?=[\s,.])", re.I)


def tidy_form(text: str) -> str:
    """«Формат две колонки позволяет…» → «Форма «две колонки» позволяет…» (after plain_terms: «Форма big_number…» too)."""
    return _FORM_LEAD.sub(lambda m: f"Форма «{m.group(1).lower()}»", text, count=1) if text else text


_CUT_MIN = 180  # the old hard cuts ([:200]) left texts this long that stop mid-word
_TERMINAL = ".!?»)…"


def mend_cut(text: str) -> str:
    """A text cut mid-word or inside a quote, ended the way a person ends a cut sentence: back to the last whole word,
    no dangling «—;,:», the quote closed, «…» after it. A whole sentence is returned as is."""
    t = text.rstrip()
    if not t:
        return t
    unclosed = t.count("«") > t.count("»")
    if t[-1] in _TERMINAL:
        return t + ("»" if unclosed else "")
    if not unclosed and len(t) < _CUT_MIN:
        return t
    head = t.rsplit(None, 1)[0] if re.search(r"\s", t) else t
    head = re.sub(r"\s+[А-Яа-яЁё]{1,2}$", "", head)  # no dangling preposition or conjunction («… в»)
    head = head.rstrip("  —–-;,:«")
    return head + "…" + ("»" if head.count("«") > head.count("»") else "")


def clip_text(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word boundary (never mid-word) and ended like a cut sentence."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if not text[limit - 1].isspace() and re.search(r"\s", head):
        head = head.rsplit(None, 1)[0]
    head = head.rstrip(" \u00a0—–-;,:«")
    return head + "…" + ("»" if head.count("«") > head.count("»") else "")


# «две диаграммы: столбчатая диаграмма и столбчатая диаграмма» → «две столбчатые диаграммы»
_TWO_OF = {
    "круговая диаграмма": "две круговые диаграммы", "кольцевая диаграмма": "две кольцевые диаграммы",
    "столбчатая диаграмма": "две столбчатые диаграммы", "горизонтальная диаграмма": "две горизонтальные диаграммы",
    "линейный график": "два линейных графика", "диаграмма с областями": "две диаграммы с областями",
    "график с заливкой": "два графика с заливкой", "диаграмма": "две диаграммы",
}
_CHART_NAME = "|".join(sorted((re.escape(k) for k in _TWO_OF), key=len, reverse=True))
_TWO_CHARTS = re.compile(rf"две диаграммы:\s*({_CHART_NAME})\s+и\s+({_CHART_NAME})", re.I)
_REDONE = re.compile(r"^переделан\w*\s+по\s+замечаниям\s+критика\s*[—–:-]\s*", re.I)
_OLD_FORM_RU = {"ряд показателей": "ряд чисел", "таймлайн": "хронология", "большая цифра": "большое число", "шаги": "процесс"}
# the form where a designer's line names it: first, or after «— », and followed by «(n)», «,», «.» or the end
_OLD_FORMS = re.compile(r"(?:^|(?<=—\s))(ряд показателей|таймлайн|большая цифра|шаги)(?=\s*\(|[,.]|$)", re.I)
_FIELD_WORDS = r"заголовок|вывод|подзаголовок|сноска|пункты|выноска"
_FIELD_HEAD = re.compile(rf"(^|;\s*|,\s*)({_FIELD_WORDS})\s*:\s*(?=«)", re.I)


def _two_charts(m: re.Match) -> str:
    a, b = m.group(1).lower(), m.group(2).lower()
    return _TWO_OF[a] if a == b else f"{m.group(1)} и {m.group(2)}"


def _split_fix(text: str) -> tuple[str, Optional[str]]:
    """«problem → fix» at the first arrow outside «quotes» (a figure «300 → 330 ₽» inside a quote stays)."""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "«":
            depth += 1
        elif ch == "»":
            depth = max(0, depth - 1)
        elif ch == "→" and depth == 0:
            left, right = text[:i].strip(), text[i + 1 :].strip()
            if left and right:
                return left, right
    return text, None


_CUT_QUOTE = re.compile(r"«[^«»]*…»")
_CUT_LAST_FIELD = re.compile(r",\s*вывод\s*«[^«»]*…»$")


def _fix_text(fix: str) -> str:
    """The critic's «what to do»: «Заголовок: «…»; takeaway: «…»» → «Заголовок «…», вывод «…»». A fix that is only a cut
    quote («Маркетинговый бюджет…») says nothing and becomes empty; a cut last field («, вывод «Месячная выручка…»») goes."""
    fix = _FIELD_HEAD.sub(lambda m: ("" if not m.group(1) else ", ") + m.group(2) + " ", plain_terms(fix).strip())
    if _CUT_QUOTE.fullmatch(fix):
        return ""
    fix = _CUT_LAST_FIELD.sub("", fix)
    return fix[:1].upper() + fix[1:] if fix else fix


def _full_stop(text: str) -> str:
    text = text.rstrip(" ;,:—–-")
    return text if not text or text[-1] in ".!?…" else text + "."


def tidy_message(step: str, msg: str) -> tuple[str, Optional[str]]:
    """An agent event's text as the interface shows it: English field names and «бриф» in plain Russian, a text cut
    mid-word ended cleanly, the critic's «problem → fix» split in two (the fix is returned apart, None when there is
    none), «две диаграммы: X и X» said the way a person says it, no «Переделан по замечаниям критика —» in front of a
    revision (the step says it)."""
    text = mend_cut(" ".join(str(msg or "").split()))
    if not text:
        return "", None
    fix: Optional[str] = None
    if step == "critic":
        problem, said = _split_fix(text)
        if said:
            text, fix = _full_stop(problem), (_fix_text(said) or None)
    if step == "analyst":
        # «Модель добавила 0 рядов данных и 1 таблицу» (older runs): only what was added; nothing added — no line
        text = re.sub(r"(?<!\d)0\s+(?:рядов данных|таблиц)\s+и\s+", "", text)
        text = re.sub(r"\s+и\s+0\s+(?:рядов данных|таблиц)(?=[.\s]*$)", "", text)
        if re.match(r"(?i)модель добавила\s+0\s", text):
            return "", None
    if step in ("designer", "revise", "compile"):
        # older runs named the forms otherwise than the tabs («ряд показателей (3 числа)», «таймлайн (5)»)
        text = _OLD_FORMS.sub(lambda m: _OLD_FORM_RU[m.group(1).lower()] if m.group(1).islower() else _OLD_FORM_RU[m.group(1).lower()].capitalize(), text)
        text = _TWO_CHARTS.sub(_two_charts, text)
        stripped = _REDONE.sub("", text, count=1)
        if stripped != text and stripped:
            text = stripped[:1].upper() + stripped[1:]
    text = plain_terms(text)
    return clip_text(text, _MAX_MESSAGE), (clip_text(fix, _MAX_MESSAGE) if fix else None)


# ---------------------------------------------------------------------------- events


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalize_event(raw: Any) -> Optional[dict]:
    """An agent event of the contract, cleaned (step lower-case, message trimmed, slide an int or None), or None."""
    if not isinstance(raw, dict) or raw.get("type") != "agent":
        return None
    step = str(raw.get("step") or "").strip().lower()[:32]
    message, fix = tidy_message(step, str(raw.get("message") or ""))
    if not message or not step:
        return None
    if fix is None and raw.get("fix"):  # an event cleaned before (a job event, agent.json) keeps its fix
        fix = clip_text(_fix_text(" ".join(str(raw["fix"]).split())), _MAX_MESSAGE) or None
    variant = raw.get("variant")
    variant = str(variant).strip()[:32] if variant not in (None, "") else None
    ev = {"type": "agent", "step": step, "message": message, "slide": _as_int(raw.get("slide")), "variant": variant}
    if fix:
        ev["fix"] = fix
    return ev


def job_progress(job) -> Callable[..., None]:
    """The pipeline's progress callback for a job: plain messages («visual: rendered slide 3/10», with the job's share
    of work done) pass as before; an agent event (a dict, as the first argument or as `event=`) becomes a job event
    that carries its step, slide and variant, so the build screen can draw the agent's timeline."""

    def progress(msg: Any = "", frac: Any = None, *args: Any, **kwargs: Any) -> None:
        share = frac if isinstance(frac, (int, float)) and not isinstance(frac, bool) else None
        candidates = [msg, kwargs.get("event"), *(a for a in args if isinstance(a, dict))]
        ev = next((e for e in map(normalize_event, candidates) if e is not None), None)
        if ev is not None:
            if share is None:
                raw = next((c for c in candidates if isinstance(c, dict) and c.get("type") == "agent"), {})
                p = raw.get("progress")
                share = p if isinstance(p, (int, float)) and not isinstance(p, bool) else None
            extra = {"fix": ev["fix"]} if ev.get("fix") else {}
            job.emit(ev["message"], share, type="agent", step=ev["step"], slide=ev["slide"], variant=ev["variant"], **extra)
            return
        if isinstance(msg, dict):  # a dict that is not an agent event: its message, if it has one
            msg = str(msg.get("message") or "")
        if msg:
            job.emit(str(msg), share)

    return progress


def write_agent_file(gdir: Path, events: Iterable[dict]) -> Optional[Path]:
    """agent.json of a generation: the agent's timeline as the build screen saw it (step, slide, variant, message)."""
    rows = []
    for ev in events:
        e = normalize_event(ev)
        if e is None:
            continue
        t = ev.get("t")
        rows.append({k: v for k, v in e.items() if k != "type"} | ({"t": t} if isinstance(t, (int, float)) else {}))
    if not rows:
        return None
    path = Path(gdir) / AGENT_FILE
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps({"version": 1, "events": rows[-_MAX_EVENTS:]}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("agent.json not written: %s", e)
        tmp.unlink(missing_ok=True)
        return None
    return path


def read_agent_events(gdir: Path) -> list[dict]:
    """The events of agent.json (empty for runs made before Agent v2 or through the command line)."""
    path = Path(gdir) / AGENT_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("events") if isinstance(data, dict) else data
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            e = normalize_event({**row, "type": "agent"})
            if e is not None:
                e.pop("type")
                if isinstance(row.get("t"), (int, float)):
                    e["t"] = row["t"]
                out.append(e)
    return out


# ---------------------------------------------------------------------------- per variant


def _clean(text: Any, limit: int = 600) -> Optional[str]:
    s = " ".join(str(text or "").split())
    return s[:limit] if s else None


def _plain(text: Optional[str]) -> Optional[str]:
    return tidy_form(plain_terms(text)) if text else text


# «столбчатая диаграмма: График позволит…» (a chart type in front of the reason): the type is the alternative's name
_CHART_HEAD = re.compile(r"^((?:[а-яё]+\s+)?(?:диаграмма|график)(?:\s+с\s+[а-яё]+)?)\s*:\s*(.+)$", re.I | re.S)


def normalize_alternatives(raw: Any) -> list[dict]:
    """The designer's other forms of a slide as {"kind", "label", "text"}: dicts ({kind, change}) or plain strings."""
    out = []
    for a in raw if isinstance(raw, list) else []:
        if isinstance(a, str):
            kind, text = None, _plain(_clean(a))
        elif isinstance(a, dict):
            # a chart alternative names its chart type when it has one («pie» says more than «chart»)
            kind = _clean(a.get("chart_type") or a.get("kind") or a.get("form") or a.get("type"), 40)
            text = _plain(_clean(a.get("change") or a.get("why") or a.get("note") or a.get("what") or a.get("description") or a.get("reason")))
        else:
            continue
        label = form_ru(kind) if kind else None
        m = _CHART_HEAD.match(text or "")
        if m:
            label, text = m.group(1).lower(), m.group(2)[:1].upper() + m.group(2)[1:]
        if kind or text:
            out.append({"kind": kind, "label": label, "text": text})
    return out[:4]


def slide_design(outline: Optional[dict]) -> list[dict]:
    """Per slide of a variant: why the designer chose its form, the other forms it proposed, the conclusion and the
    footnote shown on it, and which slide of the brief it answers. Empty values for slides planned before Agent v2."""
    out = []
    for i, s in enumerate((outline or {}).get("slides") or [], 1):
        if not isinstance(s, dict):
            continue
        out.append({
            "index": i,
            "kind": s.get("kind"),
            "rationale": _plain(_clean(s.get("rationale"))),
            "alternatives": normalize_alternatives(s.get("alternatives")),
            "takeaway": _clean(s.get("takeaway")),
            "footnote": _clean(s.get("footnote")),
            "spec_ref": _as_int(s.get("spec_ref")),
        })
    return out


def variant_events(events: list[dict], strategy: str) -> list[dict]:
    """The events of one variant: the shared steps (analyst, architect, designer: variant None) and its own."""
    return [e for e in events if e.get("variant") in (None, "", strategy)]


def variant_agent(outline: Optional[dict], events: list[dict], strategy: str) -> dict:
    """What the agent did for a variant: its log (outline.agent_log), the structured timeline when the run kept one,
    and the critic's notes (structured events of the critic and the revision, or the log's «Критик…» lines)."""
    log_lines = [plain_terms(mend_cut(s)) for s in (_clean(x) for x in ((outline or {}).get("agent_log") or [])) if s]
    mine = variant_events(events, strategy)
    critic = [e for e in mine if e.get("step") in ("critic", "revise")]
    if not critic:
        critic = [{"step": "critic" if line.lower().startswith("критик") else "revise", "message": line, "slide": None, "variant": strategy}
                  for line in log_lines if line.lower().startswith(("критик", "правка"))]
    return {"log": log_lines, "events": mine, "critic": critic}


def _slide_key(design: dict, outline_slide: dict) -> Optional[tuple]:
    if design.get("spec_ref") is not None:
        return ("spec", design["spec_ref"])
    head = " ".join(str(outline_slide.get("headline") or "").lower().split())
    return ("head", head) if head else None


def link_alternatives(variants: list[dict]) -> None:
    """Marks an alternative form «used in variant X» when another variant shows the same slide (the same slide of the
    brief, or the same headline) in that form — the other variants are built from the designer's alternatives."""
    index: dict[tuple, list[tuple[str, str]]] = {}
    for v in variants:
        slides = ((v.get("outline") or {}).get("slides")) or []
        for d in v.get("design") or []:
            s = slides[d["index"] - 1] if 0 < d["index"] <= len(slides) and isinstance(slides[d["index"] - 1], dict) else {}
            key = _slide_key(d, s)
            if key is None:
                continue
            kinds = {str(s.get("kind") or "")}
            chart = ((s.get("content") or {}).get("chart") or {}) if isinstance(s.get("content"), dict) else {}
            if isinstance(chart, dict) and chart.get("type"):
                kinds.add(str(chart["type"]))
            for k in kinds:
                if k:
                    index.setdefault(key, []).append((v["strategy"], k))
    for v in variants:
        slides = ((v.get("outline") or {}).get("slides")) or []
        for d in v.get("design") or []:
            s = slides[d["index"] - 1] if 0 < d["index"] <= len(slides) and isinstance(slides[d["index"] - 1], dict) else {}
            key = _slide_key(d, s)
            for alt in d.get("alternatives") or []:
                kind = (alt.get("kind") or "").lower()
                used = sorted({st for st, k in index.get(key, []) if st != v["strategy"] and k.lower() == kind}) if key and kind else []
                alt["used_in"] = used


# ---------------------------------------------------------------------------- chat


def describe_slide_design(design: Optional[dict], critic: list[dict], index: int) -> Optional[str]:
    """«Почему так: …», the other forms and the critic's notes on this slide — None when the designer left nothing."""
    if not design:
        return None
    lines = []
    if design.get("rationale"):
        lines.append(f"Почему так: {design['rationale'].rstrip('.')}.")
    alts = [a for a in design.get("alternatives") or [] if a.get("label") or a.get("text")]
    if alts:
        parts = []
        for a in alts[:3]:
            label, text = a.get("label") or "", a.get("text") or ""
            # «Таблица позволит увидеть…» names the form itself: no «таблица — Таблица…»
            # one running sentence: every part in lower case («столбчатая диаграмма — график позволит…; таблица удобна…»)
            if label and text and text.lower().startswith(label.lower()) and not re.match(r"\w", text[len(label):]):
                parts.append(_lower_first(text))
            else:
                parts.append(f"{label} — {_lower_first(text)}" if label and text else _lower_first(label or text))
        lines.append("Другие формы: " + "; ".join(p.rstrip(".") for p in parts if p) + ".")
    notes = [e for e in critic if e.get("slide") == index]
    if notes:
        lines.append(" ".join(f"{STEP_RU.get(e['step'], e['step'])}: {_about_slide(e['message'])}." for e in notes[:4]))
    if design.get("takeaway"):
        lines.append(f"Вывод на слайде: «{design['takeaway']}».")
    return plain_terms("\n".join(lines)) or None


_SLIDE_PREFIX = re.compile(r"^слайд[ыа]?\s*\d+\s*[—–:.-]\s*", re.I)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if len(text) > 1 and text[1:2].islower() else text


def _about_slide(message: str) -> str:
    """«Слайд 3: подписи длиннее 4 слов.» said about slide 3 → «подписи длиннее 4 слов»."""
    return _lower_first(_SLIDE_PREFIX.sub("", message).rstrip("."))


_VISUAL = re.compile(r"диаграм|график|таблиц|формул|цифр", re.I)


def _said(e: dict) -> str:
    """An event in a sentence: «слайд 3: подписи сокращены» (the slide named once, lower case after the colon)."""
    msg = e["message"].rstrip(".")
    if e.get("slide") is None or (re.match(r"^слайд\w*\s*\d+", msg, re.I) and not _SLIDE_PREFIX.match(msg)):
        return _lower_first(msg)  # no slide, or the sentence names it itself («Слайд 2 переделан»)
    return f"слайд {e['slide']}: {_about_slide(msg)}"


_SKIPPED = re.compile(r"пропущен|не ответил|не запускал", re.I)


def describe_agent_work(agent: dict, strategy_title: str) -> str:
    """The agent's work on a variant in three short lines for the chat (what the analyst found, how many slides the
    designer thought through, what the critic said and what was redone); every step by slide is in the drawer's «Агент»,
    which the chat opens beside it."""
    events = agent.get("events") or []
    tail = "Все шаги по слайдам — во вкладке «Агент»."
    if events:
        of = lambda step: [e for e in events if e.get("step") == step]  # noqa: E731
        lines = []
        analyst = of("analyst")
        found = [e for e in analyst if re.match(r"(?i)нашёл", e["message"])] or analyst
        if found:
            lines.append(f"• Аналитик: {_lower_first(found[-1]['message'].rstrip('.'))}.")
        designer = of("designer")
        if designer:
            n = len({e["slide"] for e in designer if e.get("slide")}) or len(designer)
            # the analyst counts the text's slides and the designer adds the title slide in front: «5 слайдов» then
            # «6 слайдов» reads as a contradiction, «титул и форму 5 слайдов» says both
            in_text = re.search(r"(\d+)\s+слайд", found[-1]["message"]) if found else None
            cover = any(e.get("slide") == 1 and re.match(r"(?i)(обложка|титул)", e["message"]) for e in designer)
            if in_text and cover and int(in_text.group(1)) == n - 1:
                lines.append(f"• Дизайнер: продумал титул и форму {ru_count(n - 1, 'слайда', 'слайдов', 'слайдов')}.")
            else:
                lines.append(f"• Дизайнер: продумал форму {ru_count(n, 'слайда', 'слайдов', 'слайдов')}.")
        critic = of("critic")
        notes = [e for e in critic if e.get("slide") is not None]
        redone = len({e["slide"] for e in of("revise") if e.get("slide")})
        if notes or redone:
            parts = [ru_count(len(notes), "замечание", "замечания", "замечаний")] if notes else []
            if redone:
                parts.append(f"{ru_count(redone, 'слайд', 'слайда', 'слайдов')} {'переделан' if redone % 10 == 1 and redone % 100 != 11 else 'переделаны'}")
            lines.append("• Критик: " + ", ".join(parts) + ".")
        elif critic:
            skipped = next((e for e in critic if _SKIPPED.search(e["message"])), None)
            said = re.sub(r"(?i)^критик\w*\s*:?\s*", "", skipped["message"]).rstrip(".") if skipped else ""
            lines.append(f"• Критик: {_lower_first(said)}." if said else "• Критик: замечаний нет.")
        return plain_terms(f"Вариант «{strategy_title}»:\n" + "\n".join(lines) + "\n" + tail)
    log_lines = agent.get("log") or []
    if log_lines:
        return plain_terms(f"Вариант «{strategy_title}»:\n" + "\n".join(f"• {s}" for s in log_lines[:3]) + "\n" + tail)
    return f"Для варианта «{strategy_title}» журнал агента не записан: он собран до того, как агент начал вести журнал, или без модели."
