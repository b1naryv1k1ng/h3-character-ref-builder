from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder.enhancer_config import ProviderConfigStore
from h3_character_ref_builder.nodes import H3PromptEnhancer
from h3_character_ref_builder.prompt_builder import (
    DEFAULT_SOUNDSCAPE,
    assemble_ref2va_prompt,
    parse_character_context,
    serialize_character_context,
)

from .test_prompt_builder import SECTION_NAMES, section

SYSTEM_PROMPT = "Exact workflow system instructions.\nReturn only the requested JSON."


def character_context(**overrides):
    value = {
        "schema_version": 1,
        "subject_definitions": "<Subject 1> deterministic definitions",
        "summary": "[reference generation + audio reference] deterministic summary",
        "retention_analysis": "<Subject 1>: deterministic retention",
        "scene_definition": "a quiet workshop",
        "default_soundscape": "soft room tone and distant ventilation",
    }
    value.update(overrides)
    return value


def context_json(**overrides):
    return serialize_character_context(character_context(**overrides))


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size] if size >= 0 else self.body


def completion(content=None, *, parsed=None):
    message = {}
    if content is not None:
        message["content"] = content
    if parsed is not None:
        message["parsed"] = parsed
    return {"choices": [{"message": message}]}


@pytest.fixture(autouse=True)
def configured_enhancer(monkeypatch, tmp_path):
    config_store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    monkeypatch.setattr(
        enhancer, "get_default_provider_config_store", lambda: config_store
    )
    enhancer.clear_enhancement_cache()
    monkeypatch.setenv(enhancer.API_KEY_ENV, "test-secret-key")
    monkeypatch.setenv(enhancer.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(enhancer.MODEL_ENV, "environment-model")
    monkeypatch.delenv(enhancer.TIMEOUT_ENV, raising=False)
    yield
    enhancer.clear_enhancement_cache()


def test_parse_character_context_accepts_v1_and_rejects_invalid_json_and_version():
    parsed = parse_character_context(context_json())
    assert parsed == character_context()

    with pytest.raises(ValueError, match="Invalid character_context JSON"):
        parse_character_context("not json")
    with pytest.raises(
        ValueError, match="Unsupported character_context schema_version"
    ):
        parse_character_context(context_json(schema_version=2))


@pytest.mark.parametrize(
    ("baseline", "additional", "expected"),
    [
        (
            "baseline ambience",
            "footsteps",
            "baseline ambience footsteps",
        ),
        ("  baseline ambience  ", " \n\t ", "baseline ambience"),
        ("", "footsteps", "footsteps"),
        ("", "", DEFAULT_SOUNDSCAPE),
    ],
)
def test_final_prompt_has_exact_order_and_soundscape_variants(
    baseline, additional, expected
):
    prompt = assemble_ref2va_prompt(
        character_context=character_context(default_soundscape=baseline),
        detailed_description="[Shot 1] [0-5s] She walks forward.",
        additional_soundscape=additional,
        non_diegetic_music="",
    )

    assert [
        line.removesuffix(":")
        for line in prompt.splitlines()
        if line.endswith(":") and line.removesuffix(":") in SECTION_NAMES
    ] == SECTION_NAMES
    assert (
        section(prompt, "subject_definitions")
        == character_context()["subject_definitions"]
    )
    assert section(prompt, "summary") == character_context()["summary"]
    assert (
        section(prompt, "retention_analysis")
        == character_context()["retention_analysis"]
    )
    assert section(prompt, "detailed_description") == (
        "[Shot 1] [0-5s] She walks forward."
    )
    assert section(prompt, "overall_soundscape") == expected
    assert prompt.count("overall_soundscape:") == 1
    assert "Additional action-specific sounds:" not in prompt
    assert section(prompt, "non_diegetic_music") == "N/A"


def test_structured_content_parses_plain_json_fences_and_provider_parsed_object():
    expected = {
        "detailed_description": "[Shot 1] [0-3s] She turns.",
        "additional_soundscape": "Shoes pivot softly.",
    }
    assert enhancer.parse_enhancement_content(json.dumps(expected)) == expected
    assert (
        enhancer.parse_enhancement_content("```json\n" + json.dumps(expected) + "\n```")
        == expected
    )
    assert enhancer.parse_enhancement_content(expected) == expected


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        json.dumps(
            {"detailed_description": "Missing shot marker", "additional_soundscape": ""}
        ),
        json.dumps(
            {
                "detailed_description": "[Shot 1] valid",
                "additional_soundscape": 4,
            }
        ),
    ],
)
def test_malformed_structured_content_is_rejected(content):
    with pytest.raises(enhancer.PromptEnhancerError):
        enhancer.parse_enhancement_content(content)


def test_api_request_uses_strict_schema_and_sends_only_enhancement_context(monkeypatch):
    captured = {}
    result = {
        "detailed_description": "[Shot 1] [0-4s] She lifts a cup.",
        "additional_soundscape": "Ceramic touches wood.",
    }

    def fake_open(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse(completion(json.dumps(result)))

    monkeypatch.setattr(enhancer, "urlopen", fake_open)
    config = enhancer.load_enhancer_config()
    output = enhancer._request_enhancement(
        config=config,
        system_prompt=SYSTEM_PROMPT,
        scene_definition="a workshop",
        duration_seconds=12,
        action_idea="lift the cup",
        additional_notes="keep the hand steady",
    )

    assert output == result
    body = captured["body"]
    assert body["model"] == "environment-model"
    assert body["messages"][0] == {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    assert len(body["messages"]) == 2
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload == {
        "duration_seconds": 12,
        "action_idea": "lift the cup",
        "scene_definition": "a workshop",
        "additional_notes": "keep the hand steady",
    }
    serialized_user_payload = json.dumps(user_payload)
    assert SYSTEM_PROMPT not in serialized_user_payload
    assert "system_prompt" not in user_payload
    assert "subject_definitions" not in serialized_user_payload
    assert "retention_analysis" not in serialized_user_payload
    assert captured["authorization"] == "Bearer test-secret-key"
    assert captured["timeout"] == 60


def test_request_payload_omits_empty_optional_context_fields():
    payload = enhancer._request_payload(
        config=enhancer.load_enhancer_config(),
        system_prompt=SYSTEM_PROMPT,
        scene_definition="  \n ",
        duration_seconds=8,
        action_idea="look toward the door",
        additional_notes="\t",
        structured=True,
    )

    assert payload["messages"][0] == {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    assert json.loads(payload["messages"][1]["content"]) == {
        "duration_seconds": 8,
        "action_idea": "look toward the door",
    }
    assert len(payload["messages"]) == 2


def test_api_retries_without_response_format_when_provider_rejects_it(monkeypatch):
    calls = []
    expected = {
        "detailed_description": "[Shot 1] [0-2s] She nods.",
        "additional_soundscape": "",
    }

    def fake_open(request, timeout):
        del timeout
        body = json.loads(request.data)
        calls.append(body)
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"error":{"message":"response_format unsupported"}}'),
            )
        return FakeResponse(completion(json.dumps(expected)))

    monkeypatch.setattr(enhancer, "urlopen", fake_open)
    output = enhancer._request_enhancement(
        config=enhancer.load_enhancer_config(),
        system_prompt=SYSTEM_PROMPT,
        scene_definition="",
        duration_seconds=2,
        action_idea="nod",
        additional_notes="",
    )

    assert output == expected
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "authentication failed"),
        (403, "authentication failed"),
        (429, "rate limit"),
        (503, "unavailable"),
    ],
)
def test_provider_http_errors_are_clear(monkeypatch, status, expected):
    def fake_open(request, timeout):
        del timeout
        raise HTTPError(
            request.full_url,
            status,
            "failure",
            {},
            io.BytesIO(b'{"error":{"message":"provider detail"}}'),
        )

    monkeypatch.setattr(enhancer, "urlopen", fake_open)
    with pytest.raises(enhancer.PromptEnhancerError, match=expected):
        enhancer._request_enhancement(
            config=enhancer.load_enhancer_config(),
            system_prompt=SYSTEM_PROMPT,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )


def test_network_timeout_and_malformed_provider_response_are_clear(monkeypatch):
    config = enhancer.load_enhancer_config()
    monkeypatch.setattr(
        enhancer,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError(TimeoutError())),
    )
    with pytest.raises(enhancer.PromptEnhancerError, match="timed out"):
        enhancer._request_enhancement(
            config=config,
            system_prompt=SYSTEM_PROMPT,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )

    monkeypatch.setattr(
        enhancer,
        "urlopen",
        lambda request, timeout: FakeResponse({"unexpected": True}),
    )
    with pytest.raises(enhancer.PromptEnhancerError, match=r"missing choices\[0\]"):
        enhancer._request_enhancement(
            config=config,
            system_prompt=SYSTEM_PROMPT,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )


def test_missing_api_key_and_error_text_never_expose_key(monkeypatch):
    monkeypatch.delenv(enhancer.API_KEY_ENV)
    with pytest.raises(enhancer.PromptEnhancerError, match=enhancer.API_KEY_ENV):
        enhancer.load_enhancer_config()

    secret = "never-print-this-key"
    monkeypatch.setenv(enhancer.API_KEY_ENV, secret)

    def fake_open(request, timeout):
        del timeout
        body = json.dumps({"error": {"message": f"bad credential {secret}"}}).encode()
        raise HTTPError(request.full_url, 418, "failure", {}, io.BytesIO(body))

    monkeypatch.setattr(enhancer, "urlopen", fake_open)
    with pytest.raises(enhancer.PromptEnhancerError) as error:
        enhancer._request_enhancement(
            config=enhancer.load_enhancer_config(),
            system_prompt=SYSTEM_PROMPT,
            scene_definition="",
            duration_seconds=4,
            action_idea="turn",
            additional_notes="",
        )
    assert secret not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_paid_call_cache_reuses_same_inputs_and_music_or_baseline_changes(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return {
            "detailed_description": "[Shot 1] [0-15s] She walks steadily.",
            "additional_soundscape": "Measured footsteps.",
        }

    monkeypatch.setattr(enhancer, "_request_enhancement", fake_request)
    node = H3PromptEnhancer()
    first = node.enhance_prompt(context_json(), 15, SYSTEM_PROMPT, "walk", "", "N/A")
    second = node.enhance_prompt(
        context_json(), 15, SYSTEM_PROMPT, "walk", "", "soft piano"
    )
    changed_baseline = node.enhance_prompt(
        context_json(default_soundscape="changed baseline"),
        15,
        SYSTEM_PROMPT,
        "walk",
        "",
        "soft piano",
    )

    assert len(calls) == 1
    assert "default_soundscape" not in calls[0]
    assert first[1:] == second[1:] == changed_baseline[1:]
    assert first[2] == "Measured footsteps."
    assert section(first[0], "overall_soundscape").endswith("Measured footsteps.")
    assert section(first[0], "non_diegetic_music") == "N/A"
    assert section(second[0], "non_diegetic_music") == "soft piano"
    assert section(changed_baseline[0], "overall_soundscape").startswith(
        "changed baseline"
    )

    node.enhance_prompt(
        context_json(), 15, "Different workflow instructions.", "walk", "", "N/A"
    )
    assert len(calls) == 2
    assert calls[0]["system_prompt"] == SYSTEM_PROMPT
    assert calls[1]["system_prompt"] == "Different workflow instructions."


def test_paid_call_cache_changes_for_action_duration_and_scene_context(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return {
            "detailed_description": "[Shot 1] valid",
            "additional_soundscape": "",
        }

    monkeypatch.setattr(enhancer, "_request_enhancement", fake_request)
    common = {
        "system_prompt": SYSTEM_PROMPT,
        "additional_notes": "",
    }
    enhancer.get_enhancement(
        character_context=character_context(),
        duration_seconds=15,
        action_idea="walk",
        **common,
    )
    enhancer.get_enhancement(
        character_context=character_context(),
        duration_seconds=15,
        action_idea="run",
        **common,
    )
    enhancer.get_enhancement(
        character_context=character_context(),
        duration_seconds=20,
        action_idea="run",
        **common,
    )
    enhancer.get_enhancement(
        character_context=character_context(scene_definition="a different room"),
        duration_seconds=20,
        action_idea="run",
        **common,
    )

    assert len(calls) == 4
    assert calls[2]["scene_definition"] == "a quiet workshop"
    assert calls[3]["scene_definition"] == "a different room"


def test_comfy_fingerprint_tracks_final_inputs_but_never_api_key(monkeypatch):
    base = H3PromptEnhancer.IS_CHANGED(
        context_json(), 15, SYSTEM_PROMPT, "walk", "", "N/A"
    )
    assert (
        H3PromptEnhancer.IS_CHANGED(
            context_json(), 15, SYSTEM_PROMPT, "walk", "", "music"
        )
        != base
    )
    assert (
        H3PromptEnhancer.IS_CHANGED(
            context_json(), 20, SYSTEM_PROMPT, "walk", "", "N/A"
        )
        != base
    )
    assert (
        H3PromptEnhancer.IS_CHANGED(context_json(), 15, SYSTEM_PROMPT, "run", "", "N/A")
        != base
    )
    assert (
        H3PromptEnhancer.IS_CHANGED(
            context_json(), 15, "changed system", "walk", "", "N/A"
        )
        != base
    )
    monkeypatch.setenv(enhancer.API_KEY_ENV, "a-different-secret")
    assert (
        H3PromptEnhancer.IS_CHANGED(
            context_json(), 15, SYSTEM_PROMPT, "walk", "", "N/A"
        )
        == base
    )
