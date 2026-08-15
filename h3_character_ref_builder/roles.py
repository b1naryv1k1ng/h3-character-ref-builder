"""Central media-role metadata for storage, UI, prompts, and retention."""

from __future__ import annotations

from typing import Any

IMAGE_ROLE_METADATA = {
    "face_identity": {
        "label": "Face / Identity",
        "definition": "facial identity, facial structure, eyes, hair, and recognizable facial detail",
    },
    "full_body_identity": {
        "label": "Full Body / Physical Identity",
        "definition": "full-body identity, body proportions, build, silhouette, skin tone, and distinctive physical details",
    },
    "alternate_identity": {
        "label": "Alternate Identity Angle",
        "definition": "additional identity, anatomy, and alternate-angle detail",
    },
    "wardrobe": {
        "label": "Wardrobe / Clothing",
        "definition": "wardrobe, clothing details, colors, and accessories",
    },
    "pose_orientation": {
        "label": "Pose / Orientation",
        "definition": "body orientation and pose guidance",
    },
    "expression": {
        "label": "Expression",
        "definition": "facial expression and performance detail",
    },
    "general": {
        "label": "General Reference",
        "definition": "additional appearance detail",
    },
}

AUDIO_ROLE_METADATA = {
    "voice_identity": {
        "label": "Voice Identity",
        "definition": "voice timbre, accent, pacing, and delivery",
        "retention": "voice timbre, accent, pacing, and delivery",
    },
    "delivery_emotion": {
        "label": "Delivery / Emotion",
        "definition": "vocal tone, emotional delivery, intensity, and pacing",
        "retention": "vocal tone, emotional delivery, intensity, and pacing",
    },
    "general": {
        "label": "General Audio Reference",
        "definition": "general vocal characteristics and delivery",
        "retention": "general vocal characteristics and delivery",
    },
}

IMAGE_ROLES = frozenset(IMAGE_ROLE_METADATA)
AUDIO_ROLES = frozenset(AUDIO_ROLE_METADATA)
DEFAULT_MEDIA_ROLES = {"image": "general", "audio": "general"}


def validate_role(media_type: str, role: Any) -> str:
    """Return a supported role or raise a user-facing validation error."""
    roles = (
        IMAGE_ROLES
        if media_type == "image"
        else AUDIO_ROLES
        if media_type == "audio"
        else None
    )
    if roles is None:
        raise ValueError(f"Unsupported media type for role validation: {media_type!r}.")
    if not isinstance(role, str) or role not in roles:
        allowed = ", ".join(sorted(roles))
        raise ValueError(
            f"Invalid {media_type} role {role!r}. Supported roles: {allowed}."
        )
    return role
