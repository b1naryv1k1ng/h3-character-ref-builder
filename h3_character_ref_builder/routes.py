"""HTTP routes served by ComfyUI's existing aiohttp server."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from .character_store import (
    DuplicateCharacterName,
    InvalidCharacterId,
    InvalidProfile,
    MissingMedia,
    ProfileCorrupt,
    ProfileNotFound,
    get_default_store,
)
from .media import MEDIA_SLOTS, InvalidMedia

API_PREFIX = "/api/h3-character-ref-builder"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MANAGER_DIRECTORY = Path(__file__).resolve().parent.parent / "manager"
_ROUTES_REGISTERED = False


def _profile_response(profile: dict[str, Any]) -> dict[str, Any]:
    result = dict(profile)
    character_id = profile["id"]
    result["media_urls"] = {
        slot: (
            f"{API_PREFIX}/characters/{character_id}/media/{slot}"
            if profile.get(slot)
            else None
        )
        for slot in MEDIA_SLOTS
    }
    return result


def _error_status(error: Exception) -> int:
    if isinstance(error, (ProfileNotFound, MissingMedia)):
        return 404
    if isinstance(error, DuplicateCharacterName):
        return 409
    if isinstance(
        error,
        (InvalidCharacterId, InvalidProfile, InvalidMedia, ProfileCorrupt, ValueError),
    ):
        return 400
    return 500


def _error_json(web, error: Exception):
    return web.json_response(
        {"ok": False, "error": {"message": str(error)}}, status=_error_status(error)
    )


async def _json_body(request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise InvalidProfile("Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InvalidProfile("Request JSON must be an object.")
    return payload


def register_routes() -> None:
    """Register once against the singleton PromptServer."""
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    from aiohttp import web
    from server import PromptServer

    routes = PromptServer.instance.routes

    async def list_characters(request):
        del request
        try:
            return web.json_response({"ok": True, "data": get_default_store().list_profiles()})
        except Exception as error:
            return _error_json(web, error)

    async def get_character(request):
        try:
            profile = get_default_store().get_profile(request.match_info["id"])
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def create_character(request):
        try:
            payload = await _json_body(request)
            unexpected = set(payload) - {"name", "description"}
            if unexpected:
                raise InvalidProfile(
                    f"Unsupported profile fields: {', '.join(sorted(unexpected))}."
                )
            profile = get_default_store().create_profile(
                payload.get("name", ""), payload.get("description", "")
            )
            return web.json_response(
                {"ok": True, "data": _profile_response(profile)}, status=201
            )
        except Exception as error:
            return _error_json(web, error)

    async def update_character(request):
        try:
            payload = await _json_body(request)
            unexpected = set(payload) - {"name", "description"}
            if unexpected:
                raise InvalidProfile(
                    f"Unsupported profile fields: {', '.join(sorted(unexpected))}."
                )
            profile = get_default_store().update_profile(
                request.match_info["id"],
                name=payload.get("name"),
                description=payload.get("description"),
            )
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def delete_character(request):
        try:
            get_default_store().delete_profile(request.match_info["id"])
            return web.json_response({"ok": True, "data": None})
        except Exception as error:
            return _error_json(web, error)

    async def upload_media(request):
        try:
            if not request.content_type.startswith("multipart/"):
                raise InvalidMedia("Media uploads must use multipart/form-data.")
            reader = await request.multipart()
            slot = None
            filename = None
            content_type = None
            contents = bytearray()
            async for part in reader:
                if part.name == "slot" and not part.filename:
                    slot = (await part.text()).strip()
                elif part.name == "file" and part.filename:
                    if filename is not None:
                        raise InvalidMedia("Only one multipart 'file' field is allowed.")
                    filename = part.filename
                    content_type = part.headers.get("Content-Type")
                    while True:
                        chunk = await part.read_chunk(size=1024 * 1024)
                        if not chunk:
                            break
                        contents.extend(chunk)
                        if len(contents) > MAX_UPLOAD_BYTES:
                            raise InvalidMedia("Uploaded media exceeds the 100 MiB limit.")
            if slot not in MEDIA_SLOTS:
                raise InvalidMedia(f"Invalid media slot: {slot!r}.")
            if not filename:
                raise InvalidMedia("Multipart field 'file' is required.")
            profile = get_default_store().replace_media(
                request.match_info["id"],
                slot,
                io.BytesIO(contents),
                filename,
                content_type=content_type,
            )
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def serve_media(request):
        try:
            path = get_default_store().media_path(
                request.match_info["id"], request.match_info["slot"]
            )
            response = web.FileResponse(path)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        except Exception as error:
            return _error_json(web, error)

    async def manager_page(request):
        if request.path.endswith("/"):
            raise web.HTTPFound(request.path.rstrip("/"))
        path = MANAGER_DIRECTORY / "index.html"
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    async def manager_asset(request):
        filename = request.match_info["filename"]
        allowed = {"character-manager.js", "character-manager.css"}
        if filename not in allowed:
            raise web.HTTPNotFound()
        path = MANAGER_DIRECTORY / filename
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})

    routes.get(f"{API_PREFIX}/characters")(list_characters)
    routes.get(f"{API_PREFIX}/characters/{{id}}")(get_character)
    routes.post(f"{API_PREFIX}/characters")(create_character)
    routes.put(f"{API_PREFIX}/characters/{{id}}")(update_character)
    routes.delete(f"{API_PREFIX}/characters/{{id}}")(delete_character)
    routes.post(f"{API_PREFIX}/characters/{{id}}/media")(upload_media)
    routes.get(f"{API_PREFIX}/characters/{{id}}/media/{{slot}}")(serve_media)
    routes.get("/character-manager")(manager_page)
    routes.get("/character-manager/")(manager_page)
    routes.get("/character-manager/assets/{filename}")(manager_asset)
    _ROUTES_REGISTERED = True
