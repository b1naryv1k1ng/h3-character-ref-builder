from __future__ import annotations

import asyncio
import io
import sys
import types
import wave

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from h3_character_ref_builder import routes as route_module
from h3_character_ref_builder.character_store import CharacterStore


def png_bytes(color=(30, 60, 90)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), color).save(output, format="PNG")
    return output.getvalue()


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 40)
    return output.getvalue()


def test_character_crud_media_and_narrow_serving_routes(tmp_path, monkeypatch):
    store = CharacterStore(tmp_path / "managed")
    table = web.RouteTableDef()
    fake_server = types.ModuleType("server")
    fake_server.PromptServer = type(
        "PromptServer",
        (),
        {"instance": type("Instance", (), {"routes": table})()},
    )
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setattr(route_module, "get_default_store", lambda: store)
    monkeypatch.setattr(route_module, "_ROUTES_REGISTERED", False)
    route_module.register_routes()

    app = web.Application()
    app.add_routes(table)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            created_response = await client.post(
                "/api/h3-character-ref-builder/characters",
                json={"name": "Ari", "description": "reference"},
            )
            assert created_response.status == 201
            created = (await created_response.json())["data"]
            character_id = created["id"]

            duplicate_response = await client.post(
                "/api/h3-character-ref-builder/characters", json={"name": "ARI"}
            )
            assert duplicate_response.status == 409

            uploads = {
                "reference_image_1": (png_bytes(), "one.png", "image/png"),
                "reference_image_2": (png_bytes((90, 60, 30)), "two.png", "image/png"),
                "reference_audio": (wav_bytes(), "voice.wav", "audio/wav"),
            }
            for slot, (contents, filename, content_type) in uploads.items():
                form = FormData()
                form.add_field("slot", slot)
                form.add_field(
                    "file", contents, filename=filename, content_type=content_type
                )
                response = await client.post(
                    f"/api/h3-character-ref-builder/characters/{character_id}/media",
                    data=form,
                )
                assert response.status == 200, await response.text()

            media_response = await client.get(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/reference_image_1"
            )
            assert media_response.status == 200
            assert await media_response.read() == uploads["reference_image_1"][0]

            traversal_response = await client.get(
                "/api/h3-character-ref-builder/characters/..%2F..%2Fsecret/media/reference_image_1"
            )
            assert traversal_response.status in {400, 404}

            updated_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}",
                json={"name": "Aria", "description": "renamed"},
            )
            updated = (await updated_response.json())["data"]
            assert updated["id"] == character_id
            assert updated["name"] == "Aria"

            listed_response = await client.get(
                "/api/h3-character-ref-builder/characters"
            )
            assert (await listed_response.json())["data"] == [
                {"id": character_id, "name": "Aria"}
            ]

            deleted_response = await client.delete(
                f"/api/h3-character-ref-builder/characters/{character_id}"
            )
            assert deleted_response.status == 200
            missing_response = await client.get(
                f"/api/h3-character-ref-builder/characters/{character_id}"
            )
            assert missing_response.status == 404

    asyncio.run(scenario())
