"""Text-to-image backends of the `t2i` role (configs/models.yaml). Open weights only: Apache 2.0 or MIT, at most 20B
parameters (the organisers' star task) — FLUX.2 [klein] 4B and Ming-Image-0.1-Design on OpenRouter by default.

Backends:
* `openrouter_images` — OpenRouter's POST {base}/images: {model, prompt, aspect_ratio, resolution, seed} → data[].b64_json;
* `openai_images` — the OpenAI-compatible POST {base}/images/generations: {model, prompt, size, response_format:
  b64_json, seed} → data[].b64_json or data[].url (Together, Nebius, DeepInfra, a local server, VK inference);
* `hf_inference` — Hugging Face Inference: POST {base}/models/{model} {inputs, parameters} → the image itself
  (Z-Image-Turbo 6B, Qwen-Image-2512 20B);
* `mock` — a picture drawn from the prompt (tests and offline demos; never in the default configs).

A role may list several models — a chain, like the text roles: the links are tried in order, a link without a key is
off (skipped silently, no request), a link that cannot answer (no credits, no such model, a refused key, a congested
host) is skipped for a while. Every failure is an ImageError: the slide keeps its free place then."""

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

# the aspect ratios the hosts take (OpenRouter's list); a place takes the nearest one and the picture is cropped to it
ASPECTS = ("1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "5:4", "4:5", "21:9")
# the ratios a place asks for: coarse, so the three variants' places of one description (4:3 here, 5:4 there) share one
# picture — a crop of a few per cent is invisible, three different pictures of one place are not
PLACE_ASPECTS = ("1:1", "4:3", "3:4", "16:9", "9:16", "21:9")
# OpenAI-compatible hosts take a size: about a megapixel, sides divisible by 64
SIZES = {
    "1:1": (1024, 1024), "4:3": (1152, 896), "3:4": (896, 1152), "3:2": (1216, 832), "2:3": (832, 1216),
    "16:9": (1344, 768), "9:16": (768, 1344), "5:4": (1088, 896), "4:5": (896, 1088), "21:9": (1536, 640),
}
# how long a link is skipped after a failure of its kind (s)
HOLDS = {"no_credits": 600.0, "auth": 1800.0, "missing": 1800.0, "rate": 120.0, "congested": 60.0, "error": 60.0}


class ImageError(ProviderError):
    """No picture: every link failed or is on hold, the key is missing, the answer held no image."""


@dataclass
class ImageResult:
    data: bytes  # the picture as the host sent it (PNG, JPEG or WebP)
    model: str
    label: str
    seed: Optional[int] = None
    cost_usd: Optional[float] = None
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


class _HTTPError(Exception):
    """An HTTP answer that is not a picture: `status_code` and the host's own words (for classify_error)."""

    def __init__(self, status_code: int, text: str, headers: Optional[dict] = None) -> None:
        super().__init__(f"Error code: {status_code} - {text[:300]}")
        self.status_code = status_code
        self.response = type("R", (), {"headers": headers or {}})()


def _decode_b64(s: str) -> bytes:
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _looks_like_image(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def picture_of(obj: Any, fetch=None) -> Optional[bytes]:
    """The picture in a host's JSON answer: data[].b64_json, data[].url (a data URL, or fetched with `fetch`), a chat
    answer's choices[0].message.images[].image_url.url, or images[].url (Hugging Face / SiliconFlow). None when none."""
    if not isinstance(obj, dict):
        return None
    items: list = []
    for key in ("data", "images", "output"):
        v = obj.get(key)
        if isinstance(v, list):
            items.extend(v)
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
                 extra_body: Optional[dict] = None, headers: Optional[dict] = None, price_per_image: Optional[float] = None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.label = label or model
        self.timeout_s = float(timeout_s)
        self.extra_body = dict(extra_body or {})
        self.headers = dict(headers or {})
        self.price = price_per_image
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

    def _fetch(self, url: str) -> bytes:
        import httpx

        r = httpx.get(url, timeout=self.timeout_s, follow_redirects=True)
        r.raise_for_status()
        return r.content

    def _result(self, data: Optional[bytes], seed: Optional[int], t0: float, cost: Optional[float] = None) -> ImageResult:
        if not data or not _looks_like_image(data):
            raise ImageError(f"{self.model}: the answer holds no picture")
        return ImageResult(data=data, model=self.model, label=self.label, seed=seed, cost_usd=cost if cost is not None else self.price, seconds=round(time.monotonic() - t0, 2))


class OpenRouterImages(_HTTPImages):
    """OpenRouter's image endpoint: POST {base}/images (docs: openrouter.ai/docs/features/multimodal/image-generation)."""

    name = "openrouter_images"

    def __init__(self, *args, resolution: str = "1K", **kw) -> None:
        super().__init__(*args, **kw)
        self.resolution = resolution
        self.headers.setdefault("HTTP-Referer", "https://github.com/verstka")
        self.headers.setdefault("X-Title", "Verstka")

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        t0 = time.monotonic()
        body: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": 1, "aspect_ratio": aspect, "resolution": self.resolution, **self.extra_body}
        if seed is not None:
            body["seed"] = int(seed)
        r = self._post(f"{self.base_url}/images", body, deadline)
        obj = r.json()
        cost = None
        try:
            cost = float(obj.get("usage", {}).get("cost")) if obj.get("usage", {}).get("cost") is not None else None
        except (TypeError, ValueError, AttributeError):
            cost = None
        return self._result(picture_of(obj, self._fetch), seed, t0, cost)


class OpenAIImages(_HTTPImages):
    """The OpenAI-compatible image endpoint: POST {base}/images/generations."""

    name = "openai_images"

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        t0 = time.monotonic()
        w, h = SIZES.get(aspect, SIZES["4:3"])
        body: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": 1, "size": f"{w}x{h}", "response_format": "b64_json", **self.extra_body}
        if seed is not None:
            body["seed"] = int(seed)
        r = self._post(f"{self.base_url}/images/generations", body, deadline)
        return self._result(picture_of(r.json(), self._fetch), seed, t0)


class HFInference(_HTTPImages):
    """Hugging Face Inference: POST {base}/models/{model} → the picture itself (or JSON with it)."""

    name = "hf_inference"

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        t0 = time.monotonic()
        w, h = SIZES.get(aspect, SIZES["4:3"])
        params: dict[str, Any] = {"width": w, "height": h, **self.extra_body}
        if seed is not None:
            params["seed"] = int(seed)
        r = self._post(f"{self.base_url}/models/{self.model}", {"inputs": prompt, "parameters": params}, deadline)
        data = r.content if _looks_like_image(r.content) else picture_of(r.json(), self._fetch)
        return self._result(data, seed, t0)


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
        w, h = SIZES.get(aspect, SIZES["4:3"])
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
        return ImageResult(data=buf.getvalue(), model=self.model, label=self.label, seed=seed, cost_usd=0.0)


@dataclass
class _Hold:
    until: float = 0.0
    state: str = ""
    reason: str = ""


@dataclass
class ImageChain:
    """The links of the `t2i` role in order: the first picture wins."""

    links: list
    holds: dict[int, _Hold] = field(default_factory=dict)
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

    def generate(self, prompt: str, *, aspect: str = "4:3", seed: Optional[int] = None, deadline: Optional[float] = None) -> ImageResult:
        from verstka.providers.openai_compat import LinkUnavailable, RateLimited, TransientError

        errors: list[str] = []
        live = [(i, lk) for i, lk in enumerate(self.links) if not lk.off]
        if not live:
            raise ImageError("no image model has an API key (t2i role)")
        for pos, (i, lk) in enumerate(live):
            with self._lock:
                h = self.holds.get(i)
                if h is not None and h.until > time.time():
                    errors.append(f"{lk.label}: skipped ({h.state}: {h.reason[:80]})")
                    continue
            last = pos == len(live) - 1
            for attempt in range(2 if last else 1):
                try:
                    return lk.generate(prompt, aspect=aspect, seed=seed, deadline=deadline)
                except LinkUnavailable as e:
                    self._hold(i, e.state or "error", HOLDS.get(e.state or "error", 60.0), str(e))
                    errors.append(f"{lk.label}: {e}")
                    break
                except RateLimited as e:
                    self._hold(i, "rate", min(float(e.retry_after or HOLDS["rate"]), 900.0), str(e))
                    errors.append(f"{lk.label}: {e}")
                    break
                except TransientError as e:
                    errors.append(f"{lk.label}: {e}")
                    if attempt == 0 and last and (deadline is None or deadline - time.monotonic() > 20):
                        time.sleep(2.0)
                        continue
                    self._hold(i, "congested", HOLDS["congested"], str(e))
                    break
                except ProviderError as e:
                    errors.append(f"{lk.label}: {e}")
                    break
        raise ImageError("; ".join(errors)[:600] or "no picture")

    def _hold(self, i: int, state: str, seconds: float, reason: str) -> None:
        with self._lock:
            self.holds[i] = _Hold(until=time.time() + seconds, state=state, reason=reason)
        log.info("t2i link %s on hold for %.0f s: %s", self.links[i].label, seconds, reason[:200])


def build_image_link(spec: dict, timeout_s: float = 90.0) -> Any:
    backend = (spec.get("backend") or "openrouter_images").lower()
    if backend == "mock":
        return MockImages(model=spec.get("model", "mock-t2i"), label=spec.get("label"), delay_s=float(spec.get("delay_s", 0) or 0), fail=bool(spec.get("fail")))
    kw = dict(label=spec.get("label"), timeout_s=float(spec.get("timeout_s", timeout_s)), extra_body=spec.get("extra_body"), headers=spec.get("headers"),
              price_per_image=spec.get("price_per_image"))
    if backend == "openrouter_images":
        return OpenRouterImages(spec.get("model") or "", spec.get("base_url") or "https://openrouter.ai/api/v1", spec.get("api_key") or "", resolution=str(spec.get("resolution", "1K")), **kw)
    if backend == "openai_images":
        return OpenAIImages(spec.get("model") or "", spec.get("base_url") or "https://api.openai.com/v1", spec.get("api_key") or "", **kw)
    if backend == "hf_inference":
        return HFInference(spec.get("model") or "", spec.get("base_url") or "https://router.huggingface.co/hf-inference", spec.get("api_key") or "", **kw)
    raise ImageError(f"unknown t2i backend {backend!r}")


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
    """The `t2i` role of the models config (default: configs/models.yaml or $VERSTKA_MODELS), cached per file — the
    links' holds live as long as the server. None when the config has no t2i role."""
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
