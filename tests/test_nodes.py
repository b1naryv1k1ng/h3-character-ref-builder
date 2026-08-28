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

    image_1, image_2, selected_audio, context_json, scene_image, prop_image = (
        H3CharacterReference().load_character(profile["id"])
    )
    context = json.loads(context_json)

    assert first["id"] in image_1
    assert third["id"] in image_2
    assert unused["id"] not in {image_1, image_2}
    assert audio["id"] in selected_audio
    assert context["schema_version"] == 1
    assert context["subject_definitions"].startswith("<Subject 1>")
    assert context["summary"].startswith("[reference generation + audio reference]")
    assert "fully_preserved" in context["retention_analysis"]
    assert context["scene_definition"] == ""
    assert context["default_soundscape"] == ""
    assert "file" not in context_json
    assert "images/" not in context_json
    assert scene_image is None
    assert prop_image is None


def test_node_output_contract_preserves_media_positions_and_returns_context():
    assert H3CharacterReference.RETURN_TYPES == (
        "IMAGE",
        "IMAGE",
        "AUDIO",
        "STRING",
        "IMAGE",
        "IMAGE",
    )
    assert H3CharacterReference.RETURN_NAMES == (
        "character_image_1",
        "character_image_2",
        "audio",
        "character_context",
        "scene_image",
        "prop_image",
    )


def test_node_scene_context_and_fingerprint_isolate_other_scene(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    selected_scene = scenes.create_scene(
        "Beach", "warm sand and gentle surf", "quiet waves"
    )
    other_scene = scenes.create_scene("Bedroom", "white walls")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "load_image", lambda path: path.name)
    monkeypatch.setattr(node_module, "load_audio", lambda path: path.name)

    before = H3CharacterReference.IS_CHANGED(profile["id"], selected_scene["id"])
    output = H3CharacterReference().load_character(
        profile["id"], selected_scene["id"], "legacy action is ignored"
    )
    context = json.loads(output[3])
    assert "<Subject 2> is warm sand and gentle surf" in context["subject_definitions"]
    assert context["scene_definition"] == "warm sand and gentle surf"
    assert context["default_soundscape"] == "quiet waves"

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


def test_legacy_prompt_values_are_accepted_but_do_not_affect_context_fingerprint(
    store, monkeypatch
):
    profile, _, _ = complete_profile(store)
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    before = H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, "walks")
    assert H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, "runs") == before
    assert (
        H3CharacterReference.IS_CHANGED(
            profile["id"], NO_SCENE, detailed_description="legacy"
        )
        == before
    )


def test_context_without_scene_omits_subject_2_and_scene_fields(store, monkeypatch):
    profile, _, _ = complete_profile(store)
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "load_image", lambda path: path.name)
    monkeypatch.setattr(node_module, "load_audio", lambda path: path.name)

    context = json.loads(H3CharacterReference().load_character(profile["id"])[3])

    assert "<Subject 2>" not in context["subject_definitions"]
    assert "<Subject 2>" not in context["summary"]
    assert "<Subject 2>" not in context["retention_analysis"]
    assert context["scene_definition"] == ""
    assert context["default_soundscape"] == ""
