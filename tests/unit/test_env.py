import os

from verstka.env import load_env, parse_env


def test_parse_env_handles_quotes_comments_and_export():
    text = "# comment\nexport A=1\nB='two words'\nC=\"x=y\"\nD=val # trailing\nbad line\n1X=ok\nE=\n"
    assert parse_env(text) == {"A": "1", "B": "two words", "C": "x=y", "D": "val", "1X": "ok", "E": ""}


def test_load_env_never_overrides_real_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("VERSTKA_TEST_KEEP=from_file\nVERSTKA_TEST_NEW=fresh\nVERSTKA_TEST_EMPTY=\n", encoding="utf-8")
    monkeypatch.setenv("VERSTKA_TEST_KEEP", "from_shell")
    monkeypatch.delenv("VERSTKA_TEST_NEW", raising=False)
    monkeypatch.delenv("VERSTKA_TEST_EMPTY", raising=False)
    assert load_env([env]) == [env]
    assert os.environ["VERSTKA_TEST_KEEP"] == "from_shell"
    assert os.environ["VERSTKA_TEST_NEW"] == "fresh"
    assert "VERSTKA_TEST_EMPTY" not in os.environ
    monkeypatch.delenv("VERSTKA_TEST_NEW", raising=False)


def test_load_env_ignores_missing_files(tmp_path):
    assert load_env([tmp_path / "nope.env"]) == []


def test_no_dotenv_switch_skips_implicit_files_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("VERSTKA_TEST_EXPLICIT=yes\n", encoding="utf-8")
    monkeypatch.setenv("VERSTKA_NO_DOTENV", "1")
    monkeypatch.delenv("VERSTKA_TEST_EXPLICIT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert load_env(force=True) == []  # the suite's own guard (tests/conftest.py)
    assert load_env([env]) == [env] and os.environ["VERSTKA_TEST_EXPLICIT"] == "yes"
    monkeypatch.delenv("VERSTKA_TEST_EXPLICIT", raising=False)
    assert "OPENROUTER_API_KEY" not in os.environ  # the repo's .env never leaks into tests
