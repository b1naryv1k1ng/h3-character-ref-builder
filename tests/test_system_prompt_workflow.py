from __future__ import annotations

from pathlib import Path

import pytest

from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder.nodes import H3PromptEnhancer

from .test_prompt_enhancer import character_context, context_json


def test_system_prompt_is_a_workflow_editable_multiline_widget():
    required = H3PromptEnhancer.INPUT_TYPES()["required"]
    assert list(required) == [
        "character_context",
        "duration_seconds",
        "system_prompt",
        "action_idea",
        "additional_notes",
        "non_diegetic_music",
    ]
    input_type, options = required["system_prompt"]
    assert input_type == "STRING"
    assert options["default"] == ""
    assert options["multiline"] is True
    assert options["dynamicPrompts"] is False
    assert "forceInput" not in options


def test_empty_system_prompt_fails_node_and_runtime_validation():
    assert H3PromptEnhancer.VALIDATE_INPUTS(
        context_json(), 15, " \n\t ", "walk"
    ) == "System Prompt is required."

    with pytest.raises(enhancer.PromptEnhancerError, match="System Prompt is required"):
        enhancer.get_enhancement(
            character_context=character_context(),
            duration_seconds=15,
            system_prompt=" \n\t ",
            action_idea="walk",
            additional_notes="",
        )


def test_no_hard_coded_system_prompt_module_remains():
    package = Path(__file__).parents[1] / "h3_character_ref_builder"
    assert not (package / "enhancer_system_prompt.py").exists()
    source = (package / "prompt_enhancer.py").read_text(encoding="utf-8")
    assert "H3_ACTION_ENHANCER_SYSTEM_PROMPT" not in source
    assert "SYSTEM_PROMPT_VERSION" not in source
