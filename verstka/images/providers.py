"""Text-to-image backends of the `t2i` role (configs/models.yaml). Open weights only: Apache 2.0 or MIT, at most 20B
parameters (the organisers' star task) — Z-Image (Tongyi-MAI, ≈ 10B with its text encoder) on Polza by default.

Backends:
* `polza_media` — Polza's Media API: POST {base}/media {model, input: {prompt, aspect_ratio}} → the picture's link at
  once, or {id, status: pending | processing} → GET {base}/media/{id} until completed (data: [{url}]) or failed; the
  picture is fetched from Polza's CDN;
* `openai_images` — the OpenAI-compatible POST {base}/images/generations: {model, prompt, size, response_format:
  b64_json, seed} → data[].b64_json or data[].url (the final's VK inference, if it serves an open text-to-image model);
* `mock` — a picture drawn from the prompt (tests and offline demos; never in the default configs).

A role may list several models — a chain, like the text roles: the links are tried in order, a link without a key is
off (skipped silently, no request), a link that cannot answer (no money, no such model, a refused key, congested
hosts) is skipped for a while. Every failure is an ImageError: the slide keeps its free place then."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from verstka.providers.base import ProviderError

log = logging.getLogger(__name__)

# the aspect ratios Polza's Z-Image takes; a place takes the nearest one and the picture is cropped to the place's
# exact proportions. Coarse on purpose: the three variants' places of one description (4:3 here, 5:4 there) share one
# picture — a crop of a few per cent is invisible, three different pictures of one place are not
PLACE_ASPECTS = ("1:1", "4:3", "3:4", "16:9", "9:16")
# OpenAI-compatible hosts take a size: about a megapixel, sides divisible by 64
SIZES = {"1:1": (1024, 1024), "4:3": (1152, 896), "3:4": (896, 1152), "16:9": (1344, 768), "9:16": (768, 1344)}
# Polza's limit on a picture's prompt (its catalog: parameters.prompt.max_length)
PROMPT_MAX_CHARS = 1000
# how long a link is skipped after a failure of its kind (s)
HOLDS = {"no_credits": 600.0, "auth": 1800.0, "missing": 1800.0, "rate": 120.0, "quota": 3600.0, "congested": 60.0, "error": 60.0}
_PICTURE_S = 15.0  # a picture's time: a wait must leave it before the generation's deadline
_WAIT_MAX_S = 65.0  # the longest pause of the last link that is waited out (a minute window, a congestion hold)
_RESERVE_WAIT_S = 8.0  # a 402 while parallel requests hold the balance: about one picture's time frees a reserve


class ImageError(ProviderError):
    """No picture: every link failed or is on hold, the key is missing, the answer held no image."""


@dataclass
class ImageResult:
    data: bytes  # the picture as the host sent it (PNG, JPEG or WebP)
    model: str
    label: str
    seed: Optional[int] = None
    cost_rub: Optional[float] = None  # Polza's usage.cost_rub of the picture
    seconds: float = 0.0


class ImageProvider(Protocol):
    name: str
    model: str
    label: str
    off: bool

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult: ...


def nearest_aspect(w: float, h: float, aspects: tuple[str, ...] = PLACE_ASPECTS) -> str:
    """The aspect ratio of `aspects` nearest to w:h (by the log of the ratio: 4:3 and 3:4 are equally far from 1:1)."""
    import math

    if w <= 0 or h <= 0:
        return "1:1"
    r = math.log(w / h)

    def dist(a: str) -> float:
        x, y = (float(v) for v in a.split(":"))
        return abs(math.log(x / y) - r)

    return min(aspects, key=dist)


def _known_aspect(aspect: str) -> str:
    """One of PLACE_ASPECTS: an older record's ratio («21:9», «3:2») becomes the nearest one, never a 4:3 by default."""
    if aspect in PLACE_ASPECTS:
        return aspect
    try:
        w, h = (float(v) for v in str(aspect).split(":"))
    except ValueError:
        return "4:3"
    return nearest_aspect(w, h)


class _HTTPError(Exception):
    """An HTTP answer that is not a picture: `status_code` and the host's own words (for classify_error). A JSON body
    is read as JSON first, so words the host escaped («\\u041d…») are read as words — the way the openai SDK shows a
    chat error ({'error': {'code': …, 'message': …}})."""

    def __init__(self, status_code: int, text: str, headers: Optional[dict] = None) -> None:
        import json as _json

        try:
            body = _json.loads(text)
            words = _json.dumps(body.get("error", body) if isinstance(body, dict) else body, ensure_ascii=False)
        except (ValueError, TypeError):
            words = text
        super().__init__(f"Error code: {status_code} - {words[:400]}")
        self.status_code = status_code
        self.response = type("R", (), {"headers": headers or {}})()


def _decode_b64(s: str) -> bytes:
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _looks_like_image(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def picture_of(obj: Any, fetch=None) -> Optional[bytes]:
    """The picture in a host's JSON answer: data[].b64_json, data[].url or data.url (a data URL, or fetched with
    `fetch`), a chat answer's choices[0].message.images[].image_url.url, or images[].url. None when none."""
    if not isinstance(obj, dict):
        return None
    items: list = []
    for key in ("data", "images", "output"):
        v = obj.get(key)
        if isinstance(v, list):
            items.extend(v)
        elif isinstance(v, dict):  # Polza's media status documents data as one object
            items.append(v)
    try:
        msg = obj["choices"][0]["message"]
        items.extend(msg.get("images") or [])
    except (KeyError, IndexError, TypeError):
        pass
    for it in items:
        if isinstance(it, str):
            if it.startswith("data:"):
                return _decode_b64(it)
            if it.startswith("http") and fetch is not None:
                return fetch(it)
            continue
        if not isinstance(it, dict):
            continue
        b64 = it.get("b64_json") or it.get("b64") or it.get("base64")
        if isinstance(b64, str) and b64:
            return _decode_b64(b64)
        url = it.get("url")
        if url is None and isinstance(it.get("image_url"), dict):
            url = it["image_url"].get("url")
        if isinstance(url, str) and url:
            if url.startswith("data:"):
                return _decode_b64(url)
            if url.startswith("http") and fetch is not None:
                return fetch(url)
    return None


class _HTTPImages:
    """The common part of the HTTP backends: the key, the timeout within the generation's deadline, the error → its
    kind (verstka.providers.openai_compat.classify_error), the answer → the picture."""

    name = "http"

    def __init__(self, model: str, base_url: str, api_key: str = "", *, label: Optional[str] = None, timeout_s: float = 90.0,
                 extra_body: Optional[dict] = None, headers: Optional[dict] = None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.label = label or model
        self.timeout_s = float(timeout_s)
        self.extra_body = dict(extra_body or {})
        self.headers = dict(headers or {})
        # no key or no model (an empty variable: VK_T2I_MODEL unset) — the link is off: skipped, never asked
        self.off = not self.api_key or not self.model

    def _timeout(self, deadline: Optional[float]) -> float:
        if deadline is None:
            return self.timeout_s
        left = deadline - time.monotonic()
        if left < 3.0:
            raise ImageError(f"{self.model}: no time left for a picture")
        return min(self.timeout_s, left)

    def _post(self, url: str, body: dict, deadline: Optional[float]):
        import httpx

        from verstka.providers.openai_compat import classify_error

        if self.off:
            raise ImageError(f"{self.model or 't2i'}: no API key or model — the link is off")
        headers = {"Authorization": f"Bearer {self.api_key}", **self.headers}
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=self._timeout(deadline))
        except ImageError:
            raise
        except Exception as e:  # noqa: BLE001 - timeouts and dropped connections have their kinds
            raise classify_error(e, self.model, self.api_key) from None
        if r.status_code >= 400:
            raise classify_error(_HTTPError(r.status_code, r.text, dict(r.headers)), self.model, self.api_key)
        return r

    def _fetch(self, url: str, deadline: Optional[float] = None) -> bytes:
        """The finished picture from the host's link (Polza's CDN — no key): within the deadline, one more try on a
        dropped connection or a 5xx; any failure is an ImageError (the picture is paid for, the place stays free)."""
        import httpx

        last: Optional[Exception] = None
        for attempt in range(2):
            try:
                r = httpx.get(url, timeout=min(30.0, self._timeout(deadline)), follow_redirects=True)
                if r.status_code >= 500 and attempt == 0:
                    last = RuntimeError(f"HTTP {r.status_code}")
                    time.sleep(1.0)
                    continue
                r.raise_for_status()
                return r.content
            except ImageError:
                raise
            except Exception as e:  # noqa: BLE001 - a timeout, a dropped connection, a 4xx of the CDN
                last = e
                if attempt == 0 and not isinstance(e, httpx.HTTPStatusError):
                    time.sleep(1.0)
                    continue
                break
        raise ImageError(f"{self.model}: the picture could not be downloaded ({str(last)[:160]})")

    def _json(self, r) -> Any:
        try:
            return r.json()
        except Exception as e:  # noqa: BLE001 - a 200 that is not JSON
            raise ImageError(f"{self.model}: the host's answer is not JSON ({str(e)[:120]})") from None

    def _result(self, data: Optional[bytes], seed: Optional[int], t0: float, cost: Optional[float] = None) -> ImageResult:
        if not data or not _looks_like_image(data):
            raise ImageError(f"{self.model}: the answer holds no picture")
        return ImageResult(data=data, model=self.model, label=self.label, seed=seed, cost_rub=cost, seconds=round(time.monotonic() - t0, 2))


def _usage_rub(obj: Any, polza: bool = True) -> Optional[float]:
    """What the picture cost in rubles: Polza's usage.cost_rub (or its alias usage.cost); another endpoint's usage.cost
    is in its own money, so only cost_rub counts there."""
    usage = obj.get("usage") if isinstance(obj, dict) else None
    if not isinstance(usage, dict):
        return None
    for name in ("cost_rub", "cost") if polza else ("cost_rub",):
        try:
            if usage.get(name) is not None:
                return float(usage[name])
        except (TypeError, ValueError):
            continue
    return None


# a failed task whose error is the host's passing trouble: worth asking again (a failed task costs nothing)
_TRANSIENT_CODES = {"BAD_GATEWAY", "REQUEST_TIMEOUT", "SERVICE_UNAVAILABLE", "INTERNAL_ERROR", "TOO_MANY_REQUESTS"}


class PolzaMedia(_HTTPImages):
    """Polza's Media API (docs: polza.ai/docs/api-reference/media/create). The answer is the finished picture's link,
    or a task to poll: GET {base}/media/{id} every `poll_s` until completed, failed or cancelled, within the
    generation's deadline and the link's timeout. A status request that fails (a 404 race, a 5xx, a timeout, a 429) is
    asked again at the next poll — the task keeps running and is paid once; only a refused key ends the wait. Z-Image
    takes no seed: the same prompt asked again draws a new picture (checked live: two identical requests, two
    different pictures)."""

    name = "polza_media"

    def __init__(self, *args, poll_s: float = 3.0, **kw) -> None:
        super().__init__(*args, **kw)
        self.poll_s = max(0.5, float(poll_s))

    def _status(self, url: str, deadline: Optional[float]) -> Optional[dict]:
        """The task's status, or None when this status request failed in a way the next poll may get past."""
        import httpx

        from verstka.providers.openai_compat import LinkUnavailable, classify_error

        try:
            r = httpx.get(url, headers={"Authorization": f"Bearer {self.api_key}", **self.headers}, timeout=min(20.0, self._timeout(deadline)))
        except ImageError:
            raise
        except Exception as e:  # noqa: BLE001 - a timeout or a dropped connection: poll again
            log.info("%s: status request failed (%s), polling again", self.model, str(e)[:120])
            return None
        if r.status_code in (401, 403):
            err = classify_error(_HTTPError(r.status_code, r.text, dict(r.headers)), self.model, self.api_key)
            if isinstance(err, LinkUnavailable):
                raise err
        if r.status_code >= 400:
            log.info("%s: status request answered %s, polling again", self.model, r.status_code)
            return None
        try:
            obj = r.json()
        except Exception:  # noqa: BLE001
            return None
        return obj if isinstance(obj, dict) else None

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        from verstka.providers.openai_compat import TransientError

        t0 = time.monotonic()
        ratio = _known_aspect(aspect)
        body: dict[str, Any] = {"model": self.model, "input": {"prompt": prompt[:PROMPT_MAX_CHARS], "aspect_ratio": ratio}, **self.extra_body}
        obj = self._json(self._post(f"{self.base_url}/media", body, deadline))
        ends = t0 + self.timeout_s
        task = obj.get("id") if isinstance(obj, dict) else None
        while isinstance(obj, dict) and obj.get("status") in ("pending", "processing", "queued", "in_progress"):
            if not task:
                raise ImageError(f"{self.model}: the task has no id to poll")
            if time.monotonic() + self.poll_s > min(ends, deadline if deadline is not None else ends):
                raise ImageError(f"{self.model}: the picture was not ready in time (status {obj.get('status')})")
            time.sleep(self.poll_s)
            got = self._status(f"{self.base_url}/media/{task}", deadline)
            if got is not None:
                obj = got
        if isinstance(obj, dict) and obj.get("status") in ("failed", "cancelled"):
            err = obj.get("error")
            code = err.get("code") if isinstance(err, dict) else None
            what = (err.get("message") if isinstance(err, dict) else err) or obj.get("status")
            msg = f"{self.model}: the picture failed ({code + ': ' if code else ''}{str(what)[:200]})"
            if code in _TRANSIENT_CODES:
                raise TransientError(msg)  # the host's passing trouble: the chain asks again
            raise ImageError(msg)
        return self._result(picture_of(obj, lambda u: self._fetch(u, deadline)), seed, t0, _usage_rub(obj))


class OpenAIImages(_HTTPImages):
    """The OpenAI-compatible image endpoint: POST {base}/images/generations (the final's VK inference)."""

    name = "openai_images"

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        t0 = time.monotonic()
        w, h = SIZES[_known_aspect(aspect)]
        body: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": 1, "size": f"{w}x{h}", "response_format": "b64_json", **self.extra_body}
        if seed is not None:
            body["seed"] = int(seed)
        obj = self._json(self._post(f"{self.base_url}/images/generations", body, deadline))
        return self._result(picture_of(obj, lambda u: self._fetch(u, deadline)), seed, t0, _usage_rub(obj, polza=False))


class MockImages:
    """A picture drawn from the prompt (soft bands and circles, its colours from the prompt's hash): tests and offline
    demos. Never in a default config — a build without a real model keeps its free places."""

    name = "mock"
    off = False

    def __init__(self, model: str = "mock-t2i", label: Optional[str] = None, delay_s: float = 0.0, fail: bool = False) -> None:
        self.model = model
        self.label = label or "Mock T2I"
        self.delay_s = delay_s
        self.fail = fail
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        from PIL import Image, ImageDraw

        with self._lock:
            self.calls.append({"prompt": prompt, "aspect": aspect, "seed": seed})
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise ImageError(f"{self.model}: failed on purpose")
        w, h = SIZES[_known_aspect(aspect)]
        w, h = w // 4, h // 4
        d = hashlib.sha256(f"{prompt}|{seed}".encode("utf-8")).digest()
        img = Image.new("RGB", (w, h), (d[0], d[1], d[2]))
        draw = ImageDraw.Draw(img)
        for i in range(6):
            c = (d[3 + i], d[9 + i], d[15 + i])
            r = int(min(w, h) * (0.12 + d[21 + i] / 255 * 0.3))
            x, y = int(d[27 - i] / 255 * w), int(d[i + 10] / 255 * h)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=c)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return ImageResult(data=buf.getvalue(), model=self.model, label=self.label, seed=seed, cost_rub=0.0)


@dataclass
class _Hold:
    until: float = 0.0
    state: str = ""
    reason: str = ""


@dataclass
class ImageChain:
    """The links of the `t2i` role in order: the first picture wins. Every link but the last hands a failure over to
    the next one at once. The last link — on Polza the only one, Z-Image — rides a passing trouble out instead of
    switching the pictures off for the rest of the generation: Polza's per-minute cap is waited out, the hosts' own
    429 gets a growing pause (held only after two in a row), a 402 while parallel requests hold the balance waits for
    their reserve, a 5xx gets its pause (a 503 its Retry-After) — each while the generation's deadline still leaves a
    picture's time. A short hold of the last link (a minute window, a pause after congestion) is waited out the same
    way. Polza's daily cap holds the model until midnight by Moscow time; no money, a refused key or a missing model
    hold it for 10 or 30 minutes."""

    links: list
    holds: dict[int, _Hold] = field(default_factory=dict)
    strikes: dict[int, int] = field(default_factory=dict)  # failures in a row per link (a success resets them)
    name: str = "chain"

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        live = [lk for lk in self.links if not lk.off]
        return (live[0] if live else self.links[0]).model

    @property
    def label(self) -> str:
        live = [lk for lk in self.links if not lk.off]
        return (live[0] if live else self.links[0]).label

    @property
    def off(self) -> bool:
        return all(lk.off for lk in self.links)

    def describe(self) -> list[dict]:
        now = time.time()
        out = []
        for i, lk in enumerate(self.links):
            h = self.holds.get(i)
            state = "off" if lk.off else (h.state if h and h.until > now else "ready")
            out.append({"model": lk.model, "label": lk.label, "backend": lk.name, "state": state})
        return out

    def _strike(self, i: int) -> int:
        with self._lock:
            self.strikes[i] = self.strikes.get(i, 0) + 1
            return self.strikes[i]

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        from verstka.providers.openai_compat import LinkUnavailable, RateLimited, TransientError, _quota_hold

        errors: list[str] = []
        live = [(i, lk) for i, lk in enumerate(self.links) if not lk.off]
        if not live:
            raise ImageError("no image model has an API key (t2i role)")

        def room(wait: float) -> bool:
            # after the wait the generation's deadline still leaves time for a picture
            return deadline is None or deadline - time.monotonic() > wait + _PICTURE_S

        for pos, (i, lk) in enumerate(live):
            last = pos == len(live) - 1
            with self._lock:
                h = self.holds.get(i)
                left = (h.until - time.time()) if h is not None else 0.0
            if left > 0:
                if last and h is not None and h.state in ("rate", "congested") and left <= _WAIT_MAX_S and room(left):
                    log.info("t2i link %s: waiting %.0f s for its pause to end", lk.label, left)
                    time.sleep(left)
                else:
                    errors.append(f"{lk.label}: skipped ({h.state if h else 'hold'}: {(h.reason if h else '')[:80]})")
                    continue
            attempts = 3 if last else 1
            for attempt in range(attempts):
                more = last and attempt < attempts - 1
                try:
                    res = lk.generate(prompt, aspect=aspect, seed=seed, deadline=deadline)
                    with self._lock:
                        self.strikes.pop(i, None)
                    return res
                except LinkUnavailable as e:  # no money, a refused key, no such model: a long hold
                    self._hold(i, e.state or "error", HOLDS.get(e.state or "error", 60.0), str(e))
                    errors.append(f"{lk.label}: {e}")
                    break
                except RateLimited as e:
                    errors.append(f"{lk.label}: {e}")
                    if e.daily:  # Polza's daily cap of the model: until its Retry-After or midnight by Moscow time
                        self._hold(i, "quota", _quota_hold(e), str(e))
                        break
                    if e.upstream:  # the hosts' own limit: a growing pause, a hold only after two in a row
                        n = self._strike(i)
                        wait = min(2.0 ** (attempt + 1), 8.0)
                        if n < 2 and more and room(wait):
                            time.sleep(wait)
                            continue
                        if n >= 2:
                            self._hold(i, "congested", HOLDS["congested"], str(e))
                        break
                    wait = min(float(e.retry_after or 20.0), 65.0)  # Polza's per-minute cap: its window ends soon
                    if more and room(wait):
                        time.sleep(wait)
                        continue
                    self._hold(i, "rate", wait, str(e))
                    break
                except TransientError as e:  # a 5xx, a timeout, a failed task, the balance held by parallel requests
                    errors.append(f"{lk.label}: {e}")
                    reserve = bool(getattr(e, "reserve", False))
                    wait = min(max(2.0 ** (attempt + 1), float(getattr(e, "retry_after", None) or 0.0), _RESERVE_WAIT_S if reserve else 0.0), 15.0)
                    if more and room(wait):
                        time.sleep(wait)
                        continue
                    if not reserve and self._strike(i) >= 2:
                        self._hold(i, "congested", HOLDS["congested"], str(e))
                    break
                except ProviderError as e:  # this picture failed (moderation, no picture in the answer): no hold
                    errors.append(f"{lk.label}: {e}")
                    break
        raise ImageError("; ".join(errors)[:600] or "no picture")

    def _hold(self, i: int, state: str, seconds: float, reason: str) -> None:
        with self._lock:
            self.holds[i] = _Hold(until=time.time() + seconds, state=state, reason=reason)
        log.info("t2i link %s on hold for %.0f s: %s", self.links[i].label, seconds, reason[:200])


def build_image_link(spec: dict, timeout_s: float = 90.0) -> Any:
    backend = (spec.get("backend") or "polza_media").lower()
    if backend == "mock":
        return MockImages(model=spec.get("model", "mock-t2i"), label=spec.get("label"), delay_s=float(spec.get("delay_s", 0) or 0), fail=bool(spec.get("fail")))
    kw = dict(label=spec.get("label"), timeout_s=float(spec.get("timeout_s", timeout_s)), extra_body=spec.get("extra_body"), headers=spec.get("headers"))
    if backend == "polza_media":
        return PolzaMedia(spec.get("model") or "", spec.get("base_url") or "https://polza.ai/api/v1", spec.get("api_key") or "", poll_s=float(spec.get("poll_s", 3.0) or 3.0), **kw)
    if backend == "openai_images":
        # no endpoint (VK_INFERENCE_BASE_URL unset): the link is off like one without a key
        base = spec.get("base_url") or ""
        return OpenAIImages(spec.get("model") or "", base, (spec.get("api_key") or "") if base else "", **kw)
    raise ImageError(f"unknown t2i backend {backend!r} (polza_media, openai_images or mock)")


def build_image_provider(spec: Optional[dict], timeout_s: float = 90.0) -> Optional[ImageChain]:
    """The `t2i` role's spec (env already expanded) → a chain (one link is a chain of one); None without a spec."""
    if not isinstance(spec, dict) or not spec:
        return None
    if "chain" in spec:
        shared = {k: v for k, v in spec.items() if k != "chain"}
        links = [build_image_link({**shared, **ls}, timeout_s) for ls in spec.get("chain") or [] if isinstance(ls, dict)]
    else:
        links = [build_image_link(spec, timeout_s)]
    return ImageChain(links) if links else None


_CACHE: dict[str, Optional[ImageChain]] = {}
_CACHE_LOCK = threading.Lock()


def load_image_provider(path: Optional[Path | str] = None) -> Optional[ImageChain]:
    """The `t2i` role of the models config (default: the profile verstka.providers.registry.default_models_path()
    picks — $VERSTKA_MODELS, else configs/models.vk.yaml with the VK keys set, else configs/models.yaml), cached per
    file — the links' holds live as long as the server. None when the config has no t2i role."""
    import yaml

    from verstka.providers.registry import default_models_path, expand_env

    p = Path(path) if path else default_models_path()
    key = str(p.resolve())
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except OSError:
            cfg = {}
        cfg = expand_env(cfg)
        spec = (cfg.get("roles") or {}).get("t2i")
        timeout = float((cfg.get("limits") or {}).get("t2i_timeout_s", 90))
        try:
            chain = build_image_provider(spec, timeout)
        except (ImageError, KeyError) as e:
            log.warning("t2i role unavailable: %s", e)
            chain = None
        _CACHE[key] = chain
        return chain


def reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
