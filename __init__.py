"""ComfyUI registration for H3 Character Ref Builder."""

try:
    from .h3_character_ref_builder.nodes import H3CharacterReference, H3PromptEnhancer
    from .h3_character_ref_builder.routes import register_routes
except ImportError:
    # Pytest may collect this hyphenated directory as a top-level module.
    from h3_character_ref_builder.nodes import H3CharacterReference, H3PromptEnhancer
    from h3_character_ref_builder.routes import register_routes


NODE_CLASS_MAPPINGS = {
    "H3CharacterReference": H3CharacterReference,
    "H3PromptEnhancer": H3PromptEnhancer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3CharacterReference": "H3 Character Reference",
    "H3PromptEnhancer": "H3 Prompt Enhancer",
}

WEB_DIRECTORY = "./web"

try:
    register_routes()
except ModuleNotFoundError as error:
    if error.name not in {"server", "folder_paths", "aiohttp"}:
        raise

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
