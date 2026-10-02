"""Authenticated document and export HTTP endpoints."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from aiohttp.helpers import content_disposition_header
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant

from .const import DOCUMENT_MIME_TYPES, DOMAIN, MAX_DOCUMENT_BYTES, MAX_SHORT_TEXT
from .models import utcnow_iso


def _manager(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or not getattr(entries[0], "runtime_data", None):
        raise web.HTTPServiceUnavailable(text="Dog Assistant is not loaded")
    return entries[0].runtime_data.manager


def _detected_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_filename(value: str, fallback: str = "document") -> str:
    """Return a portable basename safe for headers and ZIP members."""
    name = re.split(r"[/\\]", value)[-1]
    name = "".join(character for character in name if character.isprintable() and character not in {'"', "\r", "\n"})
    return name.strip(" .")[:MAX_SHORT_TEXT] or fallback


class DogAssistantDocumentUploadView(HomeAssistantView):
    """Upload a private dog document."""

    url = "/api/dogassistant/documents"
    name = "api:dogassistant:documents:upload"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request) -> web.Response:
        manager = _manager(request.app["hass"])
        reader = await request.multipart()
        dog_id: str | None = None
        label: str | None = None
        category = "other"
        filename = "document"
        claimed_type: str | None = None
        payload: bytes | None = None
        async for part in reader:
            if part.name == "dog_id":
                dog_id = (await part.text()).strip()
            elif part.name == "label":
                label = (await part.text()).strip()
            elif part.name == "category":
                category = (await part.text()).strip()
            elif part.name == "file":
                filename = _safe_filename(Path(part.filename or filename).name)
                claimed_type = part.headers.get("Content-Type")
                buffer = bytearray()
                while chunk := await part.read_chunk():
                    buffer.extend(chunk)
                    if len(buffer) > MAX_DOCUMENT_BYTES:
                        raise web.HTTPRequestEntityTooLarge(max_size=MAX_DOCUMENT_BYTES, actual_size=len(buffer))
                payload = bytes(buffer)
        if not dog_id or dog_id not in manager.data["dogs"]:
            raise web.HTTPBadRequest(text="A valid dog_id is required")
        if label and len(label) > MAX_SHORT_TEXT:
            raise web.HTTPBadRequest(text=f"Labels are limited to {MAX_SHORT_TEXT} characters")
        if category not in {"medical", "vaccination", "insurance", "registration", "other", "profile_photo"}:
            raise web.HTTPBadRequest(text="Invalid document category")
        if not payload:
            raise web.HTTPBadRequest(text="A non-empty file is required")
        detected_type = _detected_type(payload)
        if detected_type not in DOCUMENT_MIME_TYPES or (claimed_type and claimed_type != detected_type):
            raise web.HTTPUnsupportedMediaType(text="Only genuine PDF, JPEG, PNG, and WebP files are accepted")
        if not manager.can_store_document(len(payload)):
            raise web.HTTPInsufficientStorage(text="Dog Assistant document storage limit reached")
        document_id = uuid4().hex
        stored_name = f"{document_id}{DOCUMENT_MIME_TYPES[detected_type]}"
        path = manager.document_directory / stored_name
        await manager.hass.async_add_executor_job(path.write_bytes, payload)
        metadata = await manager.async_add_document(
            dog_id,
            {
                "id": document_id,
                "label": label or filename,
                "category": category,
                "original_name": filename,
                "stored_name": stored_name,
                "content_type": detected_type,
                "size": len(payload),
                "uploaded_at": utcnow_iso(),
            },
        )
        return self.json(metadata, status_code=201)


class DogAssistantDocumentView(HomeAssistantView):
    """Download or remove a private dog document."""

    url = "/api/dogassistant/documents/{document_id}"
    name = "api:dogassistant:documents:item"
    requires_auth = True

    async def get(self, request: web.Request, document_id: str) -> web.StreamResponse:
        manager = _manager(request.app["hass"])
        found = manager.find_document(document_id)
        if not found:
            raise web.HTTPNotFound()
        _, metadata = found
        path = manager.document_directory / metadata["stored_name"]
        if not path.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(path)
        response.content_type = metadata["content_type"]
        response.headers["Content-Disposition"] = content_disposition_header(
            "inline", filename=_safe_filename(metadata["original_name"])
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @require_admin
    async def delete(self, request: web.Request, document_id: str) -> web.Response:
        manager = _manager(request.app["hass"])
        metadata = await manager.async_delete_document(document_id)
        if not metadata:
            raise web.HTTPNotFound()
        path = manager.document_directory / metadata["stored_name"]
        if path.is_file():
            await manager.hass.async_add_executor_job(path.unlink)
        return self.json({"deleted": True})


class DogAssistantExportView(HomeAssistantView):
    """Export structured data and documents in a portable ZIP."""

    url = "/api/dogassistant/export"
    name = "api:dogassistant:export"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        manager = _manager(request.app["hass"])
        dog_id = request.query.get("dog_id")
        snapshot = manager.snapshot()
        for event in snapshot["events"]:
            event.pop("created_by_user_id", None)
        if dog_id:
            if dog_id not in snapshot["dogs"]:
                raise web.HTTPNotFound()
            snapshot["dogs"] = {dog_id: snapshot["dogs"][dog_id]}
            snapshot["events"] = [event for event in snapshot["events"] if dog_id in event.get("dog_ids", [])]

        def build_zip() -> bytes:
            output = BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("dogassistant.json", json.dumps(snapshot, indent=2, ensure_ascii=False))
                csv_buffer = StringIO()
                writer = csv.DictWriter(
                    csv_buffer, fieldnames=["id", "type", "dog_ids", "occurred_at", "caregiver", "notes", "data"]
                )
                writer.writeheader()
                for event in snapshot["events"]:
                    writer.writerow(
                        {
                            "id": event["id"],
                            "type": event["type"],
                            "dog_ids": ";".join(event["dog_ids"]),
                            "occurred_at": event.get("occurred_at"),
                            "caregiver": event.get("caregiver"),
                            "notes": event.get("notes"),
                            "data": json.dumps(event.get("data", {}), ensure_ascii=False),
                        }
                    )
                archive.writestr("events.csv", csv_buffer.getvalue())
                for dog in snapshot["dogs"].values():
                    for document in dog.get("documents", []):
                        path = manager.document_directory / document["stored_name"]
                        if path.is_file():
                            filename = _safe_filename(document["original_name"])
                            archive.write(path, f"documents/{dog['id']}/{document['id']}-{filename}")
            return output.getvalue()

        payload = await manager.hass.async_add_executor_job(build_zip)
        return web.Response(
            body=payload,
            content_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="dogassistant-export.zip"'},
        )


def register_http_views(hass: HomeAssistant) -> None:
    """Register authenticated HTTP views."""
    hass.http.register_view(DogAssistantDocumentUploadView)
    hass.http.register_view(DogAssistantDocumentView)
    hass.http.register_view(DogAssistantExportView)
