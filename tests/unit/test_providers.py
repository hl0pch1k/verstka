import pytest
from pydantic import BaseModel

from verstka.providers.base import ChatMessage, ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.openai_compat import extract_json, to_openai_messages
from verstka.providers.registry import ProviderRegistry, expand_env


class Out(BaseModel):
    kind: str
    confidence: float


def test_mock_provider_parses_schema():
    p = MockProvider(responses={"classify": '{"kind": "cards", "confidence": 0.9}'})
    r = p.complete([ChatMessage(role="user", content="please classify this")], schema=Out)
    assert r.parsed.kind == "cards" and r.attempts == 1
    assert p.calls[0]["schema"] == "Out"


def test_mock_provider_default_and_missing():
    p = MockProvider(responses={"*": {"kind": "title", "confidence": 1.0}})
    assert p.complete([ChatMessage(role="user", content="anything")], schema=Out).parsed.kind == "title"
    with pytest.raises(ProviderError):
        MockProvider(responses={"x": "y"}).complete([ChatMessage(role="user", content="z")])


def test_extract_json_from_fences_and_prose():
    assert extract_json('Sure:\n```json\n{"a": 1}\n```')["a"] == 1
    assert extract_json('text {"a": {"b": 2}} tail')["a"]["b"] == 2
    assert extract_json('[{"x": "}"}]')[0]["x"] == "}"
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_images_become_image_url_parts():
    msgs = to_openai_messages([ChatMessage(role="user", content="look", images=[b"\x89PNG\r\n\x1a\n...."])])
    parts = msgs[0]["content"]
    assert parts[0]["type"] == "text" and parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_registry_loads_mock_backend(tmp_path):
    y = tmp_path / "models.yaml"
    y.write_text("roles:\n  llm: {backend: mock}\n  vlm: {backend: mock}\nlimits: {max_concurrency: 2}\n")
    reg = ProviderRegistry.from_yaml(y)
    assert reg.get("llm").name == "mock" and reg.limits.max_concurrency == 2
    with pytest.raises(ProviderError):
        reg.get("t2i")


def test_registry_builds_openai_compat_without_network(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    cfg = {"roles": {"llm": {"backend": "openai_compat", "model": "qwen/qwen3.8-27b", "api_key": "${TEST_KEY}"}}}
    assert expand_env(cfg)["roles"]["llm"]["api_key"] == "sk-test"
    reg = ProviderRegistry.from_config(cfg)
    p = reg.get("llm")
    assert p.name == "openai_compat" and p.model == "qwen/qwen3.8-27b" and p.api_key == "sk-test"
