import os

import btd
from btd.config import DEFAULT_AWS_REGION, load_env, require


def test_imports():
    assert btd.__doc__


def test_aws_region_defaults_to_eu_west_1(monkeypatch, tmp_path):
    for key in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(key, raising=False)
    load_env(tmp_path / "missing.env")
    assert os.environ["AWS_REGION"] == DEFAULT_AWS_REGION == "eu-west-1"
    assert os.environ["AWS_DEFAULT_REGION"] == "eu-west-1"


def test_aws_region_env_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    load_env(tmp_path / "missing.env")
    assert os.environ["AWS_DEFAULT_REGION"] == "eu-central-1"


def test_require_reports_missing(monkeypatch):
    monkeypatch.delenv("SURELY_NOT_SET", raising=False)
    try:
        require("SURELY_NOT_SET")
    except RuntimeError as exc:
        assert "SURELY_NOT_SET" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_handler(monkeypatch):
    monkeypatch.setenv("LLMKIT_SINKS", "none")
    monkeypatch.setenv("LLMKIT_PROJECT", "btd")
    from btd import handlers

    assert handlers.example({}, None) == {"ok": True}
