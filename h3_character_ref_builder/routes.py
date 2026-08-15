"""HTTP routes served by ComfyUI's existing aiohttp server."""

from __future__ import annotations

import copy
import io
from pathlib import Path
from typing import Any

from .character_store import (
    DuplicateCharacterName,
    InvalidCharacterId,
    InvalidMediaId,
    InvalidProfile,
    MediaLimitReached,
    MediaNotFound,
    MissingMedia,
    ProfileCorrupt,
    ProfileNotFound,
    get_default_store,
)
from .media import InvalidMedia

API_PREFIX = "/api/h3-character-ref-builder"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MANAGER_DIRECTORY = Path(__file__).resolve().parent.parent / "manager"
_ROUTES_REGISTERED = False


def _profile_response(profile: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(profile)
    character_id = profile["id"]
    for collection in ("images", "audio"):
        for record in result[collection]:
            record["url"] = (
                f"{API_PREFIX}/characters/{character_id}/media/{record['id']}"
            )
    defaults = result["defaults"]
    result["generation_ready"] = bool(
        defaults["image_1"] and defaults["image_2"] and defaults["audio"]
    )
    return result


def _error_status(error: Exception) -> int:
    if isinstance(error, (ProfileNotFound, MediaNotFound, MissingMedia)):
        return 404
    if isinstance(error, (DuplicateCharacterName, MediaLimitReached)):
        return 409
    if isinstance(
        error,
        (
            InvalidCharacterId,
            InvalidMediaId,
            InvalidProfile,
            InvalidMedia,
            ProfileCorrupt,
            ValueError,
        ),
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


async def _multipart_body(
    request,
) -> tuple[dict[str, str], bytes | None, str | None, str | None]:
    if not request.content_type.startswith("multipart/"):
        raise InvalidMedia("Media uploads must use multipart/form-data.")
    reader = await request.multipart()
    fields: dict[str, str] = {}
    filename = None
    content_type = None
    contents: bytearray | None = None
    async for part in reader:
        if part.name == "file" and part.filename:
            if filename is not None:
                raise InvalidMedia("Only one multipart 'file' field is allowed.")
            filename = part.filename
            content_type = part.headers.get("Content-Type")
            contents = bytearray()
            while True:
                chunk = await part.read_chunk(size=1024 * 1024)
                if not chunk:
                    break
                contents.extend(chunk)
                if len(contents) > MAX_UPLOAD_BYTES:
                    raise InvalidMedia("Uploaded media exceeds the 100 MiB limit.")
        elif not part.filename and part.name:
            if part.name in fields:
                raise InvalidProfile(f"Duplicate multipart field: {part.name}.")
            fields[part.name] = await part.text()
    return (
        fields,
        bytes(contents) if contents is not None else None,
        filename,
        content_type,
    )


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
            return web.json_response(
                {"ok": True, "data": get_default_store().list_profiles()}
            )
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

    async def create_media(request):
        try:
            fields, contents, filename, content_type = await _multipart_body(request)
            unexpected = set(fields) - {"type", "label"}
            if unexpected:
                raise InvalidProfile(
                    f"Unsupported media fields: {', '.join(sorted(unexpected))}."
                )
            if contents is None or not filename:
                raise InvalidMedia("Multipart field 'file' is required.")
            profile = get_default_store().add_media(
                request.match_info["id"],
                fields.get("type", ""),
                io.BytesIO(contents),
                filename,
                label=fields.get("label", ""),
                content_type=content_type,
            )
            return web.json_response(
                {"ok": True, "data": _profile_response(profile)}, status=201
            )
        except Exception as error:
            return _error_json(web, error)

    async def update_media(request):
        try:
            label: str | object
            contents = None
            filename = None
            content_type = None
            if request.content_type.startswith("multipart/"):
                fields, contents, filename, content_type = await _multipart_body(
                    request
                )
                unexpected = set(fields) - {"label"}
                if unexpected:
                    raise InvalidProfile(
                        f"Unsupported media fields: {', '.join(sorted(unexpected))}."
                    )
                label = fields.get("label", route_unset)
            else:
                payload = await _json_body(request)
                if set(payload) != {"label"}:
                    raise InvalidProfile(
                        "A media JSON update must contain only 'label'."
                    )
                label = payload["label"]
            if label is route_unset and contents is None:
                raise InvalidProfile(
                    "Media update must include a label or replacement file."
                )
            kwargs: dict[str, Any] = {
                "source": io.BytesIO(contents) if contents is not None else None,
                "original_filename": filename,
                "content_type": content_type,
            }
            if label is not route_unset:
                kwargs["label"] = label
            profile = get_default_store().update_media(
                request.match_info["id"], request.match_info["media_id"], **kwargs
            )
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def delete_media(request):
        try:
            profile = get_default_store().delete_media(
                request.match_info["id"], request.match_info["media_id"]
            )
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def update_defaults(request):
        try:
            payload = await _json_body(request)
            if set(payload) != {"image_1", "image_2", "audio"}:
                raise InvalidProfile(
                    "Defaults must contain exactly image_1, image_2, and audio."
                )
            profile = get_default_store().set_defaults(
                request.match_info["id"],
                image_1=payload["image_1"],
                image_2=payload["image_2"],
                audio=payload["audio"],
            )
            return web.json_response({"ok": True, "data": _profile_response(profile)})
        except Exception as error:
            return _error_json(web, error)

    async def serve_media(request):
        try:
            path = get_default_store().media_path(
                request.match_info["id"], request.match_info["media_id"]
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

    route_unset = object()
    routes.get(f"{API_PREFIX}/characters")(list_characters)
    routes.get(f"{API_PREFIX}/characters/{{id}}")(get_character)
    routes.post(f"{API_PREFIX}/characters")(create_character)
    routes.put(f"{API_PREFIX}/characters/{{id}}")(update_character)
    routes.delete(f"{API_PREFIX}/characters/{{id}}")(delete_character)
    routes.post(f"{API_PREFIX}/characters/{{id}}/media")(create_media)
    routes.put(f"{API_PREFIX}/characters/{{id}}/media/{{media_id}}")(update_media)
    routes.delete(f"{API_PREFIX}/characters/{{id}}/media/{{media_id}}")(delete_media)
    routes.get(f"{API_PREFIX}/characters/{{id}}/media/{{media_id}}")(serve_media)
    routes.put(f"{API_PREFIX}/characters/{{id}}/defaults")(update_defaults)
    routes.get("/character-manager")(manager_page)
    routes.get("/character-manager/")(manager_page)
    routes.get("/character-manager/assets/{filename}")(manager_asset)
    _ROUTES_REGISTERED = True
