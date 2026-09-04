"""Deterministic MiniMax H3 Ref2VA context and prompt composition."""

from __future__ import annotations

import json
import re
from typing import Any

from .roles import AUDIO_ROLE_METADATA, IMAGE_ROLE_METADATA, validate_role

LEGACY_CHARACTER_CONTEXT_SCHEMA_VERSION = 1
CHARACTER_CONTEXT_SCHEMA_VERSION = 2
CHARACTER_CONTEXT_FIELDS = (
    "subject_roles",
    "subject_definitions",
    "summary",
    "retention_analysis",
    "scene_definition",
    "default_soundscape",
)
CHARACTER_CONTEXT_TEXT_FIELDS = CHARACTER_CONTEXT_FIELDS[1:]
SUBJECT_TOKEN_PATTERN = re.compile(r"^<Subject ([1-9][0-9]*)>$")
DEFAULT_SOUNDSCAPE = (
    "Natural diegetic ambience appropriate to the scene, with synchronized physical "
    "sounds caused by the visible action."
)
DEFAULT_MUSIC = "N/A"


def _picture_definition(number: int, role: str) -> str:
    validate_role("image", role)
    picture = f"<Picture {number}>"
    semantic = IMAGE_ROLE_METADATA[role]["definition"]
    if role in {"pose_orientation", "expression"}:
        return (
            f"{picture} provides only {semantic}. Do not retain its background, "
            "lighting, or camera framing."
        )
    return f"{picture} contributes {semantic}."


def _character_subject_definition(
    *,
    character: dict[str, Any],
    image_1: dict[str, Any],
    image_2: dict[str, Any],
    subject_number: int,
    picture_1_number: int,
    picture_2_number: int,
) -> str:
    image_1_role = validate_role("image", image_1.get("role"))
    image_2_role = validate_role("image", image_2.get("role"))
    subject = f"<Subject {subject_number}>"
    picture_1 = f"<Picture {picture_1_number}>"
    picture_2 = f"<Picture {picture_2_number}>"
    result = (
        f"{subject} is the same character defined jointly by {picture_1} and "
        f"{picture_2}. "
        f"{_picture_definition(picture_1_number, image_1_role)} "
        f"{_picture_definition(picture_2_number, image_2_role)} "
        "Preserve one coherent identity throughout; do not blend the references into "
        "different people. The reference images define identity and physical appearance "
        "only; do not retain their source backgrounds, lighting, camera framing, pose, "
        "expression, or wardrobe unless explicitly requested."
    )
    identity_details = str(character.get("description", "")).strip()
    if identity_details:
        result += f" Additional stable character information: {identity_details}"
    return result


def _audio_definition(role: str, *, audio_number: int, subject_number: int) -> str:
    validate_role("audio", role)
    audio = f"<Audio {audio_number}>"
    subject = f"<Subject {subject_number}>"
    if role == "voice_identity":
        return (
            f"{audio} is the voice-timbre, accent, pacing, and delivery reference "
            f"for {subject}. The source words are not copied."
        )
    if role == "delivery_emotion":
        return (
            f"{audio} provides vocal tone, emotional delivery, intensity, and pacing "
            f"for {subject}. The source words are not copied."
        )
    return (
        f"{audio} provides general vocal characteristics and delivery guidance for "
        f"{subject}. The source words are not copied."
    )


def _scene_subject_definition(
    scene: dict[str, Any], *, subject_number: int, picture_number: int
) -> str:
    definition = str(scene.get("definition", "")).strip()
    subject = f"<Subject {subject_number}>"
    if scene.get("reference_image") is not None:
        picture = f"<Picture {picture_number}>"
        result = (
            f"{subject} is the environment defined by {picture}. {picture} provides "
            "the established environment's spatial layout, architecture, major objects, "
            "materials, lighting, and overall visual appearance. Preserve the environment "
            "as one coherent location throughout the video."
        )
        if definition:
            result += (
                " The saved scene definition supplements the visual reference: "
                + definition
            )
        return result
    return f"{subject} is {definition}"


def _scene_retention(
    scene: dict[str, Any], *, subject_number: int, picture_number: int
) -> str:
    subject = f"<Subject {subject_number}>"
    if scene.get("reference_image") is not None:
        picture = f"<Picture {picture_number}>"
        return (
            f"{subject} (appears throughout [Shot 1]): fully_preserved - preserve "
            f"the environment defined by {picture}, including its established geometry, "
            "layout, major objects, materials, lighting direction, and defining visual "
            "characteristics throughout the video."
        )
    return (
        f"{subject} (appears throughout [Shot 1]): fully_preserved - preserve the "
        "environment's established geometry, layout, lighting direction, and defining "
        "characteristics throughout the video."
    )


def _character_retention(
    *, subject_number: int, picture_1_number: int, picture_2_number: int
) -> str:
    return (
        f"<Subject {subject_number}> (appears in [Shot 1]): fully_preserved - preserve "
        "the same recognizable identity and the stable appearance attributes defined by "
        f"<Picture {picture_1_number}> and <Picture {picture_2_number}>; pose, expression, "
        "lighting, framing, and action follow the requested scene rather than the static "
        "reference images."
    )


def _audio_retention(role: str, *, audio_number: int) -> str:
    audio_role = validate_role("audio", role)
    semantic = AUDIO_ROLE_METADATA[audio_role]["retention"]
    return (
        f"<Audio {audio_number}>: reference - preserve {semantic} without copying the "
        "original signal or source dialogue."
    )


def _prop_subject_definition(prop: dict[str, Any], picture_number: int) -> str:
    name = str(prop["name"]).strip()
    picture = f"<Picture {picture_number}>"
    result = (
        f"{picture} provides the visual reference for the {name} appearing in the "
        f"video. Whenever the {name} is visible, preserve its shape, proportions, "
        f"color, surface appearance, and distinctive visual details from {picture}. "
        f"{picture} defines the {name} only; do not retain its source background, "
        "lighting, camera framing, surrounding body, hands, pose, or unrelated content."
    )
    description = str(prop.get("description", "")).strip()
    if description:
        result += f" Additional prop information: {description}"
    return result


def _prop_retention(prop: dict[str, Any], picture_number: int) -> str:
    name = str(prop["name"]).strip()
    picture = f"<Picture {picture_number}>"
    return (
        f"{picture}: fully_preserved - use {picture} as the visual reference for the "
        f"{name}; preserve its defining shape, proportions, color, surface appearance, "
        f"and distinctive visible details whenever the {name} appears."
    )


def _subject_role(role_type: str, name: object) -> dict[str, str]:
    return {"type": role_type, "name": str(name or "").strip()}


def _scene_text(scene: dict[str, Any] | None, field: str) -> str:
    return str(scene.get(field, "")).strip() if scene is not None else ""


def build_character_context_data(
    *,
    character: dict[str, Any],
    image_1: dict[str, Any],
    image_2: dict[str, Any],
    audio: dict[str, Any],
    scene: dict[str, Any] | None,
    prop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic schema-v2 context for one referenced character."""
    audio_role = validate_role("audio", audio.get("role"))
    subject_lines = [
        _character_subject_definition(
            character=character,
            image_1=image_1,
            image_2=image_2,
            subject_number=1,
            picture_1_number=1,
            picture_2_number=2,
        ),
        _audio_definition(audio_role, audio_number=1, subject_number=1),
    ]
    subject_roles = {
        "<Subject 1>": _subject_role("character", character.get("name", ""))
    }
    if scene is not None:
        subject_lines.append(
            _scene_subject_definition(scene, subject_number=2, picture_number=3)
        )
        subject_roles["<Subject 2>"] = _subject_role(
            "environment", scene.get("name", "")
        )
    prop_picture_number = 4 if scene and scene.get("reference_image") is not None else 3
    if prop is not None:
        subject_lines.append(_prop_subject_definition(prop, prop_picture_number))

    scene_phrase = " in <Subject 2>" if scene is not None else ""
    summary = (
        "[reference generation + audio reference] Create a video featuring "
        f"<Subject 1>{scene_phrase}, using <Audio 1> only as the vocal reference for "
        "<Subject 1>."
    )
    retention_lines = [
        _character_retention(subject_number=1, picture_1_number=1, picture_2_number=2)
    ]
    if scene is not None:
        retention_lines.append(
            _scene_retention(scene, subject_number=2, picture_number=3)
        )
    if prop is not None:
        retention_lines.append(_prop_retention(prop, prop_picture_number))
    retention_lines.append(_audio_retention(audio_role, audio_number=1))
    return {
        "schema_version": CHARACTER_CONTEXT_SCHEMA_VERSION,
        "subject_roles": subject_roles,
        "subject_definitions": "\n\n".join(subject_lines),
        "summary": summary,
        "retention_analysis": "\n".join(retention_lines),
        "scene_definition": _scene_text(scene, "definition"),
        "default_soundscape": _scene_text(scene, "default_soundscape"),
    }


def build_dual_character_context_data(
    *,
    character_1: dict[str, Any],
    character_1_image_1: dict[str, Any],
    character_1_image_2: dict[str, Any],
    character_1_audio: dict[str, Any],
    character_2: dict[str, Any],
    character_2_image_1: dict[str, Any],
    character_2_image_2: dict[str, Any],
    character_2_audio: dict[str, Any],
    scene: dict[str, Any] | None,
    prop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic schema-v2 context for two independent characters."""
    audio_1_role = validate_role("audio", character_1_audio.get("role"))
    audio_2_role = validate_role("audio", character_2_audio.get("role"))
    subject_lines = [
        _character_subject_definition(
            character=character_1,
            image_1=character_1_image_1,
            image_2=character_1_image_2,
            subject_number=1,
            picture_1_number=1,
            picture_2_number=2,
        ),
        _audio_definition(audio_1_role, audio_number=1, subject_number=1),
        _character_subject_definition(
            character=character_2,
            image_1=character_2_image_1,
            image_2=character_2_image_2,
            subject_number=2,
            picture_1_number=3,
            picture_2_number=4,
        ),
        _audio_definition(audio_2_role, audio_number=2, subject_number=2),
    ]
    subject_roles = {
        "<Subject 1>": _subject_role("character", character_1.get("name", "")),
        "<Subject 2>": _subject_role("character", character_2.get("name", "")),
    }
    if scene is not None:
        subject_lines.append(
            _scene_subject_definition(scene, subject_number=3, picture_number=5)
        )
        subject_roles["<Subject 3>"] = _subject_role(
            "environment", scene.get("name", "")
        )
    prop_picture_number = 6 if scene and scene.get("reference_image") is not None else 5
    if prop is not None:
        subject_lines.append(_prop_subject_definition(prop, prop_picture_number))

    scene_phrase = " in <Subject 3>" if scene is not None else ""
    summary = (
        "[reference generation + audio reference] Create a video featuring <Subject 1> "
        f"and <Subject 2>{scene_phrase}, using <Audio 1> only as the vocal reference for "
        "<Subject 1> and <Audio 2> only as the vocal reference for <Subject 2>."
    )
    retention_lines = [
        _character_retention(subject_number=1, picture_1_number=1, picture_2_number=2),
        _character_retention(subject_number=2, picture_1_number=3, picture_2_number=4),
    ]
    if scene is not None:
        retention_lines.append(
            _scene_retention(scene, subject_number=3, picture_number=5)
        )
    if prop is not None:
        retention_lines.append(_prop_retention(prop, prop_picture_number))
    retention_lines.extend(
        [
            _audio_retention(audio_1_role, audio_number=1),
            _audio_retention(audio_2_role, audio_number=2),
        ]
    )
    return {
        "schema_version": CHARACTER_CONTEXT_SCHEMA_VERSION,
        "subject_roles": subject_roles,
        "subject_definitions": "\n\n".join(subject_lines),
        "summary": summary,
        "retention_analysis": "\n".join(retention_lines),
        "scene_definition": _scene_text(scene, "definition"),
        "default_soundscape": _scene_text(scene, "default_soundscape"),
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
    prop: dict[str, Any] | None = None,
) -> str:
    return serialize_character_context(
        build_character_context_data(
            character=character,
            image_1=image_1,
            image_2=image_2,
            audio=audio,
            scene=scene,
            prop=prop,
        )
    )


def build_dual_character_context(
    *,
    character_1: dict[str, Any],
    character_1_image_1: dict[str, Any],
    character_1_image_2: dict[str, Any],
    character_1_audio: dict[str, Any],
    character_2: dict[str, Any],
    character_2_image_1: dict[str, Any],
    character_2_image_2: dict[str, Any],
    character_2_audio: dict[str, Any],
    scene: dict[str, Any] | None,
    prop: dict[str, Any] | None = None,
) -> str:
    return serialize_character_context(
        build_dual_character_context_data(
            character_1=character_1,
            character_1_image_1=character_1_image_1,
            character_1_image_2=character_1_image_2,
            character_1_audio=character_1_audio,
            character_2=character_2,
            character_2_image_1=character_2_image_1,
            character_2_image_2=character_2_image_2,
            character_2_audio=character_2_audio,
            scene=scene,
            prop=prop,
        )
    )


def _validate_subject_roles(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or not value:
        raise TypeError("character_context subject_roles must be a non-empty object.")
    normalized: dict[str, dict[str, str]] = {}
    subject_numbers: list[int] = []
    environment_count = 0
    for token, role in value.items():
        if (
            not isinstance(token, str)
            or (match := SUBJECT_TOKEN_PATTERN.fullmatch(token)) is None
        ):
            raise ValueError(
                f"character_context has invalid subject role token {token!r}."
            )
        if not isinstance(role, dict) or set(role) != {"type", "name"}:
            raise TypeError(
                f"character_context subject role {token!r} must contain type and name."
            )
        role_type = role["type"]
        name = role["name"]
        if role_type not in {"character", "environment"}:
            raise ValueError(
                f"character_context subject role {token!r} has invalid type."
            )
        if not isinstance(name, str):
            raise TypeError(
                f"character_context subject role {token!r} name must be a string."
            )
        if role_type == "environment":
            environment_count += 1
        subject_numbers.append(int(match.group(1)))
        normalized[token] = {"type": role_type, "name": name.strip()}
    if sorted(subject_numbers) != list(range(1, len(subject_numbers) + 1)):
        raise ValueError(
            "character_context subject_roles must use consecutive Subject tokens starting at 1."
        )
    if environment_count > 1:
        raise ValueError(
            "character_context subject_roles may contain at most one environment."
        )
    if not any(role["type"] == "character" for role in normalized.values()):
        raise ValueError("character_context subject_roles must contain a character.")
    return {
        token: normalized[token]
        for token in sorted(
            normalized,
            key=lambda item: int(SUBJECT_TOKEN_PATTERN.fullmatch(item).group(1)),
        )
    }


def normalize_character_context_data(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise TypeError("character_context JSON must be an object.")
    version = context.get("schema_version")
    if type(version) is not int or version not in {
        LEGACY_CHARACTER_CONTEXT_SCHEMA_VERSION,
        CHARACTER_CONTEXT_SCHEMA_VERSION,
    }:
        raise ValueError(
            "Unsupported character_context schema_version: "
            f"{version!r}; expected 1 or {CHARACTER_CONTEXT_SCHEMA_VERSION}."
        )
    for field in CHARACTER_CONTEXT_TEXT_FIELDS:
        if field not in context:
            raise ValueError(f"character_context is missing required field {field!r}.")
        if not isinstance(context[field], str):
            raise TypeError(f"character_context field {field!r} must be a string.")
    for field in ("subject_definitions", "summary", "retention_analysis"):
        if not context[field].strip():
            raise ValueError(f"character_context field {field!r} must not be empty.")
    if version == LEGACY_CHARACTER_CONTEXT_SCHEMA_VERSION:
        subject_roles = {"<Subject 1>": {"type": "character", "name": ""}}
        legacy_text = "\n".join(
            context[field]
            for field in ("subject_definitions", "summary", "retention_analysis")
        )
        if context["scene_definition"].strip() or "<Subject 2>" in legacy_text:
            subject_roles["<Subject 2>"] = {"type": "environment", "name": ""}
    else:
        if "subject_roles" not in context:
            raise ValueError(
                "character_context is missing required field 'subject_roles'."
            )
        subject_roles = _validate_subject_roles(context["subject_roles"])
    return {
        "schema_version": CHARACTER_CONTEXT_SCHEMA_VERSION,
        "subject_roles": subject_roles,
        **{key: context[key] for key in CHARACTER_CONTEXT_TEXT_FIELDS},
    }


def parse_character_context(value: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TypeError("character_context must be a JSON string.")
    try:
        context = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid character_context JSON.") from exc
    return normalize_character_context_data(context)


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
    context = normalize_character_context_data(character_context)
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
    prop: dict[str, Any] | None = None,
) -> str:
    """Backward-compatible deterministic builder used by tests and integrations."""
    context = build_character_context_data(
        character=character,
        image_1=image_1,
        image_2=image_2,
        audio=audio,
        scene=scene,
        prop=prop,
    )
    return assemble_ref2va_prompt(
        character_context=context,
        detailed_description=detailed_description,
        additional_soundscape=overall_soundscape,
        non_diegetic_music=non_diegetic_music,
    )
