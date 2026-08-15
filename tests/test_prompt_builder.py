from __future__ import annotations

import re

import pytest

from h3_character_ref_builder.prompt_builder import (
    DEFAULT_SOUNDSCAPE,
    build_ref2va_prompt,
)

SECTION_NAMES = [
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]


def record(role):
    return {"id": "unused-in-builder", "file": "unused", "label": "", "role": role}


def build(**overrides):
    values = {
        "character": {"description": "a small scar above the left eyebrow"},
        "image_1": record("face_identity"),
        "image_2": record("full_body_identity"),
        "audio": record("voice_identity"),
        "scene": {"definition": "  a quiet beach\nwith pale sand  "},
        "detailed_description": 'She says <d>[English] "Hello there."</d> and waves.',
        "overall_soundscape": "Gentle surf and footsteps.",
        "non_diegetic_music": "N/A",
    }
    values.update(overrides)
    return build_ref2va_prompt(**values)


def section(prompt, name):
    start = prompt.index(f"{name}:\n") + len(name) + 2
    later = [prompt.find(f"\n\n{other}:\n", start) for other in SECTION_NAMES]
    endings = [value for value in later if value >= 0]
    return prompt[start : min(endings) if endings else len(prompt)]


def test_prompt_has_exact_six_sections_in_order_and_common_role_wording():
    prompt = build()
    assert re.findall(r"(?m)^([a-z_]+):$", prompt) == SECTION_NAMES
    definitions = section(prompt, "subject_definitions")
    assert "facial identity, facial structure, eyes, hair" in definitions
    assert "full-body appearance, body proportions, wardrobe" in definitions
    assert "same character" in definitions
    assert "do not blend the references into different people" in definitions
    assert "a small scar above the left eyebrow" in definitions
    assert "<Subject 2> is a quiet beach\nwith pale sand" in definitions


@pytest.mark.parametrize(
    ("role", "wording"),
    [
        (
            "alternate_identity",
            "additional identity, anatomy, and alternate-angle detail",
        ),
        ("wardrobe", "wardrobe, clothing details, colors, and accessories"),
        ("general", "additional appearance detail"),
    ],
)
def test_alternate_image_roles_use_central_semantics(role, wording):
    assert wording in build(image_1=record(role))


def test_pose_and_expression_roles_are_narrow_and_do_not_copy_source_scene():
    prompt = build(image_1=record("pose_orientation"), image_2=record("expression"))
    definitions = section(prompt, "subject_definitions")
    assert "provides only body orientation and pose guidance" in definitions
    assert "provides only facial expression and performance detail" in definitions
    assert (
        definitions.count("Do not retain its background, lighting, or camera framing")
        == 2
    )


@pytest.mark.parametrize(
    ("role", "wording"),
    [
        ("voice_identity", "voice-timbre, accent, pacing, and delivery reference"),
        ("delivery_emotion", "vocal tone, emotional delivery, intensity, and pacing"),
        ("general", "general vocal characteristics and delivery guidance"),
    ],
)
def test_audio_roles_use_reference_marker_and_never_preserve_source(role, wording):
    prompt = build(audio=record(role))
    assert wording in prompt
    assert "The source words are not copied." in prompt
    retention = section(prompt, "retention_analysis")
    assert "<Audio 1>: reference -" in retention
    assert "<Audio 1>: fully_preserved" not in retention
    assert "without copying the original signal or source dialogue" in retention


def test_no_scene_omits_subject_2_everywhere():
    prompt = build(scene=None)
    assert "<Subject 2>" not in prompt
    assert "featuring <Subject 1>, using <Audio 1>" in section(prompt, "summary")


def test_user_action_is_verbatim_only_in_detailed_description():
    action = 'She says <d>[English] "Unique exact dialogue."</d> and turns.'
    prompt = build(detailed_description=action)
    assert section(prompt, "detailed_description") == f"[Shot 1] {action}"
    assert prompt.count("Unique exact dialogue") == 1
    assert "[Shot 2]" not in prompt
    assert section(prompt, "summary").startswith(
        "[reference generation + audio reference]"
    )


def test_existing_shot_marker_is_not_duplicated_and_later_shots_are_preserved():
    action = "[Shot 1] First action.\n[Shot 2] User-authored continuation."
    prompt = build(detailed_description=action)
    assert section(prompt, "detailed_description") == action
    assert prompt.count("[Shot 2]") == 1


def test_soundscape_and_music_preservation_and_empty_fallbacks():
    prompt = build(
        overall_soundscape="  custom ambience  ", non_diegetic_music="  soft cello  "
    )
    assert section(prompt, "overall_soundscape") == "custom ambience"
    assert section(prompt, "non_diegetic_music") == "soft cello"
    fallback = build(overall_soundscape=" ", non_diegetic_music="")
    assert section(fallback, "overall_soundscape") == DEFAULT_SOUNDSCAPE
    assert section(fallback, "non_diegetic_music") == "N/A"
