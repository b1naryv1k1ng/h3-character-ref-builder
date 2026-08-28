from __future__ import annotations

import asyncio
import io
import json
import uuid

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder.media import InvalidMedia
from h3_character_ref_builder.nodes import H3CharacterReference
from h3_character_ref_builder.prompt_builder import build_character_context_data
from h3_character_ref_builder.scene_store import (
    SCENE_SCHEMA_VERSION,
    SceneCorrupt,
    SceneImageNotFound,
    SceneStore,
)

from .test_character_store import complete_profile, image_bytes
from .test_v3_routes import install_app


def _record(role: str) -> dict[str, str]:
    return {"id": str(uuid.uuid4()), "file": "unused", "label": "", "role": role}


def test_v2_scene_migration_adds_null_reference_image_idempotently(tmp_path):
    store = SceneStore(tmp_path / "managed")
    scene_id = str(uuid.uuid4())
    directory = store.scenes_root / scene_id
    directory.mkdir()
    path = directory / "scene.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "id": scene_id,
                "name": "Legacy Beach",
                "definition": "warm sand",
                "default_soundscape": "gentle surf",
            }
        ),
        encoding="utf-8",
    )

    migrated = store.get_scene(scene_id)
    first_bytes = path.read_bytes()

    assert migrated == {
        "schema_version": SCENE_SCHEMA_VERSION,
        "id": scene_id,
        "name": "Legacy Beach",
        "definition": "warm sand",
        "default_soundscape": "gentle surf",
        "reference_image": None,
    }
    assert store.get_scene(scene_id) == migrated
    assert path.read_bytes() == first_bytes
    assert not list(directory.glob(".scene-*.tmp"))


def test_text_only_scene_and_reference_image_lifecycle_update_fingerprint(tmp_path):
    store = SceneStore(tmp_path / "managed")
    scene = store.create_scene("Beach", "warm sand", "gentle surf")
    scene_id = scene["id"]
    text_only_fingerprint = store.prompt_fingerprint(scene_id)

    assert scene["schema_version"] == SCENE_SCHEMA_VERSION
    assert scene["reference_image"] is None

    with_image = store.set_reference_image(
        scene_id,
        image_bytes("PNG", (10, 20, 30)),
        "../../outside.png",
        content_type="image/png",
    )
    first_record = with_image["reference_image"]
    first_path = store.reference_image_path(scene_id)
    added_fingerprint = store.prompt_fingerprint(scene_id)

    assert first_record is not None
    assert str(uuid.UUID(first_record["id"])) == first_record["id"]
    assert first_record["file"] == f"images/{first_record['id']}.png"
    assert first_path.parent == store.scenes_root / scene_id / "images"
    assert first_path.read_bytes() == image_bytes("PNG", (10, 20, 30)).getvalue()
    assert added_fingerprint != text_only_fingerprint

    replaced = store.set_reference_image(
        scene_id,
        image_bytes("JPEG", (200, 30, 40)),
        "replacement.jpg",
    )
    replaced_path = store.reference_image_path(scene_id)
    replaced_fingerprint = store.prompt_fingerprint(scene_id)

    assert replaced["reference_image"]["id"] == first_record["id"]
    assert replaced_path.suffix == ".jpg"
    assert not first_path.exists()
    assert replaced_fingerprint != added_fingerprint

    removed = store.delete_reference_image(scene_id)
    removed_fingerprint = store.prompt_fingerprint(scene_id)

    assert removed["reference_image"] is None
    assert not replaced_path.exists()
    assert removed_fingerprint == text_only_fingerprint
    with pytest.raises(SceneImageNotFound):
        store.reference_image_path(scene_id)


def test_scene_delete_cleans_managed_reference_directory(tmp_path):
    store = SceneStore(tmp_path / "managed")
    scene = store.create_scene("Room")
    store.set_reference_image(scene["id"], image_bytes(), "room.png")
    directory = store.scenes_root / scene["id"]
    assert store.reference_image_path(scene["id"]).is_file()

    store.delete_scene(scene["id"])

    assert not directory.exists()


def test_invalid_image_and_unsafe_stored_paths_are_rejected(tmp_path):
    store = SceneStore(tmp_path / "managed")
    scene = store.create_scene("Room")
    with pytest.raises(InvalidMedia, match="not a valid image"):
        store.set_reference_image(scene["id"], io.BytesIO(b"not an image"), "bad.png")
    assert store.get_scene(scene["id"])["reference_image"] is None

    path = store.scenes_root / scene["id"] / "scene.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reference_image"] = {"id": str(uuid.uuid4()), "file": "../../escape.png"}
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SceneCorrupt, match="unsafe image filename"):
        store.get_scene(scene["id"])


def test_scene_reference_image_routes_upload_serve_replace_remove(
    tmp_path, monkeypatch
):
    app = install_app(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            created_response = await client.post(
                "/api/h3-character-ref-builder/scenes",
                json={"name": "Atrium", "definition": "glass and stone"},
            )
            created = (await created_response.json())["data"]
            scene_id = created["id"]
            assert created["reference_image"] is None

            upload = FormData()
            upload.add_field(
                "file",
                image_bytes("PNG", (1, 2, 3)).getvalue(),
                filename="../../atrium.png",
                content_type="image/png",
            )
            upload_response = await client.post(
                f"/api/h3-character-ref-builder/scenes/{scene_id}/reference-image",
                data=upload,
            )
            uploaded = (await upload_response.json())["data"]
            reference = uploaded["reference_image"]
            assert upload_response.status == 200
            assert reference["url"].endswith(f"/scenes/{scene_id}/reference-image")
            assert ".." not in reference["file"]

            served = await client.get(reference["url"])
            assert served.status == 200
            assert served.headers["Cache-Control"] == "no-store"
            assert await served.read() == image_bytes("PNG", (1, 2, 3)).getvalue()

            replacement = FormData()
            replacement.add_field(
                "file",
                image_bytes("PNG", (4, 5, 6)).getvalue(),
                filename="replacement.png",
                content_type="image/png",
            )
            replacement_response = await client.post(
                f"/api/h3-character-ref-builder/scenes/{scene_id}/reference-image",
                data=replacement,
            )
            replaced = (await replacement_response.json())["data"]
            assert replaced["reference_image"]["id"] == reference["id"]

            invalid = FormData()
            invalid.add_field(
                "file", b"not an image", filename="bad.png", content_type="image/png"
            )
            invalid_response = await client.post(
                f"/api/h3-character-ref-builder/scenes/{scene_id}/reference-image",
                data=invalid,
            )
            assert invalid_response.status == 400

            removed_response = await client.delete(
                f"/api/h3-character-ref-builder/scenes/{scene_id}/reference-image"
            )
            assert (await removed_response.json())["data"]["reference_image"] is None
            missing_response = await client.get(
                f"/api/h3-character-ref-builder/scenes/{scene_id}/reference-image"
            )
            assert missing_response.status == 404

            traversal_response = await client.get(
                "/api/h3-character-ref-builder/scenes/..%2F..%2Fsecret/reference-image"
            )
            assert traversal_response.status in {400, 404}

    asyncio.run(scenario())


def test_character_reference_returns_real_scene_image_in_compatible_slot(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    scene = scenes.create_scene("Beach", "warm sand", "gentle surf")
    scene = scenes.set_reference_image(scene["id"], image_bytes(), "beach.png")
    image_id = scene["reference_image"]["id"]
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "load_image", lambda path: f"loaded:{path.name}")
    monkeypatch.setattr(node_module, "load_audio", lambda path: f"loaded:{path.name}")

    output = H3CharacterReference().load_character(profile["id"], scene["id"])
    context = json.loads(output[3])

    assert len(output) == 5
    assert image_id in output[4]
    assert "<Picture 3>" in context["subject_definitions"]
    assert "<Picture 3>" in context["retention_analysis"]
    assert context["scene_definition"] == "warm sand"
    assert "reference_image" not in context


def test_character_reference_uses_none_for_absent_scene_image(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    scene = scenes.create_scene("Text Room", "white walls")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "load_image", lambda path: path.name)
    monkeypatch.setattr(node_module, "load_audio", lambda path: path.name)

    output = H3CharacterReference().load_character(profile["id"], scene["id"])
    context = json.loads(output[3])

    assert output[4] is None
    assert "<Picture 3>" not in context["subject_definitions"]
    assert "<Picture 3>" not in context["retention_analysis"]
    assert "<Subject 2> is white walls" in context["subject_definitions"]


def test_visual_scene_prompt_uses_picture_3_and_keeps_text_as_supplement():
    context = build_character_context_data(
        character={"description": ""},
        image_1=_record("face_identity"),
        image_2=_record("full_body_identity"),
        audio=_record("voice_identity"),
        scene={
            "definition": "a vaulted station concourse",
            "default_soundscape": "distant trains",
            "reference_image": {"id": str(uuid.uuid4()), "file": "images/unused.png"},
        },
    )

    assert (
        "<Subject 2> is the environment defined by <Picture 3>"
        in context["subject_definitions"]
    )
    assert (
        "spatial layout, architecture, major objects, materials, lighting"
        in context["subject_definitions"]
    )
    assert (
        "The saved scene definition supplements the visual reference: "
        "a vaulted station concourse"
    ) in context["subject_definitions"]
    assert (
        "preserve the environment defined by <Picture 3>"
        in context["retention_analysis"]
    )
    assert context["scene_definition"] == "a vaulted station concourse"
    assert set(context) == {
        "schema_version",
        "subject_definitions",
        "summary",
        "retention_analysis",
        "scene_definition",
        "default_soundscape",
    }


def test_scene_manager_ui_has_contained_preview_and_dedicated_operations():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "manager" / "index.html").read_text(encoding="utf-8")
    css = (root / "manager" / "character-manager.css").read_text(encoding="utf-8")
    javascript = (root / "manager" / "character-manager.js").read_text(encoding="utf-8")

    assert 'id="scene-reference-preview"' in html
    assert 'id="scene-upload-image"' in html
    assert 'id="scene-remove-image"' in html
    assert "height:190px" in css
    assert "object-fit:contain" in css
    assert "/reference-image`" in javascript
    assert 'method: "POST"' in javascript
    assert 'method: "DELETE"' in javascript
