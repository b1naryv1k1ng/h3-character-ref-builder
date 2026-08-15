"""Deterministic MiniMax H3 Ref2VA prompt composition."""

from __future__ import annotations

from typing import Any

from .roles import AUDIO_ROLE_METADATA, IMAGE_ROLE_METADATA, validate_role

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


def _soundscape(scene: dict[str, Any] | None, additional: str) -> str:
    scene_default = (
        str(scene.get("default_soundscape", "")).strip() if scene is not None else ""
    )
    parts = [part for part in (scene_default, additional.strip()) if part]
    return " ".join(parts) if parts else DEFAULT_SOUNDSCAPE


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
    """Build the exact six-section Ref2VA prompt without rewriting user prose."""
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
        subject_lines.append(f"<Subject 2> is {str(scene['definition']).strip()}")

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
        retention_lines.append(
            "<Subject 2> (appears throughout [Shot 1]): fully_preserved - preserve the "
            "environment's established geometry, layout, lighting direction, and "
            "defining characteristics throughout the video."
        )
    audio_retention = AUDIO_ROLE_METADATA[audio_role]["retention"]
    retention_lines.append(
        f"<Audio 1>: reference - preserve {audio_retention} without copying the "
        "original signal or source dialogue."
    )

    action = detailed_description.strip()
    if not action.startswith("[Shot 1]"):
        action = f"[Shot 1] {action}".rstrip()
    soundscape = _soundscape(scene, overall_soundscape)
    music = non_diegetic_music.strip() or DEFAULT_MUSIC

    sections = [
        "subject_definitions:\n" + "\n\n".join(subject_lines),
        "summary:\n" + summary,
        "retention_analysis:\n" + "\n".join(retention_lines),
        "detailed_description:\n" + action,
        "overall_soundscape:\n" + soundscape,
        "non_diegetic_music:\n" + music,
    ]
    return "\n\n".join(sections)
