from __future__ import annotations

import json

import pytest

from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder.enhancer_config import ProviderConfigStore

SYSTEM_PROMPT = "Workflow-owned system instructions."


def context():
    return {
        "schema_version": 1,
        "subject_definitions": "<Subject 1> definition",
        "summary": "summary",
        "retention_analysis": "retention",
        "scene_definition": "a quiet room",
        "default_soundscape": "room tone",
    }


@pytest.fixture
def configured_store(tmp_path, monkeypatch):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    store.update_provider(
        base_url="https://first.example/v1",
        model="first-model",
        timeout_seconds=25,
    )
    store.set_api_key("first-secret")
    monkeypatch.setattr(enhancer, "get_default_provider_config_store", lambda: store)
    enhancer.clear_enhancement_cache()
    yield store
    enhancer.clear_enhancement_cache()


def test_effective_saved_provider_values_are_used_for_requests(
    configured_store, monkeypatch
):
    captured = []

    def fake_request(**kwargs):
        captured.append(kwargs["config"])
        return {
            "detailed_description": "[Shot 1] configured request",
            "additional_soundscape": "",
        }

    monkeypatch.setattr(enhancer, "_request_enhancement", fake_request)
    enhancer.get_enhancement(
        character_context=context(),
        duration_seconds=10,
        system_prompt=SYSTEM_PROMPT,
        action_idea="turn",
        additional_notes="",
    )

    assert len(captured) == 1
    assert captured[0].endpoint == "https://first.example/v1/chat/completions"
    assert captured[0].model == "first-model"
    assert captured[0].timeout_seconds == 25
    assert captured[0].api_key == "first-secret"


def test_live_config_cache_boundaries(configured_store, monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs["config"])
        return {
            "detailed_description": f"[Shot 1] request {len(calls)}",
            "additional_soundscape": "",
        }

    monkeypatch.setattr(enhancer, "_request_enhancement", fake_request)
    common = {
        "character_context": context(),
        "duration_seconds": 10,
        "system_prompt": SYSTEM_PROMPT,
        "action_idea": "turn",
        "additional_notes": "",
    }

    first = enhancer.get_enhancement(**common)
    configured_store.update_provider(
        base_url="https://first.example/v1",
        model="first-model",
        timeout_seconds=120,
    )
    after_timeout = enhancer.get_enhancement(**common)
    configured_store.set_api_key("replacement-secret")
    after_key = enhancer.get_enhancement(**common)
    assert len(calls) == 1
    assert first == after_timeout == after_key

    configured_store.update_provider(
        base_url="https://first.example/v1",
        model="second-model",
        timeout_seconds=120,
    )
    enhancer.get_enhancement(**common)
    assert len(calls) == 2
    assert calls[-1].model == "second-model"
    assert calls[-1].api_key == "replacement-secret"

    configured_store.update_provider(
        base_url="https://second.example/api/v1",
        model="second-model",
        timeout_seconds=120,
    )
    enhancer.get_enhancement(**common)
    assert len(calls) == 3
    assert calls[-1].endpoint == "https://second.example/api/v1/chat/completions"


def test_execution_fingerprint_excludes_timeout_and_api_key(configured_store):
    kwargs = {
        "character_context": json.dumps(context()),
        "duration_seconds": 10,
        "system_prompt": SYSTEM_PROMPT,
        "action_idea": "turn",
        "additional_notes": "",
        "non_diegetic_music": "N/A",
    }
    baseline = enhancer.enhancer_execution_fingerprint(**kwargs)

    configured_store.update_provider(
        base_url="https://first.example/v1",
        model="first-model",
        timeout_seconds=180,
    )
    assert enhancer.enhancer_execution_fingerprint(**kwargs) == baseline
    configured_store.set_api_key("different-secret")
    assert enhancer.enhancer_execution_fingerprint(**kwargs) == baseline

    configured_store.update_provider(
        base_url="https://first.example/v1",
        model="different-model",
        timeout_seconds=180,
    )
    after_model = enhancer.enhancer_execution_fingerprint(**kwargs)
    assert after_model != baseline

    configured_store.update_provider(
        base_url="https://different.example/v1",
        model="different-model",
        timeout_seconds=180,
    )
    assert enhancer.enhancer_execution_fingerprint(**kwargs) != after_model


def test_api_key_is_excluded_from_paid_cache_key():
    common = {
        "endpoint": "https://provider.example/v1/chat/completions",
        "model": "model",
        "timeout_seconds": 60,
    }
    first = enhancer.EnhancerConfig(api_key="first-secret", **common)
    second = enhancer.EnhancerConfig(api_key="second-secret", **common)
    inputs = {
        "system_prompt": SYSTEM_PROMPT,
        "scene_definition": "scene",
        "duration_seconds": 10,
        "action_idea": "turn",
        "additional_notes": "",
    }
    assert enhancer._enhancement_cache_key(config=first, **inputs) == (
        enhancer._enhancement_cache_key(config=second, **inputs)
    )
