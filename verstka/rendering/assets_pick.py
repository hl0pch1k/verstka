"""Pick template assets (illustrations, icons) for content hints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.template import Asset, TemplateManifest

_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.I)

_HINT_SYNONYMS = {
    "chat": ["chat", "message", "сообщен", "чат", "bubble"],
    "calendar": ["calendar", "date", "календар", "срок", "time", "clock"],
    "alert": ["alert", "warning", "bell", "уведомл", "эскалац", "notification"],
    "list": ["list", "check", "task", "задач", "список", "todo"],
    "security": ["security", "shield", "lock", "защит", "безопас"],
    "cloud": ["cloud", "облак", "server"],
    "team": ["team", "people", "user", "команд", "люди"],
    "growth": ["growth", "chart", "рост", "arrow", "trend"],
    "money": ["money", "ruble", "деньг", "wallet", "coin"],
    "idea": ["idea", "bulb", "идея", "идеи", "идей", "light"],
}


def _score(asset: Asset, words: set[str]) -> int:
    """Hint words found in the asset's tags (file names are ids, not descriptions); short words never match —
    «и» is a substring of every «image12»."""
    hay = " ".join(asset.tags).lower()
    return sum(1 for w in words if len(w) >= 4 and w in hay)


def _expand(hint: Optional[str]) -> set[str]:
    if not hint:
        return set()
    words = set(w.lower() for w in _WORD_RE.findall(hint))
    for key, syns in _HINT_SYNONYMS.items():
        if key in words or any(s in hint.lower() for s in syns):
            words.update(syns)
    return words


def pick_asset(manifest: TemplateManifest, ws: TemplateWorkspace, hint: Optional[str], kinds: tuple[str, ...] = ("illustration", "photo"), exclude: Optional[set[str]] = None, min_px: int = 200, require_match: bool = False) -> Optional[Path]:
    """The template picture that answers the hint. With require_match, a picture whose tags say nothing about the
    hint is not returned: an untagged template (no vision model) would otherwise put a tablet frame or a store
    screenshot next to a slide about operators."""
    exclude = exclude or set()
    cands = [a for a in manifest.assets if a.kind in kinds and a.id not in exclude and max(a.width, a.height) >= min_px and not a.path.endswith(".svg")]
    if not cands:
        return None
    words = _expand(hint)
    cands.sort(key=lambda a: (-_score(a, words), -(a.width * a.height)))
    best = cands[0]
    if require_match and _score(best, words) == 0:
        return None
    return ws.dir / best.path


def _meaning_words(hint: Optional[str]) -> set[str]:
    """The hint's words and the synonyms of the topics it names — a topic named by a word that starts with one of its
    stems («сообщения» → chat), never by a stem hidden inside another word («начать» is no «чат», «простой» no
    «рост», «block» no «lock»)."""
    words = {w.lower() for w in _WORD_RE.findall(hint or "")}
    out = set(words)
    for key, syns in _HINT_SYNONYMS.items():
        if key in words or any(w.startswith(s) for w in words for s in syns if len(s) >= 4):
            out.update(syns)
    return out


def _meaning_score(asset: Asset, words: set[str]) -> int:
    """Hint words that are words of the icon's tags (or their beginnings: «сообщен» → «сообщение») — never a piece of
    another word («date» in «update»)."""
    tags = {t.lower() for t in _WORD_RE.findall(" ".join(asset.tags))}
    return sum(1 for w in words if len(w) >= 4 and any(t == w or t.startswith(w) for t in tags))


def pick_icon(manifest: TemplateManifest, ws: TemplateWorkspace, hint: Optional[str], exclude: Optional[set[str]] = None) -> Optional[tuple[str, Path]]:
    """The template icon that says what the hint says — by meaning: the hint's words or its topic's synonyms among the
    icon's tags. None when none does: the caller shows no icon rather than a wrong one (qa3 N-B5: a calendar beside
    «Каналы продаж»)."""
    exclude = exclude or set()
    cands = [a for a in manifest.assets if a.kind == "icon" and a.id not in exclude and a.has_alpha and not a.path.endswith(".svg") and a.width >= 24]
    if not cands or not (hint or "").strip():
        return None
    words = _meaning_words(hint)
    cands.sort(key=lambda a: (-_meaning_score(a, words), -(a.width * a.height)))
    best = cands[0]
    if _meaning_score(best, words) == 0:
        return None  # no icon means what the card says: none, never a random one
    return best.id, ws.dir / best.path
