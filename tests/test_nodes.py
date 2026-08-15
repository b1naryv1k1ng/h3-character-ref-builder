from __future__ import annotations

import json

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder.nodes import H3CharacterReference

from .test_character_store import add_audio, add_image


def test_node_resolves_defaults_by_media_uuid_not_array_index(store, monkeypatch):
    profile = store.create_profile("Ari")
    first = add_image(store, profile["id"], "First", (10, 20, 30))
    unused = add_image(store, profile["id"], "Unused", (40, 50, 60))
    third = add_image(store, profile["id"], "Third", (70, 80, 90))
    audio = add_audio(store, profile["id"], "Voice")
    store.set_defaults(
        profile["id"], image_1=first["id"], image_2=third["id"], audio=audio["id"]
    )

    profile_path = store.characters_root / profile["id"] / "profile.json"
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["images"] = [data["images"][1], data["images"][2], data["images"][0]]
    profile_path.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "load_image", lambda path: path.name)
    monkeypatch.setattr(node_module, "load_audio", lambda path: path.name)

    image_1, image_2, selected_audio = H3CharacterReference().load_character(
        profile["id"]
    )

    assert first["id"] in image_1
    assert third["id"] in image_2
    assert unused["id"] not in {image_1, image_2}
    assert audio["id"] in selected_audio


def test_node_output_contract_remains_compact():
    assert H3CharacterReference.RETURN_TYPES == ("IMAGE", "IMAGE", "AUDIO")
    assert H3CharacterReference.RETURN_NAMES == ("image_1", "image_2", "audio")
