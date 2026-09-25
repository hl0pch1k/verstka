"""One request to the final's model endpoint (configs/models.vk.yaml by default): is the model there, how fast, and is
its thinking off? Run it as soon as the VK inference key arrives, before the first deck:

    VERSTKA_MODELS=configs/models.vk.yaml .venv/bin/python scripts/vk_smoke.py [path/to/models.yaml]

Prints the seconds, prompt/completion tokens, finish_reason and the answer's length — never the key or the URL's
secrets. A completion bill far above the answer's length (or finish_reason=length on this tiny answer) means the host
runs the model with thinking on: the answers of the agent would be cut off. Then set the link's switch (extra_body
chat_template_kwargs.enable_thinking: false for vLLM/SGLang, or system_suffix "/no_think") — see the config's notes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verstka  # noqa: E402,F401  (loads .env: the key stays in the process, it is never printed)
import yaml  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from verstka.providers.base import ChatMessage  # noqa: E402
from verstka.providers.openai_compat import OpenAICompatProvider, extract_json  # noqa: E402
from verstka.providers.registry import ProviderRegistry, default_models_path  # noqa: E402


class _Answer(BaseModel):
    headline: str = ""
    figure: str = ""


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "configs/models.vk.yaml" if not default_models_path().name.endswith("vk.yaml") else default_models_path())
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    reg = ProviderRegistry.from_config(cfg)
    p = reg.get("llm")
    links = getattr(p, "links", None) or [p]
    link = next((x for x in links if isinstance(x, OpenAICompatProvider)), None)
    if link is None:
        print(f"{path.name}: the llm role is not an OpenAI-compatible link")
        return 2
    if link.off:
        print(f"{path.name}: no key for {link.label} (its variable is empty) — nothing sent")
        return 2
    messages = [
        ChatMessage(role="system", content="You write one slide headline. Answer with JSON only: {\"headline\": \"...\", \"figure\": \"...\"}."),
        ChatMessage(role="user", content="Выручка кофейни: 900 000 рублей в месяц, цель — 1 138 500 рублей. Заголовок-вывод до 10 слов."),
    ]
    from verstka.providers.openai_compat import _with_system_suffix, to_openai_messages

    oai = to_openai_messages(messages)
    if link.system_suffix:
        oai = _with_system_suffix(oai, link.system_suffix)
    t0 = time.monotonic()
    try:
        text, usage, finish = link._call(oai, 0.2, 300, want_json=True, deadline=time.monotonic() + 120)
    except Exception as e:  # noqa: BLE001 - the smoke test reports, it does not raise
        from verstka.providers.status import mask

        print(f"{link.label}: FAILED after {time.monotonic() - t0:.1f} s — {mask(str(e))[:300]}")
        return 1
    sec = time.monotonic() - t0
    try:
        ok = bool(_Answer.model_validate(extract_json(text, {"headline", "figure"})).headline)
    except Exception:  # noqa: BLE001
        ok = False
    est = max(1, len(text) // 3)
    thinking = finish == "length" or (usage.completion_tokens >= 150 and usage.completion_tokens > 3 * est)
    print(f"{link.label}: {sec:.1f} s, prompt {usage.prompt_tokens} / completion {usage.completion_tokens} tokens, finish_reason={finish}, answer {len(text)} chars, JSON {'ok' if ok else 'NOT ok'}")
    print(f"  extra_body: {sorted(link.extra_body) or 'none'}; system_suffix: {link.system_suffix or 'none'}")
    print("  thinking: " + ("SEEMS ON — set the switch in the config before the first deck" if thinking else "off (the bill matches the answer)"))
    return 0 if ok and not thinking else 1


if __name__ == "__main__":
    raise SystemExit(main())
