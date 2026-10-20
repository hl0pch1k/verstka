"""The pictures of a build asked right after the plan, beside the layout (pipeline/generate.py): the live lecture of
20.10 asked its pictures only after the first variant was laid out and looked at, its second chance started on the
4th minute, and the vision model's checks had no time left — the deck got a turbine nobody had checked. Now every
place of the plan (the person's and Verstka's own) is asked at once (`ImageMaker.prefetch`: drawn square, the place's
own ask after the layout gets it cropped to its frame), and a picture of Verstka's own the vision model rejected hands
its place to the next most concrete slide at once (planning/pictures.py `second_chance`) while the variants are still
being laid out — within the build's limit of attempts (`ImageMaker.attempts`) and SECOND_CHANCES slides."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Optional

from verstka.images.fill import slide_points
from verstka.images.places import is_own
from verstka.images.prompt import ImageAsk
from verstka.images.text_check import PictureNotFitting

log = logging.getLogger(__name__)

EARLY_ASPECT = "1:1"  # a square picture crops to a strip, a card or a circle around its subject (squarer_tall)


@dataclass
class Early:
    index: int  # the slide's position in the plan (0-based)
    outline_id: str
    spec_ref: Optional[int]
    hint: str
    ask: ImageAsk
    future: Future
    second: bool = False  # it took the place of a rejected picture
    state: str = "pending"  # pending | ok | failed
    handled: bool = False


class EarlyPictures:
    """The plan's pictures asked at once and the second chance started as soon as a picture misses its slide."""

    def __init__(self, maker, outline, *, need: int, second_max: int, deck_title: str = "") -> None:
        self.maker = maker
        self.outline = outline.model_copy(deep=True)  # its places mark the slides taken by the second chance too
        self.need = need
        self.second_max = second_max
        self.deck_title = deck_title or getattr(outline, "title", "") or ""
        self.items: list[Early] = []
        self.tried: set[str] = set()
        self.picks: list[tuple[Optional[int], int, str]] = []  # (spec_ref, position, description) of the second chance
        self.declined = ""  # why no (more) second chance was started
        self._lock = threading.RLock()

    # ---- asking
    def start(self) -> list[Early]:
        """Every place of the plan that gets a picture, asked now."""
        from verstka.ingest.deck_text import is_source_hint
        from verstka.planning.pictures import AUTO_LABEL

        for k, s in enumerate(self.outline.slides):
            c = s.content
            if not c.photo_slot or is_own(c.photo_slot, bool(c.photo_own)) or is_source_hint(c.photo_hint or ""):
                continue
            self._ask(k, s, c.photo_hint or "", c.photo_slot, frame="tall" if c.photo_slot == AUTO_LABEL else "square")
        return list(self.items)

    def _ask(self, k: int, s: Any, hint: str, label: str, *, frame: str, second: bool = False) -> Early:
        ask = ImageAsk(hint=hint, headline=s.headline or "", deck=self.deck_title, label=label, frame=frame,
                       slide_text=slide_points(self.outline, s.id))
        fut = self.maker.prefetch(ask, EARLY_ASPECT)
        it = Early(k, s.id, s.spec_ref, hint, ask, fut, second=second)
        with self._lock:
            self.items.append(it)
        fut.add_done_callback(lambda f, it=it: self._done(it))
        return it

    # ---- the second chance
    def _done(self, it: Early) -> None:
        try:
            self._handle(it)
        except Exception:  # noqa: BLE001 - the build goes on with the pictures it has
            log.warning("early second chance failed", exc_info=True)

    def _handle(self, it: Early) -> None:
        from verstka.planning.pictures import AUTO_LABEL, second_chance

        f = it.future
        if not f.done():
            return
        with self._lock:
            if it.handled:
                return
            it.handled = True
            exc = None if f.cancelled() else f.exception()
            it.state = "ok" if (exc is None and not f.cancelled()) else "failed"
            if not isinstance(exc, PictureNotFitting):
                return  # (no writing-free picture, no time, the limit spent: no other slide is tried for it)
            self.tried.add(it.outline_id)
            for x in self.items:  # (the others done meanwhile: their callbacks may not have run yet)
                if x.state == "pending" and x.future.done():
                    x.state = "ok" if (not x.future.cancelled() and x.future.exception() is None) else "failed"
            alive = sum(1 for x in self.items if x.state in ("pending", "ok"))
            if alive >= self.need:
                return
            if sum(1 for x in self.items if x.second) >= self.second_max:
                self.declined = "second chances spent"
                return
            left = self.maker.budget_left()
            if left is not None and left <= 0:
                # the limit is spent: the feed says the pictures did not pass the check (pipeline/generate.py)
                self.maker.budget_hit = True
                self.declined = "the limit of attempts is spent"
                return
            got = second_chance(self.outline, self.tried, 1)
            if not got:
                self.declined = "no other slide"
                return
            k, hint = got[0]
            host = self.outline.slides[k]
            host.content.photo_slot, host.content.photo_hint, host.content.photo_own = AUTO_LABEL, hint, False
            self.picks.append((host.spec_ref, k, hint))
        self._ask(k, host, hint, AUTO_LABEL, frame="tall", second=True)
        log.info("picture of slide %d rejected: slide %d tried at once", it.index + 1, k + 1)

    def sync(self) -> None:
        """Every picture already done handled (a future's callback may still be running when the export looks)."""
        for it in list(self.items):
            if it.future.done():
                self._handle(it)

    def state_of(self, hint: str) -> Optional[str]:
        """pending | ok | failed for the picture asked with `hint`, None when none was."""
        with self._lock:
            it = next((x for x in self.items if x.hint == hint), None)
            return it.state if it is not None else None

    def slides(self) -> list[int]:
        """The plan's slide numbers (1-based) asked so far."""
        with self._lock:
            return [x.index + 1 for x in self.items]
