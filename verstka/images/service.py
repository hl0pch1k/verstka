"""The pictures of one generation: asked side by side (configs/images.yaml `concurrency`), each once — the three
variants ask for the same place's picture and share it —, graded to the template's palette, kept in the generation's
images/ folder (images/<key>-<aspect>.jpg and .json with the prompt, the model, the seed)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from verstka.images import palette as P
from verstka.images.prompt import ImageAsk, build_prompt, english_subjects, load_config, template_style, too_close
from verstka.images.providers import ImageError
from verstka.images.text_check import PictureHasText, PictureNotFitting, check_text

log = logging.getLogger(__name__)

# a picture Verstka chose itself that the build's limit of attempts left undrawn (its place goes, the slide is laid out
# without it; the feed says so once — pipeline/generate.py)
WHY_LIMIT = "картинки не прошли проверку соответствия — лимит попыток изображений на сборку исчерпан"
DRAW_S = 12.0  # an attempt starts only while this long is left before the drawing deadline (Z-Image draws in ~10 s)


def is_auto(ask: ImageAsk) -> bool:
    """A picture Verstka chose itself (planning/pictures.py AUTO_LABEL, no wish of the person's): it counts against the
    build's limit of attempts; the person's own asks never do."""
    from verstka.planning.pictures import AUTO_LABEL

    return ask.label == AUTO_LABEL and not (ask.wish or "").strip()


@dataclass
class Made:
    """A picture made for an ask at an aspect ratio."""

    key: str
    aspect: str
    path: str  # the graded picture (JPEG)
    prompt: str
    style: str
    subject_by: str  # "model" — the text model wrote the subject in English; "author" — the author's words
    model: str
    model_label: str
    seed: int
    palette_match: float
    seconds: float
    cost_rub: Optional[float] = None  # what the picture cost (Polza's usage.cost_rub), every attempt counted
    attempts: int = 1  # pictures drawn for it: the ones before had writing on them (text_check)
    text_checked: bool = False  # the vision model looked at it and saw no writing
    fits: Optional[int] = None  # the vision model's grade of how well it fits its slide (0–10), None: not looked at

    def public(self) -> dict:
        return asdict(self)


def seed_of(key: str, aspect: str, salt: str = "") -> int:
    return int(hashlib.sha256(f"{key}|{aspect}|{salt}".encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647


class ImageMaker:
    def __init__(self, provider, manifest, folder: Path, *, cfg: Optional[dict] = None, skills: Any = None, providers: Any = None,
                 deadline: Optional[float] = None, limit: Optional[int] = None, deck_title: str = "", attempts: Optional[int] = None,
                 checks_end: Optional[float] = None) -> None:
        """`deadline`: no attempt is drawn past it (time.monotonic()); `checks_end`: when the vision model's checks of
        the pictures end (`providers` are bound to it) — the export waits for the pictures until then. `attempts`: the
        build's limit of the image model's calls for the pictures Verstka chose itself (`is_auto`; the person's own asks
        come on top of it), None — no limit."""
        self.provider = provider
        self.cfg = cfg if cfg is not None else load_config()
        self.palette = P.palette_of(manifest)
        self.template_style = template_style(manifest)  # a picture the author's words leave open: in the template's style
        self.folder = Path(folder)
        self.skills = skills
        self.providers = providers
        self.deadline = deadline
        self.limit = int(limit if limit is not None else self.cfg.get("max_per_generation", 8))
        self.deck_title = deck_title
        self.checks_end = checks_end if checks_end is not None else deadline
        self.attempts = attempts
        self.auto_used = 0  # the image model's calls for Verstka's own pictures so far
        self.budget_hit = False  # an attempt (or a second chance) was refused: the limit is spent
        self.log: list[dict] = []  # every attempt: when it was drawn and checked, its grade (run_manifest «pictures»)
        self._early: dict[str, Future] = {}  # pictures asked right after the plan, by their ask's key
        self.first_asked: Optional[float] = None  # when the first picture was asked (time.monotonic())
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(self.cfg.get("concurrency", 3))), thread_name_prefix="t2i")
        self._futures: dict[tuple[str, str], Future] = {}
        self._subjects: dict[str, Optional[str]] = {}
        self._lock = threading.Lock()
        self._subject_lock = threading.Lock()
        self._describe_lock = threading.Lock()
        self.asked = 0

    # ---- asking
    def budget_left(self) -> Optional[int]:
        """Attempts left for Verstka's own pictures (None: no limit)."""
        with self._lock:
            return None if self.attempts is None else max(0, self.attempts - self.auto_used)

    def _take(self, ask: ImageAsk) -> bool:
        """One attempt of the build's limit for a picture Verstka chose itself; False — the limit is spent."""
        if self.attempts is None or not is_auto(ask):
            return True
        with self._lock:
            if self.auto_used >= self.attempts:
                self.budget_hit = True
                return False
            self.auto_used += 1
            return True

    def prefetch(self, ask: ImageAsk, aspect: str, *, seed: Optional[int] = None) -> Future:
        """The picture of a place asked right after the plan, before the slide is laid out (pipeline/generate.py): the
        place's own ask later (`submit`, in its frame's proportions) gets this picture — cropped to its frame — unless
        the frame is the slide's background (a picture under the text is composed for it)."""
        fut = self.submit(ask, aspect, seed=seed)
        with self._lock:
            self._early.setdefault(ask.key(), fut)
        return fut

    def submit(self, ask: ImageAsk, aspect: str, *, seed: Optional[int] = None, fresh: bool = False) -> Future:
        """The picture for `ask` at `aspect`: one future per (ask, aspect) unless `fresh` (a new picture on the person's
        wish); the picture asked for the same place right after the plan (`prefetch`) serves any frame but a
        background. Past the generation's limit of different pictures the future fails at once (the place stays free)."""
        k = (ask.key(), aspect)
        with self._lock:
            if self.first_asked is None:
                self.first_asked = time.monotonic()
            if not fresh and k in self._futures:
                return self._futures[k]
            early = self._early.get(ask.key())
            if not fresh and early is not None and ask.frame != "background":
                self._futures[k] = early
                return early
            if not fresh and len({key for key, _ in self._futures}) >= self.limit and ask.key() not in {key for key, _ in self._futures}:
                f: Future = Future()
                f.set_exception(ImageError(f"more than {self.limit} pictures in one generation"))
                return f
            self.asked += 1
            fut = self._pool.submit(self._make, ask, aspect, seed)
            if not fresh:
                self._futures[k] = fut
            return fut

    def make(self, ask: ImageAsk, aspect: str, *, seed: Optional[int] = None) -> Made:
        """One picture now (the person's «Сгенерировать другое»)."""
        return self._make(ask, aspect, seed)

    def close(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    # ---- making
    def _subject(self, ask: ImageAsk) -> Optional[str]:
        k = ask.key()
        with self._subject_lock:
            if k in self._subjects:
                return self._subjects[k]
        # one description at a time (a few seconds each; the pictures themselves are still drawn side by side): each
        # one sees the subjects written before it, so the deck never gets the same scanner twice (live runs of 20.10)
        with self._describe_lock:
            with self._subject_lock:
                if k in self._subjects:
                    return self._subjects[k]
            return self._describe(ask, k)

    def _describe(self, ask: ImageAsk, k: str) -> Optional[str]:
        with self._subject_lock:
            others = [v for v in self._subjects.values() if v]  # the deck's pictures described so far: never the same again
        got = english_subjects([ask], self.deck_title or ask.deck, self.skills, self.providers, others=others).get(k)
        twin = next((o for o in others if got and too_close(got, o)), None)
        if twin is not None:
            # the deck already has that picture (two phones with app tiles in one deck — jury 20.10, round 4): asked
            # once more for another main object
            log.info("picture %s repeats another of the deck: described again", k)
            wish = f"Another main object than this picture the deck already has: {twin[:200]}"
            again = english_subjects([ImageAsk(**{**asdict(ask), "wish": wish})], self.deck_title or ask.deck, self.skills, self.providers, others=others)
            got = next(iter(again.values()), None) or got
        with self._subject_lock:
            self._subjects[k] = got
        return got

    def _refined(self, ask: ImageAsk, subject: Optional[str], flaws: str) -> Optional[str]:
        """The description written again after a picture that did not fit its slide (the vision model's flaws)."""
        with self._subject_lock:
            others = [v for v in self._subjects.values() if v and v != subject]
        wish = (f"The picture drawn from «{(subject or '')[:200]}» came out wrong: {flaws or 'it does not show the slide'}. "
                "Describe the same meaning more simply and concretely: one clear object or scene a viewer recognises at once")
        got = english_subjects([ImageAsk(**{**asdict(ask), "wish": wish})], self.deck_title or ask.deck, self.skills, self.providers, others=others)
        return next(iter(got.values()), None)

    def _make(self, ask: ImageAsk, aspect: str, seed: Optional[int]) -> Made:
        if self.deadline is not None and self.deadline - time.monotonic() < min(5.0, DRAW_S):
            raise ImageError("no time left in the generation for a picture")
        left = self.budget_left()
        if left is not None and left <= 0 and is_auto(ask):
            # (not even described: the text model's call would be for a picture that is never drawn)
            self.budget_hit = True
            err = ImageError(f"the build's limit of {self.attempts} picture attempts is spent")
            err.why = WHY_LIMIT
            raise err
        began = time.monotonic()  # (the description by the text model comes first)
        subject = self._subject(ask)
        from verstka.planning.pictures import AUTO_LABEL

        if subject is None and ask.label == AUTO_LABEL and not ask.wish:
            # a place Verstka chose: its «description» is the slide's heading — the image model writes it across the
            # picture; without the text model's description the place stays free and says why
            err = ImageError("the text model gave no description of the picture")
            err.why = "описание картинки не составлено (модель текста не ответила) — место оставлено свободным"
            raise err
        # one deck title for every variant's picture (the key leaves it out: the variants share the picture)
        ask2 = ImageAsk(**{**asdict(ask), "subject_en": subject, "deck": self.deck_title or ask.deck, "template_style": ask.template_style or self.template_style})
        seed = seed if seed is not None else seed_of(ask.key(), aspect)
        tc = self.cfg.get("text_check") or {}
        attempts = max(1, int(tc.get("attempts", 3))) if tc.get("enabled", True) else 1
        qc = self.cfg.get("quality") or {}
        min_fit = int(qc.get("min_fit", 6)) if qc.get("enabled", True) else 0
        strength = float((self.cfg.get("palette") or {}).get("strength", 0.3))
        self.folder.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        cost: Optional[float] = None
        seen: list[dict] = []
        best: Optional[tuple[int, Path, str, str, float, str, Any]] = None  # (fits, path, prompt, style, match, name, res)
        strict = 0
        misfits = 0
        max_misfits = max(1, int(qc.get("max_misfits", 2)))
        for k in range(attempts):
            # a picture with writing on it is drawn again from a stricter prompt; a clean one that fits its slide badly
            # (the vision model's grade under quality.min_fit: another subject, deformed hands, a symbol) is drawn again
            # from the same prompt (the host takes no seed: the same prompt draws a new picture too)
            prompt, style = build_prompt(ask2, self.palette, self.cfg, strict=strict)
            if not self._take(ask):
                # the build's limit of attempts for Verstka's own pictures is spent (configs: minimum × 2): no more
                # money on a slide the image model keeps missing
                log.info("picture %s: the build's limit of %s attempts is spent", ask.key(), self.attempts)
                break
            entry = {"key": ask.key(), "headline": (ask.headline or "")[:80], "auto": is_auto(ask), "attempt": k + 1, "began": began, "start": time.monotonic()}
            res = self.provider.generate(prompt, aspect=aspect, seed=seed + k, deadline=self.deadline)
            entry["drawn"] = time.monotonic()
            if res.cost_rub is not None:
                cost = (cost or 0.0) + float(res.cost_rub)
            graded = P.grade(P.open_image(res.data), self.palette, strength)
            match = P.palette_match(graded, self.palette)
            name = f"{ask.key()}-{aspect.replace(':', 'x')}-{seed}" + (f"-{k + 1}" if k else "")
            path = self.folder / f"{name}.jpg"
            path.write_bytes(P.encode(graded, int(self.cfg.get("jpeg_quality", 88))))
            verdict = check_text(path, self.skills, self.providers, headline=ask.headline, subject=subject or ask.what, points=ask.slide_text) if attempts > 1 else None
            unchecked = bool(verdict is not None and verdict.unchecked)
            entry.update(checked=time.monotonic(), fits=None if verdict is None or unchecked else verdict.fits, unchecked=unchecked,
                         text=None if verdict is None or unchecked else verdict.text)
            with self._lock:
                self.log.append(entry)
            seen.append({"attempt": k + 1, "prompt": prompt, "text": None if verdict is None or unchecked else verdict.text, "what": None if verdict is None else verdict.what,
                         "fits": None if verdict is None or unchecked else verdict.fits, "flaws": None if verdict is None else verdict.flaws, "unchecked": unchecked})
            if verdict is None or verdict.clean:
                fits = 10 if verdict is None else verdict.fits
                if best is None or fits > best[0]:
                    if best is not None:
                        best[1].unlink(missing_ok=True)
                    best = (fits, path, prompt, style, match, name, res)
                else:
                    path.unlink(missing_ok=True)
                if fits >= min_fit:
                    break
                misfits += 1
                if misfits >= max_misfits:
                    break  # two pictures that miss the slide's meaning: no picture rather than a wrong one
                log.info("picture %s fits its slide %d/10 (%s): described again and drawn again", name, fits, verdict.flaws if verdict else "")
                if subject is not None and self.skills is not None:
                    better = self._refined(ask, subject, verdict.flaws if verdict else "")
                    if better:
                        subject = better
                        ask2 = ImageAsk(**{**asdict(ask2), "subject_en": better})
            else:
                log.info("picture %s has writing (%s): drawn again", name, verdict.what or "text")
                path.unlink(missing_ok=True)
                strict += 1
            if k + 1 < attempts and self.deadline is not None and self.deadline - time.monotonic() < DRAW_S:
                break  # no time for another picture (and its check) before the drawing deadline
        if best is None and not seen:
            err = ImageError(f"the build's limit of {self.attempts} picture attempts is spent")
            err.why = WHY_LIMIT
            raise err
        if best is None:
            self._log_attempts(ask, aspect, seed, seen)
            raise PictureHasText(f"writing on every picture ({seen[-1]['what'] or 'text'}), {len(seen)} attempts")
        if min_fit and ask.label == AUTO_LABEL and not ask.wish and seen and all(c.get("unchecked") for c in seen):
            # a picture Verstka chose itself whose meaning nobody could check (the vision model did not answer — the
            # generation's model time spent; the live lecture of 20.10 got a turbine for «скорость изменения»): left out
            best[1].unlink(missing_ok=True)
            raise PictureNotFitting("the picture's meaning was not checked (the vision model did not answer)")
        if min_fit and best[0] < min_fit:
            # the vision model saw the slide's meaning in none of them (a sail and a palm for «касательная» — jury 20.10,
            # round 4): the place goes, the slide is laid out without it
            try:
                best[1].replace(best[1].with_name(best[1].stem + "-rejected.jpg"))  # kept for a look, never placed
            except OSError:
                best[1].unlink(missing_ok=True)
            self._log_attempts(ask, aspect, seed, seen)
            raise PictureNotFitting(f"no picture fits the slide ({best[0]}/10: {seen[-1].get('flaws') or 'another subject'}), {len(seen)} attempts")
        fits, path, prompt, style, match, name, res = best
        made = Made(
            key=ask.key(), aspect=aspect, path=str(path), prompt=prompt, style=style, subject_by="model" if subject else "author",
            model=res.model, model_label=res.label, seed=int(seed), palette_match=match, seconds=round(time.monotonic() - t0, 2), cost_rub=cost,
            attempts=len(seen), text_checked=any(c["text"] == "none" for c in seen), fits=None if all(c["fits"] is None for c in seen) else fits,
        )
        try:
            (self.folder / f"{name}.json").write_text(json.dumps({**made.public(), "hint": ask.hint, "headline": ask.headline, "wish": ask.wish, "palette": P.describe(self.palette), "checks": seen}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        log.info("picture %s (%s) by %s in %.1fs, palette match %.2f, %d attempt(s)", name, style, res.label, made.seconds, match, len(seen))
        return made

    def _log_attempts(self, ask: ImageAsk, aspect: str, seed: int, seen: list[dict]) -> None:
        try:
            name = f"{ask.key()}-{aspect.replace(':', 'x')}-{seed}-rejected"
            (self.folder / f"{name}.json").write_text(json.dumps({"hint": ask.hint, "headline": ask.headline, "checks": seen}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def timeline(maker: Optional["ImageMaker"], t_start: float) -> dict:
    """The pictures' attempts for run_manifest.json: when the first was drawn and the last checked (seconds from the
    generation's start), how many the image model drew (Verstka's own against the build's limit) and each one's grade."""
    if maker is None:
        return {}
    with maker._lock:
        log_ = [dict(e) for e in maker.log]
    rel = lambda t: round(float(t) - t_start, 1) if t is not None else None  # noqa: E731
    rows = [{"slide": e.get("headline"), "auto": e.get("auto"), "attempt": e.get("attempt"), "began_s": rel(e.get("began")), "start_s": rel(e.get("start")),
             "drawn_s": rel(e.get("drawn")), "checked_s": rel(e.get("checked")), "fits": e.get("fits"), "unchecked": e.get("unchecked"),
             "text": e.get("text")} for e in sorted(log_, key=lambda e: e.get("start") or 0)]
    return {
        "attempts": len(rows), "auto_attempts": maker.auto_used, "attempts_limit": maker.attempts, "limit_spent": maker.budget_hit,
        "first_asked_s": rel(maker.first_asked),
        "first_start_s": rows[0]["start_s"] if rows else None, "last_checked_s": max((r["checked_s"] or 0) for r in rows) if rows else None,
        "deadline_s": rel(maker.deadline), "checks_end_s": rel(maker.checks_end), "tries": rows,
    }
