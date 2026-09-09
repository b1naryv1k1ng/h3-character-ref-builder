"""ComfyUI node implementations."""

from __future__ import annotations

import hashlib
import json
import uuid

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
    build_dual_character_context,
    parse_character_context,
)
from .prompt_enhancer import (
    PromptEnhancerError,
    get_enhancement,
)
from .prop_store import InvalidPropId, get_default_prop_store, validate_prop_id
from .scene_store import InvalidSceneId, get_default_scene_store, validate_scene_id

NO_SCENE = "__h3_no_scene_preset__"
NO_PROP = "__h3_no_prop_reference__"


class H3CharacterReference:
    @classmethod
    def INPUT_TYPES(cls):
        profiles = get_default_store().list_profiles()
        character_ids = [profile["id"] for profile in profiles] or [""]
        scene_ids = [
            NO_SCENE,
            *[scene["id"] for scene in get_default_scene_store().list_scenes()],
        ]
        prop_ids = [
            NO_PROP,
            *[prop["id"] for prop in get_default_prop_store().list_usable_props()],
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
                "prop": (
                    prop_ids,
                    {
                        "default": NO_PROP,
                        "label": "Prop Reference",
                        "tooltip": "Optional reusable single-image Prop Reference.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "AUDIO", "STRING", "IMAGE", "IMAGE")
    RETURN_NAMES = (
        "character_image_1",
        "character_image_2",
        "audio",
        "character_context",
        "scene_image",
        "prop_image",
    )
    FUNCTION = "load_character"
    CATEGORY = "H3/Reference"
    DESCRIPTION = (
        "Loads active references and builds deterministic H3 character context."
    )

    @classmethod
    def VALIDATE_INPUTS(
        cls, character, scene=NO_SCENE, prop=NO_PROP, *legacy_values, **legacy_inputs
    ):
        del legacy_values, legacy_inputs
        if not character:
            return "No character selected. Create a profile in H3 Reference Manager."
        try:
            validate_character_id(character)
            if scene != NO_SCENE:
                validate_scene_id(scene)
            if prop != NO_PROP:
                try:
                    validate_prop_id(prop)
                except InvalidPropId:
                    # Pre-prop workflows may supply an obsolete positional widget here.
                    pass
        except (InvalidCharacterId, InvalidSceneId) as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(
        cls, character, scene=NO_SCENE, prop=NO_PROP, *legacy_values, **legacy_inputs
    ):
        del legacy_values, legacy_inputs
        if not character:
            return "no-character-selected"
        scene_fingerprint = "no-scene"
        if scene != NO_SCENE:
            scene_fingerprint = get_default_scene_store().prompt_fingerprint(scene)
        try:
            canonical_prop = validate_prop_id(prop) if prop != NO_PROP else None
        except InvalidPropId:
            canonical_prop = None
        prop_fingerprint = (
            get_default_prop_store().fingerprint(canonical_prop)
            if canonical_prop is not None
            else "no-prop"
        )
        relevant = {
            "character": get_default_store().fingerprint(character),
            "scene_selection": scene,
            "scene": scene_fingerprint,
            "prop_selection": canonical_prop or NO_PROP,
            "prop": prop_fingerprint,
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def load_character(
        self,
        character,
        scene=NO_SCENE,
        prop=NO_PROP,
        *legacy_values,
        **legacy_inputs,
    ):
        del legacy_values, legacy_inputs
        if not character:
            raise ValueError(
                "No character selected. Create a profile in H3 Reference Manager."
            )
        selected = get_default_store().resolve_selected_references(character)
        scene_data = None
        scene_image = None
        if scene != NO_SCENE:
            scene_store = get_default_scene_store()
            scene_data = scene_store.get_scene(scene)
            if scene_data["reference_image"] is not None:
                scene_image = load_image(scene_store.reference_image_path(scene))
        try:
            canonical_prop = validate_prop_id(prop) if prop != NO_PROP else None
        except InvalidPropId:
            canonical_prop = None
        prop_data = None
        prop_image = None
        if canonical_prop is not None:
            prop_store = get_default_prop_store()
            prop_data = prop_store.get_prop(canonical_prop)
            prop_image = load_image(prop_store.reference_image_path(canonical_prop))
        character_context = build_character_context(
            character=selected["profile"],
            image_1=selected["records"]["image_1"],
            image_2=selected["records"]["image_2"],
            audio=selected["records"]["audio"],
            scene=scene_data,
            prop=prop_data,
        )
        return (
            load_image(selected["paths"]["image_1"]),
            load_image(selected["paths"]["image_2"]),
            load_audio(selected["paths"]["audio"]),
            character_context,
            scene_image,
            prop_image,
        )


class H3DualCharacterReference:
    @classmethod
    def INPUT_TYPES(cls):
        profiles = get_default_store().list_profiles()
        character_ids = [profile["id"] for profile in profiles] or [""]
        scene_ids = [
            NO_SCENE,
            *[scene["id"] for scene in get_default_scene_store().list_scenes()],
        ]
        prop_ids = [
            NO_PROP,
            *[prop["id"] for prop in get_default_prop_store().list_usable_props()],
        ]
        return {
            "required": {
                "character_1": (
                    character_ids,
                    {
                        "default": character_ids[0],
                        "label": "Character 1",
                        "tooltip": "First character profile from H3 Reference Manager.",
                    },
                ),
                "character_2": (
                    character_ids,
                    {
                        "default": character_ids[0],
                        "label": "Character 2",
                        "tooltip": "Second character profile from H3 Reference Manager.",
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
                "prop": (
                    prop_ids,
                    {
                        "default": NO_PROP,
                        "label": "Prop Reference",
                        "tooltip": "Optional reusable single-image Prop Reference.",
                    },
                ),
            },
        }

    RETURN_TYPES = (
        "IMAGE",
        "IMAGE",
        "AUDIO",
        "IMAGE",
        "IMAGE",
        "AUDIO",
        "STRING",
        "IMAGE",
        "IMAGE",
    )
    RETURN_NAMES = (
        "character_1_image_1",
        "character_1_image_2",
        "character_1_audio",
        "character_2_image_1",
        "character_2_image_2",
        "character_2_audio",
        "character_context",
        "scene_image",
        "prop_image",
    )
    FUNCTION = "load_characters"
    CATEGORY = "H3/Reference"
    DESCRIPTION = "Loads two independent character references and builds deterministic H3 context."

    @classmethod
    def VALIDATE_INPUTS(cls, character_1, character_2, scene=NO_SCENE, prop=NO_PROP):
        del cls
        if not character_1:
            return "No Character 1 selected. Create a profile in H3 Reference Manager."
        if not character_2:
            return "No Character 2 selected. Create a profile in H3 Reference Manager."
        try:
            validate_character_id(character_1)
            validate_character_id(character_2)
            if scene != NO_SCENE:
                validate_scene_id(scene)
            if prop != NO_PROP:
                validate_prop_id(prop)
        except (InvalidCharacterId, InvalidSceneId, InvalidPropId) as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, character_1, character_2, scene=NO_SCENE, prop=NO_PROP):
        del cls
        if not character_1 or not character_2:
            return "dual-character-selection-incomplete"
        scene_fingerprint = "no-scene"
        if scene != NO_SCENE:
            scene_fingerprint = get_default_scene_store().prompt_fingerprint(scene)
        prop_fingerprint = "no-prop"
        if prop != NO_PROP:
            prop_fingerprint = get_default_prop_store().fingerprint(prop)
        relevant = {
            "character_1_selection": character_1,
            "character_1": get_default_store().fingerprint(character_1),
            "character_2_selection": character_2,
            "character_2": get_default_store().fingerprint(character_2),
            "scene_selection": scene,
            "scene": scene_fingerprint,
            "prop_selection": prop,
            "prop": prop_fingerprint,
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def load_characters(
        self,
        character_1,
        character_2,
        scene=NO_SCENE,
        prop=NO_PROP,
    ):
        if not character_1:
            raise ValueError(
                "No Character 1 selected. Create a profile in H3 Reference Manager."
            )
        if not character_2:
            raise ValueError(
                "No Character 2 selected. Create a profile in H3 Reference Manager."
            )
        character_store = get_default_store()
        selected_1 = character_store.resolve_selected_references(character_1)
        selected_2 = character_store.resolve_selected_references(character_2)
        scene_data = None
        scene_image = None
        if scene != NO_SCENE:
            scene_store = get_default_scene_store()
            scene_data = scene_store.get_scene(scene)
            if scene_data["reference_image"] is not None:
                scene_image = load_image(scene_store.reference_image_path(scene))
        prop_data = None
        prop_image = None
        if prop != NO_PROP:
            prop_store = get_default_prop_store()
            prop_data = prop_store.get_prop(prop)
            prop_image = load_image(prop_store.reference_image_path(prop))
        character_context = build_dual_character_context(
            character_1=selected_1["profile"],
            character_1_image_1=selected_1["records"]["image_1"],
            character_1_image_2=selected_1["records"]["image_2"],
            character_1_audio=selected_1["records"]["audio"],
            character_2=selected_2["profile"],
            character_2_image_1=selected_2["records"]["image_1"],
            character_2_image_2=selected_2["records"]["image_2"],
            character_2_audio=selected_2["records"]["audio"],
            scene=scene_data,
            prop=prop_data,
        )
        return (
            load_image(selected_1["paths"]["image_1"]),
            load_image(selected_1["paths"]["image_2"]),
            load_audio(selected_1["paths"]["audio"]),
            load_image(selected_2["paths"]["image_1"]),
            load_image(selected_2["paths"]["image_2"]),
            load_audio(selected_2["paths"]["audio"]),
            character_context,
            scene_image,
            prop_image,
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
    def IS_CHANGED(cls, *args, **kwargs):
        del cls, args, kwargs
        return uuid.uuid4().hex

    def enhance_prompt(
        self,
        character_context,
        duration_seconds,
        system_prompt,
        action_idea,
        additional_notes="",
        non_diegetic_music=DEFAULT_MUSIC,
        *legacy_values,
        **legacy_inputs,
    ):
        del legacy_values, legacy_inputs
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
