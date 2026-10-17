"""The prompt of a slide picture: what it shows (the author's words about the place, «экран панели управления
теплицей»; the person's wish on «Заменить изображение»), the slide and the deck it is for, the style the words call for
(a photo, an illustration, a screen), the template's palette in words, and what a slide picture never has (text,
logos). Phrases and styles: configs/images.yaml. With a text model the subject is written in English by the
`image_prompt` skill (one call for every picture of the generation); without it — or when the model fails — the
author's own words go in as they are (the open models read Russian prompts, if less precisely)."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from verstka.images.palette import Palette, palette_words

log = logging.getLogger(__name__)


class ImagePromptItem(BaseModel):
    id: str
    subject: str = Field(min_length=3)


class ImagePrompts(BaseModel):
    """The `image_prompt` skill's answer."""

    prompts: list[ImagePromptItem] = Field(default_factory=list)


@dataclass
class ImageAsk:
    """One picture to make: its place's description, the slide, the deck, the person's wish."""

    hint: str
    headline: str = ""
    deck: str = ""
    label: str = ""
    wish: Optional[str] = None
    subject_en: Optional[str] = None  # the model's English subject, when it wrote one
    frame: str = ""  # the composition of its frame on the slide: tall | wide | square | circle | background
    template_style: str = ""  # the style the template's own pictures are in (photo | illustration), when they say

    @property
    def what(self) -> str:
        """What the picture shows, in the author's words — the person's wish when the place has no description."""
        if (self.hint or "").strip():
            return self.hint.strip()
        if (self.wish or "").strip():
            return self.wish.strip()
        return (self.label if self.label and not re.match(r"^(?:изображение|мест[оа]\s)", self.label, re.I) else self.headline or self.label or "").strip()

    def key(self) -> str:
        """The same description (and wish) → the same picture: the three variants share their places' pictures even
        when their headlines differ. A place without a description is the slide's: its headline is its subject."""
        raw = "|".join([self.hint or "", self.label or "", "" if (self.hint or "").strip() else self.headline or "", self.wish or ""])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "images.yaml"


_CFG: dict[str, dict] = {}


def load_config(path: Optional[Path | str] = None) -> dict:
    p = Path(path) if path else default_config_path()
    key = str(p)
    if key not in _CFG:
        try:
            _CFG[key] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except OSError:
            _CFG[key] = {}
    return _CFG[key]


def style_of(text: str, cfg: dict, template_style: str = "") -> str:
    """The picture's style by the author's words: the first rule of configs/images.yaml `styles` that matches; else
    the style of the template's own pictures (its photos or its illustrations), else the default."""
    for rule in cfg.get("styles") or []:
        try:
            if re.search(str(rule.get("match", "")), text or "", re.I):
                return str(rule.get("style") or cfg.get("default_style") or "photo")
        except re.error:
            continue
    if template_style and template_style in ((cfg.get("prompt") or {}).get("styles") or {}):
        return template_style
    return str(cfg.get("default_style") or "photo")


def template_style(manifest) -> str:
    """The style the template's own pictures are in: «illustration» when its large pictures are mostly illustrations
    (drawn, 3D, cut out), «photo» when photos hold their own among them, "" when it has no large pictures."""
    kinds = [str(getattr(a, "kind", "") or "") for a in (getattr(manifest, "assets", None) or [])
             if (getattr(a, "width", 0) or 0) * (getattr(a, "height", 0) or 0) >= 300 * 300]
    photos, drawn = kinds.count("photo"), kinds.count("illustration")
    if photos + drawn < 2:
        return ""
    if drawn >= 6 and drawn >= 4 * photos:
        return "illustration"
    return "photo" if photos >= 2 else ""


def _clean(text: str, limit: int = 300) -> str:
    t = " ".join(str(text or "").replace("«", '"').replace("»", '"').split())
    t = re.sub(r"^(?:место\s+(?:под|для)\s+(?:изображени\w*|фото\w*|картинк\w*)\s*[:—-]\s*)", "", t, flags=re.I)
    return t[:limit].rstrip(" .,;:")


def build_prompt(ask: ImageAsk, pal: Optional[Palette], cfg: Optional[dict] = None, strict: int = 0) -> tuple[str, str]:
    """(the prompt, the style). Deterministic: the same ask and palette give the same prompt. `strict` — the attempt
    after a picture came out with writing on it (images/text_check.py): 1 — the wordless lead and the strict rules,
    a screen shown as shapes only; 2 — and the subject as a flat illustration, never a screen, a page or a sign."""
    cfg = cfg if cfg is not None else load_config()
    pcfg = cfg.get("prompt") or {}
    style = style_of(" ".join([ask.hint or "", ask.label or "", ask.wish or ""]), cfg, ask.template_style)
    scfg = pcfg.get("strict") or {}
    if strict >= 2:
        style = "illustration"
    subject = _clean(ask.subject_en or ask.what)
    if ask.wish and not ask.subject_en and (ask.hint or "").strip():
        subject = str(pcfg.get("wish", "{wish}. Subject: {subject}")).format(wish=_clean(ask.wish), subject=_clean(ask.hint))
    context = str(pcfg.get("context", "")).format(headline=_clean(ask.headline, 120) or "—", deck=_clean(ask.deck, 120) or "—")
    style_line = str((pcfg.get("styles") or {}).get(style, ""))
    if strict >= 1 and (scfg.get("styles") or {}).get(style):
        style_line = str(scfg["styles"][style])
    colors = palette_words(pal) if pal is not None else ""
    # the frame's composition (a bleed half of the slide is a tall picture, a circle keeps its subject in the middle)
    frame_line = str((pcfg.get("frames") or {}).get(ask.frame or "", "")) if ask.frame else ""
    template = str(pcfg.get("template", "{subject}. {context}. {style}. Colour palette: {colors}. {rules}."))
    if frame_line and "{frame}" not in template:
        template = template.replace("{style}.", "{style}. {frame}.", 1)
    rules = str(pcfg.get("rules", "No text"))
    if strict >= 1:
        template = str(scfg.get("lead", "Wordless picture.")) + " " + template
        rules = str(scfg.get("rules", rules))

    def compose(subj: str, ctx: str) -> str:
        text = template.format(subject=subj, context=ctx, style=style_line, colors=colors or "neutral", rules=rules, frame=frame_line)
        return re.sub(r"\.\s*\.", ".", re.sub(r"\s+", " ", text)).strip()

    text = compose(subject, context)
    # the host's limit on a prompt (Polza: 1000 characters): the slide's context goes first, then the end of the
    # subject — the style, the palette and the rules (no text in the picture) always stay
    limit = int(pcfg.get("max_chars", 1000) or 0)
    if limit and len(text) > limit:
        text = compose(subject, "")
        if len(text) > limit:
            keep = max(40, len(subject) - (len(text) - limit) - 1)
            subject = subject[:keep].rsplit(" ", 1)[0].rstrip(" ,.;:—-") or subject[:keep]
            text = compose(subject, "")
    return text, style


def english_subjects(asks: list[ImageAsk], deck: str, skills, providers) -> dict[str, str]:
    """The `image_prompt` skill: the subjects of every ask in English, in one call ({ask.key(): subject}). Empty when
    there is no text model or it fails — the prompts then carry the author's own words."""
    if not asks or skills is None or providers is None or not getattr(providers, "has", lambda r: False)("llm"):
        return {}
    items = [{"id": a.key(), "headline": _clean(a.headline, 120), "hint": _clean(a.hint or a.label or a.headline, 400), "wish": _clean(a.wish, 300) if a.wish else None} for a in asks]
    try:
        res = skills.run("image_prompt", providers, {"deck": _clean(deck, 160) or "—", "items": items})
        parsed: ImagePrompts = res.parsed
    except Exception as e:  # noqa: BLE001 - the author's words go in instead
        log.info("image_prompt skill failed: %s", e)
        return {}
    keys = {a.key() for a in asks}
    out = {}
    for p in parsed.prompts if parsed else []:
        s = " ".join(p.subject.split())
        if p.id in keys and 3 <= len(s) <= 400 and not re.search(r"[а-яё]{4,}", s, re.I):
            out[p.id] = s
    return out
