"""ComfyUI node implementation."""

from __future__ import annotations

from .character_store import (
    InvalidCharacterId,
    get_default_store,
    validate_character_id,
)
from .media import load_audio, load_image


class H3CharacterReference:
    @classmethod
    def INPUT_TYPES(cls):
        profiles = get_default_store().list_profiles()
        character_ids = [profile["id"] for profile in profiles]
        if not character_ids:
            character_ids = [""]
        return {
            "required": {
                "character": (
                    character_ids,
                    {
                        "default": character_ids[0],
                        "tooltip": "Character profile managed by H3 Character Manager.",
                    },
                )
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "AUDIO")
    RETURN_NAMES = ("image_1", "image_2", "audio")
    FUNCTION = "load_character"
    CATEGORY = "H3/Reference"
    DESCRIPTION = "Loads the active two images and audio from a character profile."

    @classmethod
    def VALIDATE_INPUTS(cls, character):
        if not character:
            return "No character selected. Create a profile in H3 Character Manager."
        try:
            validate_character_id(character)
        except InvalidCharacterId as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, character):
        if not character:
            return "no-character-selected"
        return get_default_store().fingerprint(character)

    def load_character(self, character):
        if not character:
            raise ValueError(
                "No character selected. Create a profile in H3 Character Manager."
            )
        paths = get_default_store().resolve_selected_media(character)
        return (
            load_image(paths["image_1"]),
            load_image(paths["image_2"]),
            load_audio(paths["audio"]),
        )
