from __future__ import annotations

import json
from pathlib import Path

import pytest

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder.nodes import (
    NO_PROP,
    NO_SCENE,
    H3CharacterReference,
    H3DualCharacterReference,
)
from h3_character_ref_builder.prompt_builder import (
    build_dual_character_context_data,
    parse_character_context,
    serialize_character_context,
)
from h3_character_ref_builder.prop_store import PropStore
from h3_character_ref_builder.scene_store import SceneStore

from .test_character_store import complete_profile, image_bytes


def _selected_records(profile):
    images = {record["id"]: record for record in profile["images"]}
    audio = {record["id"]: record for record in profile["audio"]}
    return (
        images[profile["defaults"]["image_1"]],
        images[profile["defaults"]["image_2"]],
        audio[profile["defaults"]["audio"]],
    )


def _dual_context(character_1, character_2, *, scene=None, prop=None):
    image_1_1, image_1_2, audio_1 = _selected_records(character_1)
    image_2_1, image_2_2, audio_2 = _selected_records(character_2)
    return build_dual_character_context_data(
        character_1=character_1,
        character_1_image_1=image_1_1,
        character_1_image_2=image_1_2,
        character_1_audio=audio_1,
        character_2=character_2,
        character_2_image_1=image_2_1,
        character_2_image_2=image_2_2,
        character_2_audio=audio_2,
        scene=scene,
        prop=prop,
    )


def _stores(store, tmp_path, monkeypatch):
    scenes = SceneStore(tmp_path / "managed-scenes")
    props = PropStore(tmp_path / "managed-props")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "get_default_prop_store", lambda: props)
    monkeypatch.setattr(node_module, "load_image", lambda path: f"image:{path.name}")
    monkeypatch.setattr(node_module, "load_audio", lambda path: f"audio:{path.name}")
    return scenes, props


def test_dual_node_registration_inputs_and_exact_output_contract(
    store, tmp_path, monkeypatch
):
    first = store.create_profile("Ashley")
    second = store.create_profile("Vespera")
    _stores(store, tmp_path, monkeypatch)

    inputs = H3DualCharacterReference.INPUT_TYPES()
    profile_ids = [first["id"], second["id"]]
    assert list(inputs["required"]) == ["character_1", "character_2"]
    assert inputs["required"]["character_1"][0] == profile_ids
    assert inputs["required"]["character_2"][0] == profile_ids
    assert inputs["required"]["character_1"][1]["label"] == "Character 1"
    assert inputs["required"]["character_2"][1]["label"] == "Character 2"
    assert set(inputs["optional"]) == {"scene", "prop"}
    assert inputs["optional"]["scene"][0] == [NO_SCENE]
    assert inputs["optional"]["prop"][0] == [NO_PROP]

    assert H3DualCharacterReference.RETURN_TYPES == (
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
    assert H3DualCharacterReference.RETURN_NAMES == (
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
    assert H3DualCharacterReference.CATEGORY == "H3/Reference"
    assert H3CharacterReference.RETURN_NAMES == (
        "character_image_1",
        "character_image_2",
        "audio",
        "character_context",
        "scene_image",
        "prop_image",
    )

    registration = (Path(__file__).parents[1] / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert '"H3CharacterReference": H3CharacterReference' in registration
    assert '"H3DualCharacterReference": H3DualCharacterReference' in registration
    assert '"H3DualCharacterReference": "H3 Dual Character Reference"' in registration


def test_dual_node_loads_both_characters_audio_and_no_fake_optional_images(
    store, tmp_path, monkeypatch
):
    first, _, _ = complete_profile(store, "Ashley")
    second, _, _ = complete_profile(store, "Vespera")
    first = store.update_profile(first["id"], description="Ashley's blue eyes")
    first = store.update_media(
        first["id"], first["defaults"]["audio"], role="voice_identity"
    )
    second = store.update_profile(second["id"], description="Vespera's silver hair")
    second_audio_id = second["defaults"]["audio"]
    second = store.update_media(second["id"], second_audio_id, role="delivery_emotion")
    _stores(store, tmp_path, monkeypatch)

    output = H3DualCharacterReference().load_characters(first["id"], second["id"])
    context = json.loads(output[6])

    assert len(output) == 9
    for index, media_id in (
        (0, first["defaults"]["image_1"]),
        (1, first["defaults"]["image_2"]),
        (2, first["defaults"]["audio"]),
        (3, second["defaults"]["image_1"]),
        (4, second["defaults"]["image_2"]),
        (5, second["defaults"]["audio"]),
    ):
        assert media_id in output[index]
    assert output[7] is None
    assert output[8] is None
    assert context["schema_version"] == 2
    assert context["subject_roles"] == {
        "<Subject 1>": {"type": "character", "name": "Ashley"},
        "<Subject 2>": {"type": "character", "name": "Vespera"},
    }

    definitions = context["subject_definitions"]
    subject_1, subject_2 = definitions.split("<Subject 2>", 1)
    assert "defined jointly by <Picture 1> and <Picture 2>" in subject_1
    assert "Ashley's blue eyes" in subject_1
    assert "Vespera's silver hair" not in subject_1
    assert "defined jointly by <Picture 3> and <Picture 4>" in subject_2
    assert "Vespera's silver hair" in subject_2
    assert "Ashley's blue eyes" not in subject_2
    assert "<Audio 1> is the voice-timbre" in definitions
    assert "for <Subject 1>" in definitions
    assert "<Audio 2> provides vocal tone" in definitions
    assert "for <Subject 2>" in definitions
    assert "<Subject 3>" not in json.dumps(context)

    summary = context["summary"]
    assert "featuring <Subject 1> and <Subject 2>," in summary
    assert "<Audio 1> only as the vocal reference for <Subject 1>" in summary
    assert "<Audio 2> only as the vocal reference for <Subject 2>" in summary
    retention = context["retention_analysis"]
    assert "<Subject 1>" in retention and "<Picture 1> and <Picture 2>" in retention
    assert "<Subject 2>" in retention and "<Picture 3> and <Picture 4>" in retention
    assert "<Audio 1>: reference -" in retention
    assert "<Audio 2>: reference -" in retention

    same_profile = H3DualCharacterReference().load_characters(first["id"], first["id"])
    assert len(same_profile) == 9


def test_dual_visual_scene_and_prop_use_picture_5_and_picture_6(
    store, tmp_path, monkeypatch
):
    first, _, _ = complete_profile(store, "Ashley")
    second, _, _ = complete_profile(store, "Vespera")
    scenes, props = _stores(store, tmp_path, monkeypatch)
    scene = scenes.create_scene("Beanbag", "a warm lounge", "quiet ventilation")
    scene = scenes.set_reference_image(scene["id"], image_bytes(), "room.png")
    prop = props.create_prop("dildo", "black silicone")
    prop = props.set_reference_image(prop["id"], image_bytes(), "prop.png")

    output = H3DualCharacterReference().load_characters(
        first["id"], second["id"], scene["id"], prop["id"]
    )
    context = json.loads(output[6])
    assert scene["reference_image"]["id"] in output[7]
    assert prop["reference_image"]["id"] in output[8]
    assert context["subject_roles"] == {
        "<Subject 1>": {"type": "character", "name": "Ashley"},
        "<Subject 2>": {"type": "character", "name": "Vespera"},
        "<Subject 3>": {"type": "environment", "name": "Beanbag"},
    }
    definitions = context["subject_definitions"]
    assert "<Subject 3> is the environment defined by <Picture 5>" in definitions
    assert "<Picture 6> provides the visual reference for the dildo" in definitions
    assert "Additional prop information: black silicone" in definitions
    assert "<Subject 4>" not in definitions
    assert "dildo" not in json.dumps(context["subject_roles"])
    assert "in <Subject 3>" in context["summary"]
    retention = context["retention_analysis"]
    assert "<Subject 3>" in retention and "<Picture 5>" in retention
    assert "<Picture 6>: fully_preserved" in retention


def test_dual_prop_uses_picture_5_without_real_scene_image(store):
    first, _, _ = complete_profile(store, "Ashley")
    second, _, _ = complete_profile(store, "Vespera")
    prop = {"name": "penis", "description": "thick shaft"}
    text_scene = {
        "name": "Beanbag",
        "definition": "a warm lounge",
        "default_soundscape": "",
        "reference_image": None,
    }

    with_scene = _dual_context(first, second, scene=text_scene, prop=prop)
    assert "<Subject 3> is a warm lounge" in with_scene["subject_definitions"]
    assert (
        "<Picture 5> provides the visual reference for the penis"
        in with_scene["subject_definitions"]
    )
    assert "<Picture 6>" not in json.dumps(with_scene)

    without_scene = _dual_context(first, second, prop=prop)
    assert set(without_scene["subject_roles"]) == {"<Subject 1>", "<Subject 2>"}
    assert "<Subject 3>" not in json.dumps(without_scene)
    assert (
        "<Picture 5> provides the visual reference for the penis"
        in without_scene["subject_definitions"]
    )
    assert "<Picture 5>: fully_preserved" in without_scene["retention_analysis"]


@pytest.mark.parametrize(
    ("role", "wording"),
    [
        ("voice_identity", "<Audio 2> is the voice-timbre"),
        ("delivery_emotion", "<Audio 2> provides vocal tone"),
        ("general", "<Audio 2> provides general vocal characteristics"),
    ],
)
def test_dual_audio_2_role_wording_targets_subject_2(store, role, wording):
    first, _, _ = complete_profile(store, "Ashley")
    second, _, _ = complete_profile(store, "Vespera")
    second = store.update_media(second["id"], second["defaults"]["audio"], role=role)
    context = _dual_context(first, second)
    assert wording in context["subject_definitions"]
    audio_2_definition = context["subject_definitions"].split("<Audio 2>", 1)[1]
    assert "<Subject 2>" in audio_2_definition
    assert "<Audio 2>: reference -" in context["retention_analysis"]


def test_dual_fingerprint_tracks_selected_inputs_and_isolates_unrelated_data(
    store, tmp_path, monkeypatch
):
    first, _, _ = complete_profile(store, "Ashley")
    second, _, _ = complete_profile(store, "Vespera")
    unrelated, _, _ = complete_profile(store, "Rachel")
    scenes, props = _stores(store, tmp_path, monkeypatch)
    scene = scenes.create_scene("Beanbag", "warm lounge")
    other_scene = scenes.create_scene("Kitchen", "steel counters")
    prop = props.create_prop("dildo")
    prop = props.set_reference_image(prop["id"], image_bytes(), "prop.png")
    other_prop = props.create_prop("wand")
    other_prop = props.set_reference_image(other_prop["id"], image_bytes(), "wand.png")

    args = (first["id"], second["id"], scene["id"], prop["id"])
    baseline = H3DualCharacterReference.IS_CHANGED(*args)
    assert H3DualCharacterReference.IS_CHANGED(*args) == baseline
    assert (
        H3DualCharacterReference.IS_CHANGED(
            first["id"], second["id"], other_scene["id"], prop["id"]
        )
        != baseline
    )
    assert (
        H3DualCharacterReference.IS_CHANGED(
            first["id"], second["id"], scene["id"], other_prop["id"]
        )
        != baseline
    )

    store.update_profile(unrelated["id"], description="unrelated change")
    scenes.update_scene(other_scene["id"], definition="unrelated scene change")
    props.update_prop(other_prop["id"], description="unrelated prop change")
    assert H3DualCharacterReference.IS_CHANGED(*args) == baseline

    store.update_profile(first["id"], description="first changed")
    first_changed = H3DualCharacterReference.IS_CHANGED(*args)
    assert first_changed != baseline
    store.update_media(
        second["id"], second["defaults"]["audio"], role="delivery_emotion"
    )
    second_changed = H3DualCharacterReference.IS_CHANGED(*args)
    assert second_changed != first_changed

    scenes.set_reference_image(scene["id"], image_bytes(), "scene.png")
    scene_changed = H3DualCharacterReference.IS_CHANGED(*args)
    assert scene_changed != second_changed
    props.update_prop(prop["id"], name="Black Dildo", description="silicone")
    prop_changed = H3DualCharacterReference.IS_CHANGED(*args)
    assert prop_changed != scene_changed
    props.set_reference_image(
        prop["id"], image_bytes("PNG", (190, 20, 30)), "replacement.png"
    )
    assert H3DualCharacterReference.IS_CHANGED(*args) != prop_changed


@pytest.mark.parametrize(
    "subject_roles",
    [
        {},
        {"Subject 1": {"type": "character", "name": "Ashley"}},
        {"<Subject 2>": {"type": "character", "name": "Ashley"}},
        {"<Subject 1>": {"type": "prop", "name": "wand"}},
        {"<Subject 1>": {"type": "character"}},
        {"<Subject 1>": {"type": "character", "name": 4}},
    ],
)
def test_schema_v2_rejects_malformed_subject_roles(subject_roles):
    context = {
        "schema_version": 2,
        "subject_roles": subject_roles,
        "subject_definitions": "<Subject 1> definition",
        "summary": "summary",
        "retention_analysis": "retention",
        "scene_definition": "",
        "default_soundscape": "",
    }
    with pytest.raises((TypeError, ValueError), match="subject_roles|subject role"):
        parse_character_context(serialize_character_context(context))


def test_frontend_supports_single_and_dual_nodes_with_one_shared_catalog_fetch():
    source = (Path(__file__).parents[1] / "web" / "character_reference.js").read_text(
        encoding="utf-8"
    )
    assert 'const SINGLE_NODE_TYPE = "H3CharacterReference"' in source
    assert 'const DUAL_NODE_TYPE = "H3DualCharacterReference"' in source
    assert 'character_1: "Character 1"' in source
    assert 'character_2: "Character 2"' in source
    assert 'character: "Character"' in source
    assert 'applyOptions(node, "character_1", catalogs.characters' in source
    assert 'applyOptions(node, "character_2", catalogs.characters' in source
    assert 'applyOptions(node, "character", catalogs.characters' in source
    assert source.count("async function fetchCatalogs()") == 1
    assert 'window.addEventListener("focus", refreshAllNodes)' in source
