from __future__ import annotations

import json

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder.nodes import NO_SCENE, H3CharacterReference
from h3_character_ref_builder.scene_store import SceneStore

from .test_character_store import add_audio, add_image, complete_profile


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

    image_1, image_2, selected_audio, prompt = H3CharacterReference().load_character(
        profile["id"]
    )

    assert first["id"] in image_1
    assert third["id"] in image_2
    assert unused["id"] not in {image_1, image_2}
    assert audio["id"] in selected_audio
    assert prompt.startswith("subject_definitions:")


def test_node_output_contract_preserves_first_three_and_adds_prompt():
    assert H3CharacterReference.RETURN_TYPES == ("IMAGE", "IMAGE", "AUDIO", "STRING")
    assert H3CharacterReference.RETURN_NAMES == (
        "image_1",
        "image_2",
        "audio",
        "prompt",
    )


def test_node_scene_prompt_and_fingerprint_isolate_other_scene(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    selected_scene = scenes.create_scene("Beach", "warm sand and gentle surf")
    other_scene = scenes.create_scene("Bedroom", "white walls")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "load_image", lambda path: path.name)
    monkeypatch.setattr(node_module, "load_audio", lambda path: path.name)

    before = H3CharacterReference.IS_CHANGED(profile["id"], selected_scene["id"])
    output = H3CharacterReference().load_character(
        profile["id"], selected_scene["id"], "The character walks forward."
    )
    assert "<Subject 2> is warm sand and gentle surf" in output[3]

    scenes.update_scene(other_scene["id"], definition="changed unrelated scene")
    assert (
        H3CharacterReference.IS_CHANGED(profile["id"], selected_scene["id"]) == before
    )

    scenes.update_scene(selected_scene["id"], name="Renamed Beach")
    assert (
        H3CharacterReference.IS_CHANGED(profile["id"], selected_scene["id"]) == before
    )
    scenes.update_scene(selected_scene["id"], definition="a stormy shoreline")
    changed = H3CharacterReference.IS_CHANGED(profile["id"], selected_scene["id"])
    assert changed != before
    assert H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE) != changed


def test_node_own_prompt_inputs_participate_in_fingerprint(store, monkeypatch):
    profile, _, _ = complete_profile(store)
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    before = H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, "walks")
    assert H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, "runs") != before
