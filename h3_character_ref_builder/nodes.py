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
    DESCRIPTION = "Loads two images and one audio reference from a saved character profile."

    @classmethod
    def VALIDATE_INPUTS(cls, character):
        if not character:
            return "No character selected. Create a profile in H3 Character Manager."
        try:
            validate_character_id(character)
        except InvalidCharacterId as exc:
            return str(exc)
        # Existence is deliberately checked by execution/fingerprinting so a deleted
        # UUID produces the package's explicit missing-profile error, not a combo error.
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
        store = get_default_store()
        # Resolve all paths before decoding so incomplete profiles fail with a clear slot.
        image_1_path = store.media_path(character, "reference_image_1")
        image_2_path = store.media_path(character, "reference_image_2")
        audio_path = store.media_path(character, "reference_audio")
        return (
            load_image(image_1_path),
            load_image(image_2_path),
            load_audio(audio_path),
        )
