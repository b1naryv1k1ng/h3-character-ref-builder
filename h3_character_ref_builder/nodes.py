"""ComfyUI node implementations."""

from __future__ import annotations

import hashlib
import json

from .character_store import (
    InvalidCharacterId,
    get_default_store,
    validate_character_id,
)
from .media import load_audio, load_image
from .prompt_builder import (
    DEFAULT_MUSIC,
    assemble_ref2va_prompt,
    build_character_context,
    parse_character_context,
)
from .prompt_enhancer import (
    PromptEnhancerError,
    enhancer_execution_fingerprint,
    get_enhancement,
)
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
                        "label": "Character",
                        "tooltip": "Character profile managed by H3 Reference Manager.",
                    },
                ),
            },
            "optional": {
                "scene": (
                    scene_ids,
                    {
                        "default": NO_SCENE,
                        "label": "Scene Preset",
                        "tooltip": "Optional reusable Scene Preset.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("image_1", "image_2", "audio", "character_context")
    FUNCTION = "load_character"
    CATEGORY = "H3/Reference"
    DESCRIPTION = "Loads active references and builds deterministic H3 character context."

    @classmethod
    def VALIDATE_INPUTS(cls, character, scene=NO_SCENE, *legacy_values, **legacy_inputs):
        del legacy_values, legacy_inputs
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
    def IS_CHANGED(cls, character, scene=NO_SCENE, *legacy_values, **legacy_inputs):
        del legacy_values, legacy_inputs
        if not character:
            return "no-character-selected"
        scene_fingerprint = "no-scene"
        if scene != NO_SCENE:
            scene_fingerprint = get_default_scene_store().prompt_fingerprint(scene)
        relevant = {
            "character": get_default_store().fingerprint(character),
            "scene_selection": scene,
            "scene": scene_fingerprint,
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def load_character(self, character, scene=NO_SCENE, *legacy_values, **legacy_inputs):
        del legacy_values, legacy_inputs
        if not character:
            raise ValueError(
                "No character selected. Create a profile in H3 Reference Manager."
            )
        selected = get_default_store().resolve_selected_references(character)
        scene_data = None
        if scene != NO_SCENE:
            scene_data = get_default_scene_store().get_scene(scene)
        character_context = build_character_context(
            character=selected["profile"],
            image_1=selected["records"]["image_1"],
            image_2=selected["records"]["image_2"],
            audio=selected["records"]["audio"],
            scene=scene_data,
        )
        return (
            load_image(selected["paths"]["image_1"]),
            load_image(selected["paths"]["image_2"]),
            load_audio(selected["paths"]["audio"]),
            character_context,
        )


class H3PromptEnhancer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_context": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Connect character_context from H3 Character Reference.",
                    },
                ),
                "duration_seconds": (
                    "INT",
                    {"default": 15, "min": 1, "max": 60, "step": 1},
                ),
                "system_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "dynamicPrompts": False,
                        "label": "System Prompt",
                        "tooltip": (
                            "Workflow-owned provider instructions. This widget can be "
                            "converted to a connected STRING input in ComfyUI."
                        ),
                    },
                ),
                "action_idea": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "dynamicPrompts": False,
                        "label": "Action Idea",
                    },
                ),
                "additional_notes": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "dynamicPrompts": False,
                        "label": "Additional Notes",
                    },
                ),
                "non_diegetic_music": (
                    "STRING",
                    {
                        "default": DEFAULT_MUSIC,
                        "multiline": True,
                        "dynamicPrompts": False,
                        "label": "Non-Diegetic Music",
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "detailed_description", "additional_soundscape")
    FUNCTION = "enhance_prompt"
    CATEGORY = "H3/Prompt"
    DESCRIPTION = "Enhances action choreography and assembles the final H3 prompt."

    @classmethod
    def IS_CHANGED(
        cls,
        character_context,
        duration_seconds,
        system_prompt,
        action_idea,
        additional_notes="",
        non_diegetic_music=DEFAULT_MUSIC,
    ):
        return enhancer_execution_fingerprint(
            character_context=character_context,
            duration_seconds=duration_seconds,
            system_prompt=system_prompt,
            action_idea=action_idea,
            additional_notes=additional_notes,
            non_diegetic_music=non_diegetic_music,
        )

    def enhance_prompt(
        self,
        character_context,
        duration_seconds,
        system_prompt,
        action_idea,
        additional_notes="",
        non_diegetic_music=DEFAULT_MUSIC,
    ):
        try:
            context = parse_character_context(character_context)
            enhancement = get_enhancement(
                character_context=context,
                duration_seconds=duration_seconds,
                system_prompt=system_prompt,
                action_idea=action_idea,
                additional_notes=additional_notes,
            )
        except (TypeError, ValueError, PromptEnhancerError) as exc:
            raise RuntimeError(str(exc)) from exc
        prompt = assemble_ref2va_prompt(
            character_context=context,
            detailed_description=enhancement["detailed_description"],
            additional_soundscape=enhancement["additional_soundscape"],
            non_diegetic_music=non_diegetic_music,
        )
        return (
            prompt,
            enhancement["detailed_description"],
            enhancement["additional_soundscape"],
        )
