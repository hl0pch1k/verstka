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
                 deadline: Optional[float] = None, limit: Optional[int] = None, deck_title: str = "") -> None:
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
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(self.cfg.get("concurrency", 3))), thread_name_prefix="t2i")
        self._futures: dict[tuple[str, str], Future] = {}
        self._subjects: dict[str, Optional[str]] = {}
        self._lock = threading.Lock()
        self._subject_lock = threading.Lock()
        self._describe_lock = threading.Lock()
        self.asked = 0

    # ---- asking
    def submit(self, ask: ImageAsk, aspect: str, *, seed: Optional[int] = None, fresh: bool = False) -> Future:
        """The picture for `ask` at `aspect`: one future per (ask, aspect) unless `fresh` (a new picture on the person's
        wish). Past the generation's limit of different pictures the future fails at once (the place stays free)."""
        k = (ask.key(), aspect)
        with self._lock:
            if not fresh and k in self._futures:
                return self._futures[k]
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
        if self.deadline is not None and self.deadline - time.monotonic() < 5:
            raise ImageError("no time left in the generation for a picture")
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
            res = self.provider.generate(prompt, aspect=aspect, seed=seed + k, deadline=self.deadline)
            if res.cost_rub is not None:
                cost = (cost or 0.0) + float(res.cost_rub)
            graded = P.grade(P.open_image(res.data), self.palette, strength)
            match = P.palette_match(graded, self.palette)
            name = f"{ask.key()}-{aspect.replace(':', 'x')}-{seed}" + (f"-{k + 1}" if k else "")
            path = self.folder / f"{name}.jpg"
            path.write_bytes(P.encode(graded, int(self.cfg.get("jpeg_quality", 88))))
            verdict = check_text(path, self.skills, self.providers, headline=ask.headline, subject=subject or ask.what, points=ask.slide_text) if attempts > 1 else None
            seen.append({"attempt": k + 1, "prompt": prompt, "text": None if verdict is None else verdict.text, "what": None if verdict is None else verdict.what,
                         "fits": None if verdict is None else verdict.fits, "flaws": None if verdict is None else verdict.flaws})
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
            if k + 1 < attempts and self.deadline is not None and self.deadline - time.monotonic() < 25:
                break  # no time for another picture
        if best is None:
            self._log_attempts(ask, aspect, seed, seen)
            raise PictureHasText(f"writing on every picture ({seen[-1]['what'] or 'text'}), {len(seen)} attempts")
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
