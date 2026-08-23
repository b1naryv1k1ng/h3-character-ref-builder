from __future__ import annotations

import pytest

from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder.nodes import H3CharacterReference, H3PromptEnhancer
from h3_character_ref_builder.prompt_builder import DEFAULT_MUSIC

from .test_prompt_enhancer import SYSTEM_PROMPT, context_json


def test_enhancer_omits_v1_preflight_validator_but_character_node_keeps_it():
    assert "VALIDATE_INPUTS" not in H3PromptEnhancer.__dict__
    assert "VALIDATE_INPUTS" in H3CharacterReference.__dict__

    duration_type, duration_options = H3PromptEnhancer.INPUT_TYPES()["required"][
        "duration_seconds"
    ]
    assert duration_type == "INT"
    assert duration_options["min"] == 1
    assert duration_options["max"] == 60


def test_resolved_linked_and_widget_strings_share_the_runtime_execution_path(
    monkeypatch,
):
    calls = []
    config = enhancer.EnhancerConfig(
        api_key="unused-test-key",
        endpoint="https://provider.example/v1/chat/completions",
        model="test-model",
        timeout_seconds=5,
    )

    def fake_request(**kwargs):
        calls.append(kwargs)
        return {
            "detailed_description": "[Shot 1] [0-5s] She turns toward the door.",
            "additional_soundscape": "A quiet footstep.",
        }

    monkeypatch.setattr(enhancer, "load_enhancer_config", lambda: config)
    monkeypatch.setattr(enhancer, "_request_enhancement", fake_request)
    enhancer.clear_enhancement_cache()
    node = H3PromptEnhancer()

    upstream_character_context = context_json()
    upstream_system_prompt = SYSTEM_PROMPT
    linked_result = node.enhance_prompt(
        upstream_character_context,
        15,
        upstream_system_prompt,
        "turn toward the door",
        "",
        DEFAULT_MUSIC,
    )

    enhancer.clear_enhancement_cache()
    widget_result = node.enhance_prompt(
        context_json(),
        15,
        SYSTEM_PROMPT,
        "turn toward the door",
        "",
        DEFAULT_MUSIC,
    )

    assert linked_result == widget_result
    assert len(calls) == 2
    assert calls[0]["system_prompt"] == upstream_system_prompt
    assert calls[0]["scene_definition"] == "a quiet workshop"
    assert calls[1]["system_prompt"] == SYSTEM_PROMPT
    enhancer.clear_enhancement_cache()


@pytest.mark.parametrize(
    (
        "character_context",
        "duration_seconds",
        "system_prompt",
        "action_idea",
        "error_message",
    ),
    [
        (context_json(), 15, " \n\t ", "walk", "System Prompt is required"),
        (context_json(), 15, SYSTEM_PROMPT, " \t", "Action Idea is required"),
        (
            "not character context JSON",
            15,
            SYSTEM_PROMPT,
            "walk",
            "Invalid character_context JSON",
        ),
        (
            context_json(),
            0,
            SYSTEM_PROMPT,
            "walk",
            "Duration must be between 1 and 60 seconds",
        ),
        (
            context_json(),
            61,
            SYSTEM_PROMPT,
            "walk",
            "Duration must be between 1 and 60 seconds",
        ),
    ],
)
def test_runtime_validation_fails_before_any_provider_request(
    monkeypatch,
    character_context,
    duration_seconds,
    system_prompt,
    action_idea,
    error_message,
):
    provider_calls = []

    def unexpected_provider_request(**kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("provider request must not run after validation failure")

    monkeypatch.setattr(enhancer, "_request_enhancement", unexpected_provider_request)

    with pytest.raises(RuntimeError, match=error_message):
        H3PromptEnhancer().enhance_prompt(
            character_context,
            duration_seconds,
            system_prompt,
            action_idea,
            "",
            DEFAULT_MUSIC,
        )

    assert provider_calls == []
