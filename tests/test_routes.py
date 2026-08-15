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


def media_form(media_type, contents, filename, content_type, label=""):
    form = FormData()
    form.add_field("type", media_type)
    form.add_field("label", label)
    form.add_field("file", contents, filename=filename, content_type=content_type)
    return form


def test_character_library_api_end_to_end(tmp_path, monkeypatch):
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
            assert created["schema_version"] == 3
            assert created["generation_ready"] is False

            image_ids = []
            for index, color in enumerate(((10, 20, 30), (40, 50, 60))):
                response = await client.post(
                    f"/api/h3-character-ref-builder/characters/{character_id}/media",
                    data=media_form(
                        "image",
                        png_bytes(color),
                        f"image-{index}.png",
                        "image/png",
                        f"Image {index + 1}",
                    ),
                )
                assert response.status == 201, await response.text()
                profile = (await response.json())["data"]
                image_ids.append(profile["images"][-1]["id"])

            audio_response = await client.post(
                f"/api/h3-character-ref-builder/characters/{character_id}/media",
                data=media_form(
                    "audio", wav_bytes(), "voice.wav", "audio/wav", "Neutral"
                ),
            )
            assert audio_response.status == 201
            audio_id = (await audio_response.json())["data"]["audio"][-1]["id"]

            defaults_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/defaults",
                json={
                    "image_1": image_ids[0],
                    "image_2": image_ids[1],
                    "audio": audio_id,
                },
            )
            defaults_profile = (await defaults_response.json())["data"]
            assert defaults_response.status == 200
            assert defaults_profile["generation_ready"] is True

            detail_response = await client.get(
                f"/api/h3-character-ref-builder/characters/{character_id}"
            )
            detail = (await detail_response.json())["data"]
            assert detail["images"][0]["url"].endswith(image_ids[0])

            media_response = await client.get(detail["images"][0]["url"])
            assert media_response.status == 200
            assert await media_response.read() == png_bytes((10, 20, 30))

            label_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{image_ids[0]}",
                json={"label": "Front portrait"},
            )
            assert (await label_response.json())["data"]["images"][0][
                "label"
            ] == "Front portrait"

            replace_form = FormData()
            replace_form.add_field(
                "file",
                png_bytes((200, 1, 2)),
                filename="replacement.png",
                content_type="image/png",
            )
            replace_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{image_ids[0]}",
                data=replace_form,
            )
            replaced = (await replace_response.json())["data"]
            assert replaced["images"][0]["id"] == image_ids[0]

            wrong_type_response = await client.put(
                f"/api/h3-character-ref-builder/characters/{character_id}/defaults",
                json={"image_1": audio_id, "image_2": image_ids[1], "audio": audio_id},
            )
            assert wrong_type_response.status == 400

            deleted_response = await client.delete(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{image_ids[0]}"
            )
            after_delete = (await deleted_response.json())["data"]
            assert after_delete["defaults"]["image_1"] is None
            assert after_delete["generation_ready"] is False

            missing_media_response = await client.get(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/{image_ids[0]}"
            )
            assert missing_media_response.status == 404

            traversal_response = await client.get(
                f"/api/h3-character-ref-builder/characters/{character_id}/media/..%2F..%2Fsecret"
            )
            assert traversal_response.status in {400, 404}

            delete_character_response = await client.delete(
                f"/api/h3-character-ref-builder/characters/{character_id}"
            )
            assert delete_character_response.status == 200

    asyncio.run(scenario())
