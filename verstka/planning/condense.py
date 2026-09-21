"""Text condensing: LLM skill with a deterministic fallback."""

from __future__ import annotations

import re
from typing import Optional

from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.outline import CondensedText
from verstka.skills_registry.registry import SkillsRegistry


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    cut = " ".join(words[:max_words])
    # prefer a clause boundary inside the kept part
    m = list(re.finditer(r"[,;:—–-]\s", cut))
    if m and m[-1].start() > len(cut) * 0.5:
        cut = cut[: m[-1].start()]
    return cut.rstrip(" ,;:—–-").strip()


def condense_text(text: str, max_words: int, skills: Optional[SkillsRegistry] = None, providers: Optional[ProviderRegistry] = None, language: str = "ru") -> str:
    if len(text.split()) <= max_words:
        return text.strip()
    if skills is not None and providers is not None and providers.has("llm"):
        try:
            res = skills.run("text_condenser", providers, {"text": text, "max_words": max_words, "language": language})
            out: CondensedText = res.parsed
            if out.text.strip() and len(out.text.split()) <= max_words + 2:
                return out.text.strip()
        except (ProviderError, ValueError, KeyError):
            pass
    return trim_words(text, max_words)
