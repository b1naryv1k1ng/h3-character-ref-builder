from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder.nodes import H3CharacterReference, H3PromptEnhancer
from h3_character_ref_builder.prompt_builder import DEFAULT_SOUNDSCAPE
from h3_character_ref_builder.roles import IMAGE_ROLE_METADATA
from h3_character_ref_builder.scene_store import SCENE_SCHEMA_VERSION, SceneStore

from .test_character_store import complete_profile
from .test_prompt_builder import build, section
from .test_v3_routes import install_app


def test_full_body_identity_and_wardrobe_are_semantically_distinct():
    full_body = IMAGE_ROLE_METADATA["full_body_identity"]["definition"]
    wardrobe = IMAGE_ROLE_METADATA["wardrobe"]["definition"]

    assert "body proportions" in full_body
    assert "build" in full_body
    assert "silhouette" in full_body
    assert "wardrobe" not in full_body
    assert "clothing" not in full_body
    assert "wardrobe" in wardrobe
    assert "clothing" in wardrobe
    assert full_body != wardrobe

    definitions = section(build(), "subject_definitions")
    picture_2 = definitions.split("<Picture 2> contributes ", 1)[1].split(".", 1)[0]
    assert "body proportions, build, silhouette" in picture_2
    assert "wardrobe" not in picture_2
    assert "source backgrounds, lighting, camera framing, pose, expression" in definitions
    assert "or wardrobe unless explicitly requested" in definitions


def test_scene_v1_migration_is_atomic_idempotent_and_preserves_definition(tmp_path):
    store = SceneStore(tmp_path / "managed")
    scene_id = str(uuid.uuid4())
    scene_dir = store.scenes_root / scene_id
    scene_dir.mkdir()
    scene_path = scene_dir / "scene.json"
    original_definition = "an intact legacy scene definition"
    scene_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": scene_id,
                "name": "Legacy Room",
                "definition": original_definition,
            }
        ),
        encoding="utf-8",
    )

    migrated = store.get_scene(scene_id)
    first_bytes = scene_path.read_bytes()
    assert migrated == {
        "schema_version": SCENE_SCHEMA_VERSION,
        "id": scene_id,
        "name": "Legacy Room",
        "definition": original_definition,
        "default_soundscape": "",
    }
    assert not list(scene_dir.glob(".scene-*.tmp"))

    assert store.get_scene(scene_id) == migrated
    assert scene_path.read_bytes() == first_bytes


def test_scene_soundscape_crud_rename_and_uuid_stability(tmp_path):
    store = SceneStore(tmp_path / "managed")
    created = store.create_scene(
        "Beach",
        "warm sand and calm water",
        "gentle surf and light ocean wind",
    )
    scene_id = created["id"]
    assert created["schema_version"] == SCENE_SCHEMA_VERSION
    assert created["default_soundscape"] == "gentle surf and light ocean wind"
    assert store.get_scene(scene_id)["default_soundscape"] == created["default_soundscape"]

    updated = store.update_scene(
        scene_id, default_soundscape="distant seabirds and subtle water movement"
    )
    assert updated["id"] == scene_id
    assert updated["default_soundscape"] == (
        "distant seabirds and subtle water movement"
    )

    renamed = store.update_scene(scene_id, name="Tropical Beach")
    assert renamed["id"] == scene_id
    assert renamed["definition"] == created["definition"]
    assert renamed["default_soundscape"] == updated["default_soundscape"]


def test_scene_api_reads_and_writes_default_soundscape(tmp_path, monkeypatch):
    app = install_app(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            created_response = await client.post(
                "/api/h3-character-ref-builder/scenes",
                json={
                    "name": "Beach",
                    "definition": "warm sand",
                    "default_soundscape": "gentle breaking waves",
                },
            )
            assert created_response.status == 201
            created = (await created_response.json())["data"]
            assert created["default_soundscape"] == "gentle breaking waves"

            detail_response = await client.get(
                f"/api/h3-character-ref-builder/scenes/{created['id']}"
            )
            detail = (await detail_response.json())["data"]
            assert detail["default_soundscape"] == created["default_soundscape"]

            updated_response = await client.put(
                f"/api/h3-character-ref-builder/scenes/{created['id']}",
                json={"default_soundscape": "ocean wind and distant seabirds"},
            )
            updated = (await updated_response.json())["data"]
            assert updated["id"] == created["id"]
            assert updated["default_soundscape"] == "ocean wind and distant seabirds"

    asyncio.run(scenario())


def test_soundscape_combines_scene_default_and_additional_without_rewriting():
    scene_default = "Natural coastal ambience; waves break gently."
    additional = "Barefoot steps splash in wet sand!"
    prompt = build(
        scene={"definition": "a beach", "default_soundscape": scene_default},
        overall_soundscape=additional,
    )
    assert section(prompt, "overall_soundscape") == (
        f"{scene_default}\n\n"
        f"Additional action-specific sounds: {additional}"
    )


def test_soundscape_uses_scene_default_only():
    scene_default = "Quiet room tone with faint HVAC airflow."
    prompt = build(
        scene={"definition": "a bedroom", "default_soundscape": scene_default},
        overall_soundscape="",
    )
    assert section(prompt, "overall_soundscape") == scene_default


def test_soundscape_uses_additional_only_with_or_without_scene():
    additional = "Fabric rustles as she sits; the bed creaks slightly."
    with_scene = build(
        scene={"definition": "a bedroom", "default_soundscape": ""},
        overall_soundscape=additional,
    )
    without_scene = build(scene=None, overall_soundscape=additional)
    assert section(with_scene, "overall_soundscape") == additional
    assert section(without_scene, "overall_soundscape") == additional
    assert "<Subject 2>" not in without_scene


def test_soundscape_falls_back_when_both_sources_are_empty():
    with_scene = build(
        scene={"definition": "a studio", "default_soundscape": ""},
        overall_soundscape="",
    )
    assert section(with_scene, "overall_soundscape") == DEFAULT_SOUNDSCAPE
    no_scene = build(scene=None, overall_soundscape="")
    assert section(no_scene, "overall_soundscape") == DEFAULT_SOUNDSCAPE
    assert "<Subject 2>" not in no_scene


def test_selected_scene_soundscape_alone_participates_in_fingerprint(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    selected = scenes.create_scene("Beach", "warm sand", "gentle surf")
    unrelated = scenes.create_scene("Bedroom", "white walls", "quiet room tone")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)

    before = H3CharacterReference.IS_CHANGED(profile["id"], selected["id"])
    scenes.update_scene(unrelated["id"], default_soundscape="radiator ticking")
    assert H3CharacterReference.IS_CHANGED(profile["id"], selected["id"]) == before
    scenes.update_scene(selected["id"], default_soundscape="strong ocean wind")
    assert H3CharacterReference.IS_CHANGED(profile["id"], selected["id"]) != before


def test_character_node_removes_authoring_widgets_and_enhancer_owns_them(
    store, tmp_path, monkeypatch
):
    complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)

    assert set(H3CharacterReference.INPUT_TYPES()["optional"]) == {"scene"}
    required = H3PromptEnhancer.INPUT_TYPES()["required"]
    expected = {
        "action_idea": "Action Idea",
        "additional_notes": "Additional Notes",
        "non_diegetic_music": "Non-Diegetic Music",
    }
    for key, label in expected.items():
        input_type, options = required[key]
        assert input_type == "STRING"
        assert options["multiline"] is True
        assert options["label"] == label
    assert required["additional_notes"][1]["default"] == ""
    assert required["non_diegetic_music"][1]["default"] == "N/A"

    extension = (
        Path(__file__).parents[1] / "web" / "character_reference.js"
    ).read_text(encoding="utf-8")
    assert "widget.label = label" in extension
    assert "detailed_description:" not in extension
    assert "overall_soundscape:" not in extension
