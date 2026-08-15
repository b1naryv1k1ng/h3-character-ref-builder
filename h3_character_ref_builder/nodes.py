"""ComfyUI node implementation."""

from __future__ import annotations

import hashlib
import json

from .character_store import (
    InvalidCharacterId,
    get_default_store,
    validate_character_id,
)
from .media import load_audio, load_image
from .prompt_builder import DEFAULT_MUSIC, DEFAULT_SOUNDSCAPE, build_ref2va_prompt
from .scene_store import InvalidSceneId, get_default_scene_store, validate_scene_id

NO_SCENE = "__h3_no_scene_preset__"


class H3CharacterReference:
    @classmethod
    def INPUT_TYPES(cls):
        profiles = get_default_store().list_profiles()
        character_ids = [profile["id"] for profile in profiles] or [""]
        scene_ids = [
            NO_SCENE,
            *[scene["id"] for scene in get_default_scene_store().list_scenes()],
        ]
        return {
            "required": {
                "character": (
                    character_ids,
                    {
                        "default": character_ids[0],
                        "tooltip": "Character profile managed by H3 Reference Manager.",
                    },
                ),
            },
            # Optional inputs preserve execution compatibility with workflows saved
            # before V3 while still rendering normal widgets for new nodes.
            "optional": {
                "scene": (
                    scene_ids,
                    {
                        "default": NO_SCENE,
                        "tooltip": "Optional reusable Scene Preset.",
                    },
                ),
                "detailed_description": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "dynamicPrompts": False,
                        "tooltip": "Video / Action Description used verbatim in detailed_description.",
                    },
                ),
                "overall_soundscape": (
                    "STRING",
                    {
                        "default": DEFAULT_SOUNDSCAPE,
                        "multiline": True,
                        "dynamicPrompts": False,
                    },
                ),
                "non_diegetic_music": (
                    "STRING",
                    {
                        "default": DEFAULT_MUSIC,
                        "multiline": True,
                        "dynamicPrompts": False,
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("image_1", "image_2", "audio", "prompt")
    FUNCTION = "load_character"
    CATEGORY = "H3/Reference"
    DESCRIPTION = "Loads active character references and builds an H3 Ref2VA prompt."

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        character,
        scene=NO_SCENE,
        detailed_description="",
        overall_soundscape=DEFAULT_SOUNDSCAPE,
        non_diegetic_music=DEFAULT_MUSIC,
    ):
        del detailed_description, overall_soundscape, non_diegetic_music
        if not character:
            return "No character selected. Create a profile in H3 Reference Manager."
        try:
            validate_character_id(character)
            if scene != NO_SCENE:
                validate_scene_id(scene)
        except (InvalidCharacterId, InvalidSceneId) as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(
        cls,
        character,
        scene=NO_SCENE,
        detailed_description="",
        overall_soundscape=DEFAULT_SOUNDSCAPE,
        non_diegetic_music=DEFAULT_MUSIC,
    ):
        if not character:
            return "no-character-selected"
        scene_fingerprint = "no-scene"
        if scene != NO_SCENE:
            scene_fingerprint = get_default_scene_store().prompt_fingerprint(scene)
        relevant = {
            "character": get_default_store().fingerprint(character),
            "scene_selection": scene,
            "scene": scene_fingerprint,
            "detailed_description": detailed_description,
            "overall_soundscape": overall_soundscape,
            "non_diegetic_music": non_diegetic_music,
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def load_character(
        self,
        character,
        scene=NO_SCENE,
        detailed_description="",
        overall_soundscape=DEFAULT_SOUNDSCAPE,
        non_diegetic_music=DEFAULT_MUSIC,
    ):
        if not character:
            raise ValueError(
                "No character selected. Create a profile in H3 Reference Manager."
            )
        selected = get_default_store().resolve_selected_references(character)
        scene_data = None
        if scene != NO_SCENE:
            scene_data = get_default_scene_store().get_scene(scene)
        prompt = build_ref2va_prompt(
            character=selected["profile"],
            image_1=selected["records"]["image_1"],
            image_2=selected["records"]["image_2"],
            audio=selected["records"]["audio"],
            scene=scene_data,
            detailed_description=detailed_description,
            overall_soundscape=overall_soundscape,
            non_diegetic_music=non_diegetic_music,
        )
        return (
            load_image(selected["paths"]["image_1"]),
            load_image(selected["paths"]["image_2"]),
            load_audio(selected["paths"]["audio"]),
            prompt,
        )
