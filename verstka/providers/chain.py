"""Fallback chain: one role served by several open models, tried in order.

Free hosts of open models get congested for hours («temporarily rate-limited upstream»), a paid model answers 402
until the account is topped up, a model id disappears. The chain asks its links in turn and returns the first valid
answer. Every link but the last is asked with `fail_fast`: whatever goes wrong, the next link answers at once; the last
link keeps the short pause on congestion and the backoff of a single provider. A link on hold (status.py) is skipped
without a request, a link without an API key ("off") is skipped silently; a chain with exactly one link that has a
key calls it as a single provider (its own attempts and waits, no long holds). When at least one link failed only
because of congestion, 5xx / timeouts or a per-minute cap, every other failed link is on hold anyway (402, 404,
401/403, spent quota) and at least 30 s of the generation's budget remain, the chain makes one more pass after a
3-5 s pause; a failure that opens no hold (invalid JSON, a plain 4xx) would only repeat, so it rules the pass out.
When every link is still on hold after that pause, but the earliest hold ends within 30 s (a per-minute cap — Cloud.ru's
429 ModelArts.81114, a Retry-After, a congestion hold about to end) and the budget leaves that hold plus 30 s, the chain
waits the hold out instead of giving up; at most three passes in all. Only then does the caller get a ProviderError,
and the pipeline takes its deterministic steps as before; its `retry_in` (seconds, or None) says when the earliest hold
ends, so a caller with a short deadline of its own (the writer's titles call) can wait and ask once more.

That error names every link that failed by its label, in brackets before its own message: «all model links failed:
[Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: no credits (402) …; [Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: access refused
(401/403) …» — two links may run the same model id, the label (the one status.snapshot() shows) tells them apart.
"""

from __future__ import annotations

import inspect
import logging
import random
import time
from typing import Any, Optional

from pydantic import BaseModel

from verstka.providers import status
from verstka.providers.base import ChatMessage, CompletionResult, Provider, ProviderError, Usage
from verstka.providers.openai_compat import _MIN_REQUEST_S, BudgetSpent, LinkUnavailable, RateLimited, TransientError

log = logging.getLogger(__name__)

_SECOND_PASS_MIN_S = 30.0  # budget that must remain for the second pass (and after a wait for a hold)
_SECOND_PASS_PAUSE_S = (3.0, 5.0)  # jittered, so the variants planned in parallel do not knock at the same moment
_WAIT_MAX_S = 30.0  # the longest hold the chain waits out when every link is on hold (a per-minute window)
_WAIT_JITTER_S = (0.5, 2.0)  # after the hold ends, so parallel calls waiting for the same window do not knock at once
_MAX_PASSES = 3  # pass 1 and at most two more (after a pause or a wait)
_RETRY_LATER = ("congested", "rate")


def _accepts(p: Any, param: str) -> bool:
    try:
        return param in inspect.signature(p.complete).parameters
    except (TypeError, ValueError):
        return False


def _summary(e: Exception, n: int = 180) -> str:
    text = status.mask(" ".join(str(e).split()))
    return text if len(text) <= n else text[: n - 1] + "…"


def link_label(p: Any) -> str:
    """The link's label as status.snapshot() shows it (its health record's), else the provider's own."""
    h = getattr(p, "health", None)
    return getattr(h, "label", None) or getattr(p, "label", None) or getattr(p, "model", "") or "model"


def _kind(e: Exception) -> str:
    """off | retry (congestion, 5xx, timeout, per-minute cap — worth a second pass) | other."""
    if isinstance(e, TransientError):
        return "retry"
    if isinstance(e, RateLimited):
        return "other" if e.daily else "retry"
    state = getattr(e, "state", None)
    if state == "off":
        return "off"
    if isinstance(e, LinkUnavailable) and (state in _RETRY_LATER or (state == "error" and getattr(e, "skipped", False))):
        # a link on hold after connection errors in a row is transient as well (other errors never open a hold)
        return "retry"
    return "other"


class ChainProvider:
    """Same interface as OpenAICompatProvider: `model` / `label` are those of the first link that has a key (the
    intended model; the first link when none has one); every CompletionResult names the model (and `label`, the
    host) that actually answered."""

    name = "chain"

    def __init__(self, links: list[Provider]) -> None:
        if not links:
            raise ProviderError("a fallback chain needs at least one link")
        self.links = list(links)
        first = next((p for p in self.links if not getattr(p, "off", False)), self.links[0])
        self.model = first.model
        self.label = getattr(first, "label", self.model)
        self._aware = [_accepts(p, "in_chain") for p in self.links]

    @property
    def api_key(self) -> str:
        """The first configured key: the app treats models as configured when any link can be called."""
        return next((k for k in (getattr(p, "api_key", "") for p in self.links) if k), "")

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"backend": p.name, "model": p.model, "label": getattr(p, "label", p.model), "off": bool(getattr(p, "off", False))} for p in self.links
        ]

    def _on_hold(self, i: int) -> bool:
        """The link (or its pool) is on hold now: a second pass would skip it without a request."""
        h = getattr(self.links[i], "health", None)
        return h is not None and status.blocked(h) is not None

    def _free_after(self, i: int, pause: float) -> bool:
        """The link can be asked once the pause is over (no hold, or one that ends by then)."""
        return self._hold_left(i) <= pause

    def _hold_left(self, i: int) -> float:
        """Seconds until the link (or its pool) may be asked again: 0 without a hold."""
        h = getattr(self.links[i], "health", None)
        if h is None:
            return 0.0
        hit = status.blocked(h)
        return 0.0 if hit is None else max(0.0, hit[2])

    def _soonest(self, live: list[int]) -> float:
        """Seconds until the first of the live links may be asked again."""
        return min((self._hold_left(i) for i in live), default=0.0)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        deadline: Optional[float] = None,
    ) -> CompletionResult:
        live = [i for i, p in enumerate(self.links) if not getattr(p, "off", False)]
        if not live:
            raise ProviderError(f"all model links failed: every link is {status.PHRASES['off']}")
        if len(live) == 1:
            # the only link with a key is a single provider: its own attempts, backoff and per-minute waits, at most
            # a short hold — the same as a config without a chain (e.g. a key-gated backup of the final's model)
            return self.links[live[0]].complete(messages, schema=schema, temperature=temperature, max_tokens=max_tokens, deadline=deadline)
        last = live[-1]
        failures: list[str] = []
        failed: list[dict[str, Any]] = []  # label, model, state and pass of every link that failed, in order
        spent = Usage()
        busy = final = False
        pass_no = 0
        while pass_no < _MAX_PASSES:
            pass_no += 1
            busy = False  # some link failed only for congestion, 5xx / timeout or a per-minute cap
            final = False  # some link failed in a way a second pass would repeat (no hold: invalid JSON, a plain 4xx)
            for i in live:
                link = self.links[i]
                if deadline is not None and deadline - time.monotonic() < _MIN_REQUEST_S:
                    failures.append("time budget of the generation is spent")
                    err = BudgetSpent("all model links failed: " + "; ".join(failures))
                    err.usage = spent  # type: ignore[attr-defined]
                    err.failed = failed  # type: ignore[attr-defined]
                    raise err
                kwargs: dict[str, Any] = dict(schema=schema, temperature=temperature, max_tokens=max_tokens, deadline=deadline)
                if self._aware[i]:
                    kwargs["in_chain"] = True
                    kwargs["fail_fast"] = i != last
                try:
                    res = link.complete(messages, **kwargs)
                except ProviderError as e:
                    used = getattr(e, "usage", None)
                    if isinstance(used, Usage):
                        spent = spent.add(used)
                    kind = _kind(e)
                    if kind == "off":
                        continue  # no key: not an error, nothing to report
                    if kind == "retry":
                        busy = True
                    elif not self._on_hold(i):
                        final = True  # a 402 / 404 / 401 / 403 / spent quota is on hold: skipped in pass 2 anyway
                    label = link_label(link)
                    failed.append({"label": label, "model": link.model, "state": getattr(e, "state", None) or "error", "pass": pass_no})
                    failures.append(("again: " if pass_no >= 2 else "") + f"[{label}] " + _summary(e))
                    log.info("model chain: %s did not answer (%s), next link", label, _summary(e, 160))
                    continue
                if failures:
                    log.info("model chain: answered by %s after %d failed attempt(s)", getattr(res, "label", None) or res.model, len(failures))
                    res.usage = spent.add(res.usage)
                return res
            if pass_no >= _MAX_PASSES or final or not busy:
                break
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left < _SECOND_PASS_MIN_S:
                break
            pause = random.uniform(*_SECOND_PASS_PAUSE_S)
            if not any(self._free_after(i, pause) for i in live):
                # every link is still on hold after the pause: a pass now would only skip them. A hold that ends soon
                # (a per-minute window of the only working link) is waited out while the budget leaves room for the
                # answer after it — a short cap of Cloud.ru must not turn the deck into a skeleton
                soonest = self._soonest(live)
                if soonest > _WAIT_MAX_S or (left is not None and left < soonest + _SECOND_PASS_MIN_S):
                    break
                pause = soonest + random.uniform(*_WAIT_JITTER_S)
                log.info("model chain: every link is on hold, waiting %.1f s for the first one to be free", pause)
            else:
                log.info("model chain: every link is busy, one more pass in %.1f s", pause)
            time.sleep(pause)
        err = ProviderError("all model links failed: " + ("; ".join(failures) or f"every link is {status.PHRASES['off']}"))
        err.usage = spent  # type: ignore[attr-defined]
        err.failed = failed  # type: ignore[attr-defined]
        # when the first link is free again: a caller with a short deadline of its own may wait and ask once more
        # (only after failures a later pass could cure — congestion, a 5xx, a per-minute cap — and a hold ≤ 30 s)
        soonest = self._soonest(live) if busy and not final else None
        err.retry_in = soonest if soonest is not None and 0.0 < soonest <= _WAIT_MAX_S else None  # type: ignore[attr-defined]
        raise err
