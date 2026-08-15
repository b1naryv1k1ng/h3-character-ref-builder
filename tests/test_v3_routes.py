from __future__ import annotations

import asyncio
import sys
import types

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from h3_character_ref_builder import routes as route_module
from h3_character_ref_builder.character_store import CharacterStore
from h3_character_ref_builder.scene_store import SceneStore

from .test_routes import png_bytes


def install_app(tmp_path, monkeypatch):
    characters = CharacterStore(tmp_path / "managed")
    scenes = SceneStore(tmp_path / "managed")
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
    monkeypatch.setattr(route_module, "_ROUTES_REGISTERED", False)
    route_module.register_routes()
    app = web.Application()
    app.add_routes(table)
    return app


def test_role_and_scene_api_end_to_end(tmp_path, monkeypatch):
    app = install_app(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            character_response = await client.post(
                "/api/h3-character-ref-builder/characters", json={"name": "Ari"}
            )
            character_id = (await character_response.json())["data"]["id"]
            form = FormData()
            form.add_field("type", "image")
            form.add_field("label", "Front")
            form.add_field("role", "face_identity")
            form.add_field(
                "file", png_bytes(), filename="front.png", content_type="image/png"
            )
            media_response = await client.post(
                f"/api/h3-character-ref-builder/characters/{character_id}/media",
                data=form,
            )
            media = (await media_response.json())["data"]["images"][0]
            assert media_response.status == 201
            assert media["role"] == "face_identity"

            role_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{media['id']}",
                json={"role": "expression"},
            )
            role_profile = (await role_response.json())["data"]
            assert role_response.status == 200
            assert role_profile["images"][0]["id"] == media["id"]
            assert role_profile["images"][0]["role"] == "expression"

            invalid_role = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{media['id']}",
                json={"role": "voice_identity"},
            )
            assert invalid_role.status == 400

            created_response = await client.post(
                "/api/h3-character-ref-builder/scenes",
                json={
                    "name": "Tropical Beach",
                    "definition": "<Subject 2> is warm sand and calm water",
                },
            )
            created = (await created_response.json())["data"]
            assert created_response.status == 201
            assert created["definition"] == "warm sand and calm water"

            list_response = await client.get("/api/h3-character-ref-builder/scenes")
            assert (await list_response.json())["data"] == [
                {"id": created["id"], "name": "Tropical Beach"}
            ]
            detail_response = await client.get(
                f"/api/h3-character-ref-builder/scenes/{created['id']}"
            )
            assert (await detail_response.json())["data"]["definition"] == created[
                "definition"
            ]

            updated_response = await client.put(
                f"/api/h3-character-ref-builder/scenes/{created['id']}",
                json={"name": "Beach", "definition": "late afternoon shoreline"},
            )
            updated = (await updated_response.json())["data"]
            assert updated["id"] == created["id"]

            duplicate = await client.post(
                "/api/h3-character-ref-builder/scenes",
                json={"name": " BEACH ", "definition": "duplicate"},
            )
            assert duplicate.status == 409

            traversal = await client.get(
                "/api/h3-character-ref-builder/scenes/..%2F..%2Fsecret"
            )
            assert traversal.status in {400, 404}
            deleted = await client.delete(
                f"/api/h3-character-ref-builder/scenes/{created['id']}"
            )
            assert deleted.status == 200
            missing = await client.get(
                f"/api/h3-character-ref-builder/scenes/{created['id']}"
            )
            assert missing.status == 404

    asyncio.run(scenario())
