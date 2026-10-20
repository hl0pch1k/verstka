"""No text in a slide picture. The text-to-image model draws any word, number or label it imagines on a screen, a
sign, a page or a chart — and draws it badly (pseudo-letters, broken digits): the vision model looks at every picture
it makes (skill `image_text_check`), and a picture with writing on it is drawn again from a stricter prompt — blank
screens, pictograms instead of labels. A picture that still carries writing after the last attempt never goes on a
slide: its place stays free and says why (configs/images.yaml `text_check`). The same look grades how well the picture
fits its slide: one under `quality.min_fit` is drawn again, and the best clean one is kept."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

WHY_TEXT = "на картинках модель рисовала текст — место оставлено свободным, сгенерируйте ещё раз или вставьте своё изображение"


class PictureHasText(Exception):
    """Every attempt drew writing into the picture: the place stays free with `why`."""

    why = WHY_TEXT


WHY_MISFIT = "картинка не подошла к смыслу слайда — слайд оставлен без неё"


class PictureNotFitting(Exception):
    """No attempt showed what the slide means (the vision model's grade under quality.min_fit): no picture."""

    why = WHY_MISFIT


class TextCheck(BaseModel):
    """Output of the `image_text_check` skill: whether the picture has any writing on it and where, and how well it
    fits its slide (0–10: the asked subject, clear and natural; defects and symbols score low) with its main flaws."""

    text: str = "none"  # none | some
    what: str = ""
    fits: int = 10  # an answer without a grade (an older model reply) never rejects a picture
    flaws: str = ""

    @field_validator("fits", mode="before")
    @classmethod
    def _fits(cls, v: Any) -> int:
        try:
            return max(0, min(10, int(round(float(str(v).strip().split("/")[0])))))
        except (TypeError, ValueError):
            return 10

    @field_validator("flaws", mode="before")
    @classmethod
    def _flaws(cls, v: Any) -> str:
        return " ".join(str(v or "").split())[:200]

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        s = str(v if v is not None else "").strip().lower()
        if isinstance(v, bool):
            return "some" if v else "none"
        return "none" if s in ("", "none", "no", "нет", "false", "0", "clean", "без текста") else "some"

    @field_validator("what", mode="before")
    @classmethod
    def _what(cls, v: Any) -> str:
        return " ".join(str(v or "").split())[:200]

    @property
    def clean(self) -> bool:
        return self.text == "none"


def check_text(path: Path, skills: Any, providers: Any, *, headline: str = "", subject: str = "", points: str = "") -> Optional[TextCheck]:
    """The vision model's look at one picture (for the slide `headline`, asked to show `subject`); None when there is
    no vision model or it does not answer (the picture is then taken as it is — the prompt's own rules stay its
    guard)."""
    if skills is None or providers is None or not getattr(providers, "has", lambda r: False)("vlm"):
        return None
    try:
        from verstka.analysis.classify import image_bytes_for_vlm

        ctx = {"headline": " ".join((headline or "").split())[:160], "subject": " ".join((subject or "").split())[:400],
               "points": " ".join((points or "").split())[:500]}
        res = skills.run("image_text_check", providers, ctx, images=[image_bytes_for_vlm(Path(path), max_w=768)])
        return res.parsed
    except Exception as e:  # noqa: BLE001 - one unchecked picture never stops the deck
        log.info("picture text check failed: %s", str(e)[:160])
        return None
