from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

import pytest

from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder.nodes import H3PromptEnhancer


class RawResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size] if size >= 0 else self.body


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv(enhancer.API_KEY_ENV, "secret")
    monkeypatch.setenv(enhancer.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(enhancer.MODEL_ENV, "model")
    monkeypatch.delenv(enhancer.TIMEOUT_ENV, raising=False)


def test_missing_base_url_model_and_invalid_timeout_are_clear(monkeypatch):
    monkeypatch.delenv(enhancer.BASE_URL_ENV)
    with pytest.raises(enhancer.PromptEnhancerError, match=enhancer.BASE_URL_ENV):
        enhancer.load_enhancer_config("model")

    monkeypatch.setenv(enhancer.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.delenv(enhancer.MODEL_ENV)
    with pytest.raises(enhancer.PromptEnhancerError, match=enhancer.MODEL_ENV):
        enhancer.load_enhancer_config("")

    monkeypatch.setenv(enhancer.MODEL_ENV, "model")
    monkeypatch.setenv(enhancer.TIMEOUT_ENV, "not-a-number")
    with pytest.raises(enhancer.PromptEnhancerError, match=enhancer.TIMEOUT_ENV):
        enhancer.load_enhancer_config("")


def test_dns_failure_and_malformed_http_json_are_clear(monkeypatch):
    config = enhancer.load_enhancer_config("")
    monkeypatch.setattr(
        enhancer,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            URLError("DNS name resolution failed")
        ),
    )
    with pytest.raises(enhancer.PromptEnhancerError, match="Network failure"):
        enhancer._request_enhancement(
            config=config,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )

    monkeypatch.setattr(
        enhancer,
        "urlopen",
        lambda request, timeout: RawResponse(b"not provider JSON"),
    )
    with pytest.raises(enhancer.PromptEnhancerError, match="malformed JSON"):
        enhancer._request_enhancement(
            config=config,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )


def test_api_key_is_not_a_widget_and_both_nodes_are_registered():
    inputs = H3PromptEnhancer.INPUT_TYPES()["required"]
    assert enhancer.API_KEY_ENV not in inputs
    assert "api_key" not in inputs

    registration = (Path(__file__).parents[1] / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert '"H3CharacterReference": H3CharacterReference' in registration
    assert '"H3PromptEnhancer": H3PromptEnhancer' in registration
    assert '"H3PromptEnhancer": "H3 Prompt Enhancer"' in registration
