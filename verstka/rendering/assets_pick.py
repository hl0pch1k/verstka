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
    "idea": ["idea", "bulb", "иде", "light"],
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


def pick_asset(manifest: TemplateManifest, ws: TemplateWorkspace, hint: Optional[str], kinds: tuple[str, ...] = ("illustration", "photo"), exclude: Optional[set[str]] = None, min_px: int = 200) -> Optional[Path]:
    exclude = exclude or set()
    cands = [a for a in manifest.assets if a.kind in kinds and a.id not in exclude and max(a.width, a.height) >= min_px and not a.path.endswith(".svg")]
    if not cands:
        return None
    words = _expand(hint)
    cands.sort(key=lambda a: (-_score(a, words), -(a.width * a.height)))
    best = cands[0]
    return ws.dir / best.path


def pick_icon(manifest: TemplateManifest, ws: TemplateWorkspace, hint: Optional[str], exclude: Optional[set[str]] = None) -> Optional[tuple[str, Path]]:
    exclude = exclude or set()
    cands = [a for a in manifest.assets if a.kind == "icon" and a.id not in exclude and a.has_alpha and not a.path.endswith(".svg") and a.width >= 24]
    if not cands:
        return None
    words = _expand(hint)
    cands.sort(key=lambda a: (-_score(a, words), -(a.width * a.height)))
    best = cands[0]
    if words and _score(best, words) == 0:
        return None  # no semantic match: keep the template's own icon rather than a random one
    return best.id, ws.dir / best.path
