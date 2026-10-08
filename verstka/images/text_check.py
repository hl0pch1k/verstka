"""No text in a slide picture. The text-to-image model draws any word, number or label it imagines on a screen, a
sign, a page or a chart — and draws it badly (pseudo-letters, broken digits): the vision model looks at every picture
it makes (skill `image_text_check`), and a picture with writing on it is drawn again from a stricter prompt — blank
screens, pictograms instead of labels. A picture that still carries writing after the last attempt never goes on a
slide: its place stays free and says why (configs/images.yaml `text_check`)."""

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


class TextCheck(BaseModel):
    """Output of the `image_text_check` skill: whether the picture has any writing on it and where."""

    text: str = "none"  # none | some
    what: str = ""

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


def check_text(path: Path, skills: Any, providers: Any) -> Optional[TextCheck]:
    """The vision model's look at one picture; None when there is no vision model or it does not answer (the picture
    is then taken as it is — the prompt's own rules stay its guard)."""
    if skills is None or providers is None or not getattr(providers, "has", lambda r: False)("vlm"):
        return None
    try:
        from verstka.analysis.classify import image_bytes_for_vlm

        res = skills.run("image_text_check", providers, {}, images=[image_bytes_for_vlm(Path(path), max_w=768)])
        return res.parsed
    except Exception as e:  # noqa: BLE001 - one unchecked picture never stops the deck
        log.info("picture text check failed: %s", str(e)[:160])
        return None
