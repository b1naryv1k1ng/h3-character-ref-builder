from __future__ import annotations

import asyncio
import io
import json
import sys
import types
import uuid

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from h3_character_ref_builder import nodes as node_module
from h3_character_ref_builder import prompt_enhancer as enhancer
from h3_character_ref_builder import routes as route_module
from h3_character_ref_builder.character_store import CharacterStore
from h3_character_ref_builder.media import InvalidMedia
from h3_character_ref_builder.nodes import NO_PROP, NO_SCENE, H3CharacterReference
from h3_character_ref_builder.prompt_builder import build_character_context_data
from h3_character_ref_builder.prop_store import (
    PROP_SCHEMA_VERSION,
    DuplicatePropName,
    PropCorrupt,
    PropStore,
)
from h3_character_ref_builder.scene_store import SceneStore

from .test_character_store import complete_profile, image_bytes


def _record(role: str) -> dict[str, str]:
    return {"id": str(uuid.uuid4()), "file": "unused", "label": "", "role": role}


def _context(*, scene=None, prop=None):
    return build_character_context_data(
        character={"description": ""},
        image_1=_record("face_identity"),
        image_2=_record("full_body_identity"),
        audio=_record("voice_identity"),
        scene=scene,
        prop=prop,
    )


def _install_app(tmp_path, monkeypatch):
    characters = CharacterStore(tmp_path / "managed")
    scenes = SceneStore(tmp_path / "managed")
    props = PropStore(tmp_path / "managed")
    table = web.RouteTableDef()
    fake_server = types.ModuleType("server")
    fake_server.PromptServer = type(
        "PromptServer",
        (),
        {"instance": type("Instance", (), {"routes": table})()},
    )
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setattr(route_module, "get_default_store", lambda: characters)
    monkeypatch.setattr(route_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(route_module, "get_default_prop_store", lambda: props)
    monkeypatch.setattr(route_module, "_ROUTES_REGISTERED", False)
    route_module.register_routes()
    app = web.Application()
    app.add_routes(table)
    return app, props


def test_prop_crud_unique_names_and_usable_catalog(tmp_path):
    store = PropStore(tmp_path / "managed")
    prop = store.create_prop("  dildo  ", "  black silicone  ")

    assert prop == {
        "schema_version": PROP_SCHEMA_VERSION,
        "id": prop["id"],
        "name": "dildo",
        "description": "black silicone",
        "reference_image": None,
    }
    assert store.list_props() == [{"id": prop["id"], "name": "dildo", "usable": False}]
    assert store.list_usable_props() == []
    with pytest.raises(DuplicatePropName):
        store.create_prop(" DILDO ")

    updated = store.update_prop(
        prop["id"], name="Silicone Dildo", description="large tapered shaft"
    )
    assert updated["id"] == prop["id"]
    assert updated["name"] == "Silicone Dildo"
    assert updated["description"] == "large tapered shaft"
    assert store.get_prop(prop["id"]) == updated


def test_prop_image_upload_replace_fingerprint_and_delete_cleanup(tmp_path):
    store = PropStore(tmp_path / "managed")
    prop = store.create_prop("penis", "thick shaft")
    before = store.fingerprint(prop["id"])

    uploaded = store.set_reference_image(
        prop["id"], image_bytes("PNG", (1, 2, 3)), "../../unsafe.png"
    )
    first = uploaded["reference_image"]
    first_path = store.reference_image_path(prop["id"])
    after_upload = store.fingerprint(prop["id"])

    assert first["file"] == f"images/{first['id']}.png"
    assert first_path.parent == store.props_root / prop["id"] / "images"
    assert before != after_upload
    assert store.list_props()[0]["usable"] is True
    assert store.list_usable_props() == [{"id": prop["id"], "name": "penis"}]

    replaced = store.set_reference_image(
        prop["id"], image_bytes("JPEG", (8, 9, 10)), "replacement.jpg"
    )
    replacement_path = store.reference_image_path(prop["id"])
    assert replaced["reference_image"]["id"] == first["id"]
    assert replacement_path.suffix == ".jpg"
    assert not first_path.exists()
    assert store.fingerprint(prop["id"]) != after_upload

    directory = store.props_root / prop["id"]
    store.delete_prop(prop["id"])
    assert not directory.exists()


def test_prop_invalid_image_and_unsafe_metadata_are_rejected(tmp_path):
    store = PropStore(tmp_path / "managed")
    prop = store.create_prop("wand")
    with pytest.raises(InvalidMedia, match="not a valid image"):
        store.set_reference_image(prop["id"], io.BytesIO(b"not an image"), "bad.png")
    assert store.get_prop(prop["id"])["reference_image"] is None

    path = store.props_root / prop["id"] / "prop.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reference_image"] = {"id": str(uuid.uuid4()), "file": "../../escape.png"}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PropCorrupt, match="unsafe image filename"):
        store.get_prop(prop["id"])


def test_prop_api_end_to_end(tmp_path, monkeypatch):
    app, _ = _install_app(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            created_response = await client.post(
                "/api/h3-character-ref-builder/props",
                json={"name": "Dildo", "description": "black silicone"},
            )
            assert created_response.status == 201
            created = (await created_response.json())["data"]
            assert created["usable"] is False

            duplicate = await client.post(
                "/api/h3-character-ref-builder/props", json={"name": " dildo "}
            )
            assert duplicate.status == 409

            updated_response = await client.patch(
                f"/api/h3-character-ref-builder/props/{created['id']}",
                json={"name": "Tapered Dildo", "description": "large and black"},
            )
            updated = (await updated_response.json())["data"]
            assert updated["name"] == "Tapered Dildo"
            assert updated["description"] == "large and black"

            upload = FormData()
            upload.add_field(
                "file",
                image_bytes().getvalue(),
                filename="../../prop.png",
                content_type="image/png",
            )
            upload_response = await client.post(
                f"/api/h3-character-ref-builder/props/{created['id']}/reference-image",
                data=upload,
            )
            uploaded = (await upload_response.json())["data"]
            assert uploaded["usable"] is True
            assert ".." not in uploaded["reference_image"]["file"]

            listed = (
                await (await client.get("/api/h3-character-ref-builder/props")).json()
            )["data"]
            assert listed == [
                {"id": created["id"], "name": "Tapered Dildo", "usable": True}
            ]
            detail = (
                await (
                    await client.get(
                        f"/api/h3-character-ref-builder/props/{created['id']}"
                    )
                ).json()
            )["data"]
            image_response = await client.get(detail["reference_image"]["url"])
            assert image_response.status == 200
            assert image_response.headers["Cache-Control"] == "no-store"
            assert await image_response.read() == image_bytes().getvalue()

            invalid = FormData()
            invalid.add_field(
                "file", b"bad", filename="bad.png", content_type="image/png"
            )
            invalid_response = await client.post(
                f"/api/h3-character-ref-builder/props/{created['id']}/reference-image",
                data=invalid,
            )
            assert invalid_response.status == 400

            traversal = await client.get(
                "/api/h3-character-ref-builder/props/..%2F..%2Fsecret/reference-image"
            )
            assert traversal.status in {400, 404}

            deleted = await client.delete(
                f"/api/h3-character-ref-builder/props/{created['id']}"
            )
            assert deleted.status == 200
            assert (
                await client.get(f"/api/h3-character-ref-builder/props/{created['id']}")
            ).status == 404

    asyncio.run(scenario())


def test_node_prop_input_output_none_and_real_image(store, tmp_path, monkeypatch):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    props = PropStore(tmp_path / "managed-props")
    incomplete = props.create_prop("Incomplete")
    prop = props.create_prop("Dildo", "tapered black silicone")
    prop = props.set_reference_image(prop["id"], image_bytes(), "prop.png")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "get_default_prop_store", lambda: props)
    monkeypatch.setattr(node_module, "load_image", lambda path: f"loaded:{path.name}")
    monkeypatch.setattr(node_module, "load_audio", lambda path: f"loaded:{path.name}")

    schema = H3CharacterReference.INPUT_TYPES()
    assert set(schema["optional"]) == {"scene", "prop"}
    assert schema["optional"]["prop"][0] == [NO_PROP, prop["id"]]
    assert incomplete["id"] not in schema["optional"]["prop"][0]

    without_prop = H3CharacterReference().load_character(profile["id"])
    with_prop = H3CharacterReference().load_character(
        profile["id"], NO_SCENE, prop["id"]
    )
    context = json.loads(with_prop[3])

    assert len(without_prop) == 6
    assert without_prop[4] is None
    assert without_prop[5] is None
    assert prop["reference_image"]["id"] in with_prop[5]
    assert (
        "<Picture 3> provides the visual reference for the Dildo"
        in context["subject_definitions"]
    )
    assert "tapered black silicone" in context["subject_definitions"]
    assert "file" not in json.dumps(context)


def test_prop_fingerprint_selected_metadata_image_and_unrelated_isolation(
    store, tmp_path, monkeypatch
):
    profile, _, _ = complete_profile(store)
    scenes = SceneStore(tmp_path / "managed-scenes")
    props = PropStore(tmp_path / "managed-props")
    selected = props.create_prop("Wand", "silver")
    selected = props.set_reference_image(selected["id"], image_bytes(), "wand.png")
    unrelated = props.create_prop("Cup", "blue")
    unrelated = props.set_reference_image(unrelated["id"], image_bytes(), "cup.png")
    monkeypatch.setattr(node_module, "get_default_store", lambda: store)
    monkeypatch.setattr(node_module, "get_default_scene_store", lambda: scenes)
    monkeypatch.setattr(node_module, "get_default_prop_store", lambda: props)

    no_prop = H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, NO_PROP)
    before = H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, selected["id"])
    assert no_prop == H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, NO_PROP)
    assert no_prop != before
    assert before != H3CharacterReference.IS_CHANGED(
        profile["id"], NO_SCENE, unrelated["id"]
    )

    props.update_prop(unrelated["id"], description="red")
    assert (
        H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, selected["id"])
        == before
    )

    original_context = _context(prop=props.get_prop(selected["id"]))
    props.update_prop(selected["id"], name="Magic Wand", description="gold")
    metadata_changed = H3CharacterReference.IS_CHANGED(
        profile["id"], NO_SCENE, selected["id"]
    )
    assert metadata_changed != before
    updated_context = _context(prop=props.get_prop(selected["id"]))
    assert updated_context != original_context
    assert "the Magic Wand" in updated_context["subject_definitions"]
    assert "Additional prop information: gold" in updated_context["subject_definitions"]
    assert (
        "Additional prop information: silver" in original_context["subject_definitions"]
    )

    props.set_reference_image(
        selected["id"], image_bytes("PNG", (200, 10, 10)), "wand.png"
    )
    assert (
        H3CharacterReference.IS_CHANGED(profile["id"], NO_SCENE, selected["id"])
        != metadata_changed
    )


@pytest.mark.parametrize(
    ("scene", "picture"),
    [
        (None, 3),
        (
            {
                "definition": "white room",
                "default_soundscape": "",
                "reference_image": None,
            },
            3,
        ),
        (
            {
                "definition": "white room",
                "default_soundscape": "",
                "reference_image": {"id": str(uuid.uuid4()), "file": "unused"},
            },
            4,
        ),
    ],
)
def test_prop_picture_numbering_and_deterministic_semantics(scene, picture):
    prop = {
        "name": "penis",
        "description": "thick shaft",
        "reference_image": {"id": str(uuid.uuid4()), "file": "unused"},
    }
    context = _context(scene=scene, prop=prop)
    definitions = context["subject_definitions"]
    retention = context["retention_analysis"]

    assert (
        f"<Picture {picture}> provides the visual reference for the penis"
        in definitions
    )
    assert f"from <Picture {picture}>" in definitions
    assert "Additional prop information: thick shaft" in definitions
    assert f"<Picture {picture}>: fully_preserved" in retention
    assert "<Subject 3>" not in definitions + retention
    assert "<Subject 1>'s penis" not in definitions + retention
    assert "<Subject 2>" not in definitions if scene is None else True
    if scene is not None:
        assert "<Subject 2>" in definitions
        assert "penis" not in definitions.split("<Subject 2>", 1)[1].split("\n\n", 1)[0]


def test_scene_picture_3_semantics_remain_without_prop():
    scene = {
        "definition": "a bright atrium",
        "default_soundscape": "",
        "reference_image": {"id": str(uuid.uuid4()), "file": "unused"},
    }
    context = _context(scene=scene, prop=None)
    assert (
        "<Subject 2> is the environment defined by <Picture 3>"
        in context["subject_definitions"]
    )
    assert "<Picture 4>" not in json.dumps(context)


def test_glm_request_contains_no_prop_image_or_prop_metadata():
    payload = enhancer._request_payload(
        config=enhancer.EnhancerConfig(
            api_key="unused",
            endpoint="https://example.invalid/chat/completions",
            model="test",
            timeout_seconds=10,
        ),
        system_prompt="system",
        scene_definition="a white room",
        duration_seconds=8,
        action_idea="She holds the dildo.",
        additional_notes="",
        structured=True,
    )
    user_context = json.loads(payload["messages"][1]["content"])
    assert user_context == {
        "duration_seconds": 8,
        "action_idea": "She holds the dildo.",
        "scene_definition": "a white room",
    }
    assert all("image" not in key and "prop" not in key for key in user_context)


def test_prop_manager_and_node_frontend_are_wired_without_multi_prop_support():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "manager" / "index.html").read_text(encoding="utf-8")
    css = (root / "manager" / "character-manager.css").read_text(encoding="utf-8")
    manager = (root / "manager" / "character-manager.js").read_text(encoding="utf-8")
    node_frontend = (root / "web" / "character_reference.js").read_text(
        encoding="utf-8"
    )

    assert 'id="props-tab"' in html
    assert 'id="prop-form"' in html
    assert 'id="prop-reference-preview"' in html
    assert "object-fit:contain" in css
    assert "/props/" in manager
    assert 'method: "POST"' in manager
    assert 'prop: "Prop Reference"' in node_frontend
    assert "props.data.filter((item) => item.usable)" in node_frontend
