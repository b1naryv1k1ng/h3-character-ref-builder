"""Deterministic MiniMax H3 Ref2VA context and prompt composition."""

from __future__ import annotations

import json
from typing import Any

from .roles import AUDIO_ROLE_METADATA, IMAGE_ROLE_METADATA, validate_role

CHARACTER_CONTEXT_SCHEMA_VERSION = 1
CHARACTER_CONTEXT_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "scene_definition",
    "default_soundscape",
)
DEFAULT_SOUNDSCAPE = (
    "Natural diegetic ambience appropriate to the scene, with synchronized physical "
    "sounds caused by the visible action."
)
DEFAULT_MUSIC = "N/A"


def _picture_definition(number: int, role: str) -> str:
    validate_role("image", role)
    subject = f"<Picture {number}>"
    semantic = IMAGE_ROLE_METADATA[role]["definition"]
    if role == "pose_orientation":
        return (
            f"{subject} provides only {semantic}. Do not retain its background, "
            "lighting, or camera framing."
        )
    if role == "expression":
        return (
            f"{subject} provides only {semantic}. Do not retain its background, "
            "lighting, or camera framing."
        )
    return f"{subject} contributes {semantic}."


def _audio_definition(role: str) -> str:
    validate_role("audio", role)
    if role == "voice_identity":
        return (
            "<Audio 1> is the voice-timbre, accent, pacing, and delivery reference "
            "for <Subject 1>. The source words are not copied."
        )
    if role == "delivery_emotion":
        return (
            "<Audio 1> provides vocal tone, emotional delivery, intensity, and pacing "
            "for <Subject 1>. The source words are not copied."
        )
    return (
        "<Audio 1> provides general vocal characteristics and delivery guidance for "
        "<Subject 1>. The source words are not copied."
    )


def _scene_subject_definition(scene: dict[str, Any]) -> str:
    definition = str(scene.get("definition", "")).strip()
    if scene.get("reference_image") is not None:
        result = (
            "<Subject 2> is the environment defined by <Picture 3>. <Picture 3> "
            "provides the established environment's spatial layout, architecture, "
            "major objects, materials, lighting, and overall visual appearance. "
            "Preserve the environment as one coherent location throughout the video."
        )
        if definition:
            result += (
                " The saved scene definition supplements the visual reference: "
                + definition
            )
        return result
    return f"<Subject 2> is {definition}"


def _scene_retention(scene: dict[str, Any]) -> str:
    if scene.get("reference_image") is not None:
        return (
            "<Subject 2> (appears throughout [Shot 1]): fully_preserved - preserve "
            "the environment defined by <Picture 3>, including its established "
            "geometry, layout, major objects, materials, lighting direction, and "
            "defining visual characteristics throughout the video."
        )
    return (
        "<Subject 2> (appears throughout [Shot 1]): fully_preserved - preserve the "
        "environment's established geometry, layout, lighting direction, and "
        "defining characteristics throughout the video."
    )


def build_character_context_data(
    *,
    character: dict[str, Any],
    image_1: dict[str, Any],
    image_2: dict[str, Any],
    audio: dict[str, Any],
    scene: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the deterministic, media-free context consumed by the enhancer."""
    image_1_role = validate_role("image", image_1.get("role"))
    image_2_role = validate_role("image", image_2.get("role"))
    audio_role = validate_role("audio", audio.get("role"))

    subject_1 = (
        "<Subject 1> is the same character defined jointly by <Picture 1> and "
        "<Picture 2>. "
        f"{_picture_definition(1, image_1_role)} "
        f"{_picture_definition(2, image_2_role)} "
        "Preserve one coherent identity throughout; do not blend the references into "
        "different people. The reference images define identity and physical appearance "
        "only; do not retain their source backgrounds, lighting, camera framing, pose, "
        "expression, or wardrobe unless explicitly requested."
    )
    identity_details = str(character.get("description", "")).strip()
    if identity_details:
        subject_1 += f" Additional stable character information: {identity_details}"

    subject_lines = [subject_1, _audio_definition(audio_role)]
    if scene is not None:
        subject_lines.append(_scene_subject_definition(scene))

    scene_phrase = " in <Subject 2>" if scene is not None else ""
    summary = (
        "[reference generation + audio reference] Create a video featuring "
        f"<Subject 1>{scene_phrase}, using <Audio 1> only as the vocal reference for "
        "<Subject 1>."
    )

    retention_lines = [
        (
            "<Subject 1> (appears in [Shot 1]): fully_preserved - preserve the same "
            "recognizable identity and the stable appearance attributes defined by "
            "<Picture 1> and <Picture 2>; pose, expression, lighting, framing, and action "
            "follow the requested scene rather than the static reference images."
        )
    ]
    if scene is not None:
        retention_lines.append(_scene_retention(scene))
    audio_retention = AUDIO_ROLE_METADATA[audio_role]["retention"]
    retention_lines.append(
        f"<Audio 1>: reference - preserve {audio_retention} without copying the "
        "original signal or source dialogue."
    )
    return {
        "schema_version": CHARACTER_CONTEXT_SCHEMA_VERSION,
        "subject_definitions": "\n\n".join(subject_lines),
        "summary": summary,
        "retention_analysis": "\n".join(retention_lines),
        "scene_definition": (
            str(scene.get("definition", "")).strip() if scene is not None else ""
        ),
        "default_soundscape": (
            str(scene.get("default_soundscape", "")).strip()
            if scene is not None
            else ""
        ),
    }


def serialize_character_context(context: dict[str, Any]) -> str:
    """Serialize context as stable, human-inspectable JSON."""
    return json.dumps(context, ensure_ascii=False, indent=2)


def build_character_context(
    *,
    character: dict[str, Any],
    image_1: dict[str, Any],
    image_2: dict[str, Any],
    audio: dict[str, Any],
    scene: dict[str, Any] | None,
) -> str:
    return serialize_character_context(
        build_character_context_data(
            character=character,
            image_1=image_1,
            image_2=image_2,
            audio=audio,
            scene=scene,
        )
    )


def parse_character_context(value: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TypeError("character_context must be a JSON string.")
    try:
        context = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid character_context JSON.") from exc
    if not isinstance(context, dict):
        raise TypeError("character_context JSON must be an object.")
    version = context.get("schema_version")
    if type(version) is not int or version != CHARACTER_CONTEXT_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported character_context schema_version: "
            f"{version!r}; expected {CHARACTER_CONTEXT_SCHEMA_VERSION}."
        )
    for field in CHARACTER_CONTEXT_FIELDS:
        if field not in context:
            raise ValueError(f"character_context is missing required field {field!r}.")
        if not isinstance(context[field], str):
            raise TypeError(f"character_context field {field!r} must be a string.")
    for field in ("subject_definitions", "summary", "retention_analysis"):
        if not context[field].strip():
            raise ValueError(f"character_context field {field!r} must not be empty.")
    return {
        "schema_version": version,
        **{key: context[key] for key in CHARACTER_CONTEXT_FIELDS},
    }


def combine_soundscape(default_soundscape: str, additional_soundscape: str) -> str:
    baseline = default_soundscape.strip()
    additional = additional_soundscape.strip()
    if baseline and additional:
        return f"{baseline} {additional}"
    if baseline:
        return baseline
    if additional:
        return additional
    return DEFAULT_SOUNDSCAPE


def assemble_ref2va_prompt(
    *,
    character_context: dict[str, Any],
    detailed_description: str,
    additional_soundscape: str,
    non_diegetic_music: str,
) -> str:
    """Assemble the exact six-section prompt without rewriting deterministic fields."""
    context = parse_character_context(serialize_character_context(character_context))
    action = detailed_description.strip()
    if not action.startswith("[Shot 1]"):
        action = f"[Shot 1] {action}".rstrip()
    music = non_diegetic_music.strip() or DEFAULT_MUSIC
    soundscape = combine_soundscape(
        context["default_soundscape"], additional_soundscape
    )
    sections = [
        "subject_definitions:\n" + context["subject_definitions"],
        "summary:\n" + context["summary"],
        "retention_analysis:\n" + context["retention_analysis"],
        "detailed_description:\n" + action,
        "overall_soundscape:\n" + soundscape,
        "non_diegetic_music:\n" + music,
    ]
    return "\n\n".join(sections)


def build_ref2va_prompt(
    *,
    character: dict[str, Any],
    image_1: dict[str, Any],
    image_2: dict[str, Any],
    audio: dict[str, Any],
    scene: dict[str, Any] | None,
    detailed_description: str,
    overall_soundscape: str,
    non_diegetic_music: str,
) -> str:
    """Backward-compatible deterministic builder used by tests and integrations."""
    context = build_character_context_data(
        character=character,
        image_1=image_1,
        image_2=image_2,
        audio=audio,
        scene=scene,
    )
    return assemble_ref2va_prompt(
        character_context=context,
        detailed_description=detailed_description,
        additional_soundscape=overall_soundscape,
        non_diegetic_music=non_diegetic_music,
    )
