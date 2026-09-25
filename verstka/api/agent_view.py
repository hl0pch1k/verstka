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

# the forms a designer names, the way a person says them (slide kinds and chart types)
FORM_RU = {
    "title": "титульный слайд", "section": "разделитель", "agenda": "повестка", "bullets": "короткий список", "cards": "карточки",
    "two_column": "две колонки", "big_number": "одна большая цифра", "stat_row": "ряд ключевых цифр", "comparison": "сравнение",
    "timeline": "шкала времени", "process": "шаги", "table": "таблица", "chart": "диаграмма", "image_text": "картинка и текст",
    "team": "команда", "quote": "цитата", "code": "код", "mockup": "макет экрана", "thanks": "финальный слайд", "freeform": "свободная форма",
    "pie": "круговая диаграмма", "doughnut": "кольцевая диаграмма", "column": "столбчатая диаграмма", "bar": "горизонтальная диаграмма",
    "line": "линейный график", "area": "график с заливкой", "formula": "формула",
}


def form_ru(kind: Optional[str]) -> str:
    k = (kind or "").strip()
    return FORM_RU.get(k.lower(), k)


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
    message = " ".join(str(raw.get("message") or "").split())[:_MAX_MESSAGE]
    step = str(raw.get("step") or "").strip().lower()[:32]
    if not message or not step:
        return None
    variant = raw.get("variant")
    variant = str(variant).strip()[:32] if variant not in (None, "") else None
    return {"type": "agent", "step": step, "message": message, "slide": _as_int(raw.get("slide")), "variant": variant}


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
            job.emit(ev["message"], share, type="agent", step=ev["step"], slide=ev["slide"], variant=ev["variant"])
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


def normalize_alternatives(raw: Any) -> list[dict]:
    """The designer's other forms of a slide as {"kind", "label", "text"}: dicts ({kind, change}) or plain strings."""
    out = []
    for a in raw if isinstance(raw, list) else []:
        if isinstance(a, str):
            kind, text = None, _clean(a)
        elif isinstance(a, dict):
            # a chart alternative names its chart type when it has one («pie» says more than «chart»)
            kind = _clean(a.get("chart_type") or a.get("kind") or a.get("form") or a.get("type"), 40)
            text = _clean(a.get("change") or a.get("why") or a.get("note") or a.get("what") or a.get("description") or a.get("reason"))
        else:
            continue
        if kind or text:
            out.append({"kind": kind, "label": form_ru(kind) if kind else None, "text": text})
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
            "rationale": _clean(s.get("rationale")),
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
    log_lines = [s for s in (_clean(x) for x in ((outline or {}).get("agent_log") or [])) if s]
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
            label = a.get("label") or ""
            parts.append(f"{label} — {a['text']}" if label and a.get("text") else label or a.get("text") or "")
        lines.append("Другие формы, которые агент рассматривал: " + "; ".join(p.rstrip(".") for p in parts if p) + ".")
    notes = [e for e in critic if e.get("slide") == index]
    if notes:
        lines.append(" ".join(f"{STEP_RU.get(e['step'], e['step'])}: {_about_slide(e['message'])}." for e in notes[:4]))
    if design.get("takeaway"):
        lines.append(f"Вывод на слайде: «{design['takeaway']}».")
    return "\n".join(lines) or None


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


def describe_agent_work(agent: dict, strategy_title: str) -> str:
    """The agent's work on a variant in a few lines for the chat: the timeline by steps, or the log as is."""
    events = agent.get("events") or []
    if events:
        lines = []
        by_step: dict[str, list[dict]] = {}
        for e in events:
            by_step.setdefault(e["step"], []).append(e)
        for step in [*AGENT_STEPS, *[s for s in by_step if s not in AGENT_STEPS]]:
            evs = by_step.get(step)
            if not evs or step == "compile":  # the plan's assembly repeats what the designer said
                continue
            name = STEP_RU.get(step, step.capitalize())
            if step == "designer":
                # the slides that show data are the interesting ones: two of them as examples
                examples = ([e for e in evs if _VISUAL.search(e["message"])] or evs)[:2]
                head = f"продумал форму {ru_count(len(evs), 'слайда', 'слайдов', 'слайдов')}"
                lines.append(f"• {name}: {head}, например: " + "; ".join(_said(e) for e in examples) + ".")
            else:
                lines.append(f"• {name}: " + "; ".join(_said(e) for e in evs[:4]) + ("; …" if len(evs) > 4 else "") + ".")
        return f"Как агент работал над вариантом «{strategy_title}»:\n" + "\n".join(lines) + "\nВесь путь по шагам — в «Как работал агент»."
    log_lines = agent.get("log") or []
    if log_lines:
        shown = log_lines[:10]
        more = f"\n…и ещё {ru_count(len(log_lines) - 10, 'шаг', 'шага', 'шагов')} — весь журнал в «Как работал агент»." if len(log_lines) > 10 else ""
        return f"Как агент работал над вариантом «{strategy_title}»:\n" + "\n".join(f"• {s}" for s in shown) + more
    return f"Для варианта «{strategy_title}» журнал агента не записан: он собран до того, как агент начал вести журнал, или без модели."
