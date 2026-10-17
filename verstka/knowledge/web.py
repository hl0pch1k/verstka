"""A public web page for the knowledge base: one GET of the address the person gave, nothing more.

- only http(s), ports 80 and 443, no user:password in the address, no cookies, no authorization of any kind;
- the host must resolve to public addresses only (no localhost, private networks, link-local, the metadata service):
  a page is never a way into the server's own network; every redirect (at most MAX_REDIRECTS) is checked again;
- at most MAX_BYTES of the answer and TIMEOUT_S for the whole fetch;
- no crawling: the links on the page are not followed.

The answer: an HTML page, a text, a PDF or a DOCX — read by verstka/ingest/documents.py."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 12.0
MAX_REDIRECTS = 3
USER_AGENT = "Verstka/knowledge-base (one page on request; https://github.com/)"

_ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown", "application/pdf",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class FetchError(ValueError):
    """The page cannot be taken — the message is for the person (Russian)."""


@dataclass
class Page:
    url: str  # the address after the redirects
    content_type: str
    data: bytes
    seconds: float


Resolver = Callable[[str, int], list[str]]


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def check_url(url: str, resolve: Optional[Resolver] = None) -> str:
    """The address as it will be fetched, or FetchError with the reason."""
    u = (url or "").strip()
    if not u:
        raise FetchError("Вставьте адрес страницы")
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I) and not re.match(r"^[\w.-]+:\d", u):
            raise FetchError("Подходят только ссылки http:// и https://")
        u = "https://" + u
    try:
        parts = urlsplit(u)
    except ValueError as e:
        raise FetchError("Адрес не читается — проверьте ссылку") from e
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchError("Подходят только ссылки http:// и https://")
    if parts.username or parts.password:
        raise FetchError("Страницы с логином и паролем в адресе не беру — нужна публичная страница")
    host = parts.hostname or ""
    if not host or "." not in host and not _is_ip(host):
        raise FetchError("В адресе нет сайта — проверьте ссылку")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as e:
        raise FetchError("Адрес не читается — проверьте ссылку") from e
    if port not in (80, 443):
        raise FetchError("Подходят только обычные адреса сайтов (порты 80 и 443)")
    try:
        addrs = (resolve or _resolve)(host, port)
    except (OSError, UnicodeError) as e:
        raise FetchError(f"Сайт {host} не найден — проверьте адрес") from e
    if not addrs:
        raise FetchError(f"Сайт {host} не найден — проверьте адрес")
    for a in addrs:
        if not _public(a):
            raise FetchError("Это адрес внутренней сети — подходят только публичные страницы интернета")
    return u


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast and not ip.is_reserved


def fetch(url: str, *, timeout_s: float = TIMEOUT_S, max_bytes: int = MAX_BYTES, transport: Any = None,
          resolve: Optional[Resolver] = None) -> Page:
    """One public page (FetchError with the reason otherwise)."""
    import httpx

    t0 = time.monotonic()
    deadline = t0 + timeout_s
    u = check_url(url, resolve)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.5",
               "Accept-Language": "ru,en;q=0.8"}
    with httpx.Client(follow_redirects=False, transport=transport, headers=headers, timeout=httpx.Timeout(min(timeout_s, 10.0))) as client:
        for _ in range(MAX_REDIRECTS + 1):
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchError("Страница слишком долго отвечает")
            try:
                with client.stream("GET", u, timeout=httpx.Timeout(max(1.0, left))) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise FetchError("Страница перенаправляет в никуда")
                        u = check_url(urljoin(u, loc), resolve)
                        continue
                    if r.status_code in (401, 403):
                        raise FetchError("Страница закрыта входом — нужна публичная страница без авторизации")
                    if r.status_code == 404:
                        raise FetchError("Страница не найдена (404) — проверьте адрес")
                    if r.status_code >= 400:
                        raise FetchError(f"Сайт ответил ошибкой {r.status_code}")
                    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if ctype and not any(ctype.startswith(t) for t in _ALLOWED_TYPES):
                        raise FetchError("По ссылке не страница и не документ — подходят веб-страницы, PDF и DOCX")
                    declared = r.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError(f"Страница больше {max_bytes // (1024 * 1024)} МБ")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise FetchError(f"Страница больше {max_bytes // (1024 * 1024)} МБ")
                        if time.monotonic() > deadline:
                            raise FetchError("Страница слишком долго загружается")
                    return Page(url=str(r.url), content_type=ctype, data=bytes(buf), seconds=round(time.monotonic() - t0, 2))
            except FetchError:
                raise
            except httpx.TimeoutException as e:
                raise FetchError("Страница слишком долго отвечает") from e
            except httpx.HTTPError as e:
                raise FetchError("Не удалось открыть страницу — сайт недоступен") from e
    raise FetchError("Слишком много перенаправлений")


def page_name(page: Page) -> str:
    """The name the page's document is read under (its type by the answer's content type)."""
    path = urlsplit(page.url).path.rsplit("/", 1)[-1] or urlsplit(page.url).hostname or "page"
    if page.content_type == "application/pdf" or page.data[:4] == b"%PDF":
        return path if path.lower().endswith(".pdf") else f"{path}.pdf"
    if "wordprocessingml" in page.content_type:
        return path if path.lower().endswith(".docx") else f"{path}.docx"
    if page.content_type in ("text/plain", "text/markdown"):
        return path if path.lower().endswith((".txt", ".md")) else f"{path}.txt"
    return path if path.lower().endswith((".html", ".htm")) else f"{path}.html"


__all__ = ["FetchError", "MAX_BYTES", "Page", "TIMEOUT_S", "check_url", "fetch", "page_name"]
