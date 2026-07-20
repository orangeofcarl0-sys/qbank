"""Local-only HTTP management surface for registered logical assets.

The server is deliberately small: it is a view over the authoritative asset
repository, never a general command runner or arbitrary file browser.  Every
mutation delegates to :class:`AssetApplicationService`, which applies the same
containment, transaction, and history rules as the CLI.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import quote, unquote, urlsplit

from pydantic import BaseModel, ValidationError

from qbank.application.assets import AssetApplicationService
from qbank.application.ports import RenderingPort
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, QBankError
from qbank.models import (
    AssetFormat,
    AssetManifest,
    AssetPackageRepresentation,
    AssetRepresentation,
    AssetServeResult,
)
from qbank.utils import is_relative_to

_DEFAULT_RENDER_FORMATS = (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG)


class AssetManagementServer(ThreadingHTTPServer):
    """A localhost-only HTTP server with immutable management state."""

    daemon_threads = True

    def __init__(self, port: int, manager: _AssetManager):
        self.manager = manager
        super().__init__(("127.0.0.1", port), _AssetManagementHandler)


class _AssetManager:
    """Render dashboard data and dispatch a fixed allowlist of operations."""

    def __init__(
        self,
        context: ProjectContext,
        assets: AssetApplicationService,
        renderer: RenderingPort,
        *,
        questions: int,
    ):
        self.context = context
        self.assets = assets
        self.renderer = renderer
        self.questions = questions
        self.token = secrets.token_urlsafe(32)

    def dashboard(self) -> str:
        """Render an inspectable page containing only registered assets."""
        asset_views = [self._asset_view(item) for item in self.assets.repository.list(strict=False)]
        return self.renderer.internal_template(
            "preview/asset-manager.html.j2",
            {
                "assets": asset_views,
                "token": self.token,
                "preview_url": "/preview/",
            },
        )

    def registered_file(
        self,
        question_id: str,
        asset_id: str,
        representation_id: str,
    ) -> Path:
        """Resolve one local representation after registry and containment checks."""
        manifest = self.assets.repository.get(question_id, asset_id)
        representation = _representation(manifest.representations, representation_id)
        if representation.path is None:
            raise DataValidationError("asset_command_rejected: representation is remote")
        path = self.assets.repository.representation_path(manifest, representation_id)
        if path is None or not path.is_file():
            raise DataValidationError(
                f"asset_representation_missing: representation does not exist: {representation_id}"
            )
        if not is_relative_to(path.resolve(), self.context.paths.assets.resolve()):
            raise DataValidationError("asset_path_escape: representation escaped assets root")
        return path

    def dispatch(
        self,
        question_id: str,
        asset_id: str,
        action: str,
        payload: Mapping[str, object],
    ) -> BaseModel:
        """Execute one fixed asset operation; arbitrary commands are impossible."""
        if action in {"open", "edit", "open-directory"}:
            return self._launch_action(question_id, asset_id, action)
        if action == "render":
            return self.assets.render_asset(
                question_id,
                asset_id,
                formats=_render_formats(payload.get("formats")),
                dry_run=False,
            )
        if action in {"set-render", "set-editor"}:
            representation_id = _required_text(payload, "representation_id")
            return self.assets.set_preference(
                question_id,
                asset_id,
                representation_id,
                kind="render" if action == "set-render" else "editor",
                dry_run=False,
            )
        if action == "finalize":
            return self.assets.finalize(question_id, asset_id, dry_run=False)
        if action == "replace":
            return self.assets.replace(
                question_id,
                asset_id,
                _uploaded_representation(payload),
                self.context.root,
                dry_run=False,
            )
        raise DataValidationError(f"asset_command_rejected: unsupported action: {action}")

    def _launch_action(self, question_id: str, asset_id: str, action: str) -> BaseModel:
        if action == "open":
            return self.assets.open_asset(question_id, asset_id, dry_run=False)
        if action == "edit":
            return self.assets.edit_asset(question_id, asset_id, dry_run=False)
        return self.assets.open_asset_directory(question_id, asset_id, dry_run=False)

    def _asset_view(self, manifest: AssetManifest) -> dict[str, object]:
        representations = [
            {
                "id": item.representation_id,
                "format": item.format.value,
                "purpose": item.purpose,
                "editable": item.editable,
                "derived_from": item.derived_from or "",
                "uri": self._representation_uri(manifest.question_id, manifest.asset_id, item),
                "is_remote": item.url is not None,
                "is_image": item.renderable,
            }
            for item in manifest.representations
        ]
        preview = self.assets.select(manifest, "preview")
        original = next(
            (item for item in representations if item["purpose"] in {"original", "reference"}),
            representations[0],
        )
        current = next(item for item in representations if item["id"] == preview.representation_id)
        return {
            "question_id": manifest.question_id,
            "asset_id": manifest.asset_id,
            "role": manifest.role,
            "status": manifest.status.value,
            "preferred_editor": manifest.preferred_editor or "—",
            "preferred_render": manifest.preferred_render or "—",
            "provenance": json.dumps(manifest.provenance, ensure_ascii=False, indent=2),
            "review_notes": manifest.review_notes,
            "original": original,
            "current": current,
            "representations": representations,
        }

    @staticmethod
    def _representation_uri(
        question_id: str,
        asset_id: str,
        representation: AssetRepresentation,
    ) -> str:
        if representation.url is not None:
            return representation.url
        return "/_assets/{}/{}/{}".format(
            quote(question_id, safe=""),
            quote(asset_id, safe=""),
            quote(representation.representation_id, safe=""),
        )


class _AssetManagementHandler(BaseHTTPRequestHandler):
    """HTTP implementation restricted to dashboard, preview, and fixed APIs."""

    @property
    def asset_server(self) -> AssetManagementServer:
        """Return the locally created server without changing base-handler state."""
        return cast(AssetManagementServer, self.server)

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/":
                self._send_bytes(
                    HTTPStatus.OK,
                    self.asset_server.manager.dashboard().encode("utf-8"),
                    "text/html",
                )
                return
            if path in {"/preview", "/preview/"}:
                self._serve_preview("index.html")
                return
            if path.startswith("/preview/"):
                self._serve_preview(path.removeprefix("/preview/"))
                return
            if path.startswith("/_assets/"):
                self._serve_registered_representation(path)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
        except QBankError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        except OSError:
            self._send_error(HTTPStatus.NOT_FOUND, "file not found")

    def do_POST(self) -> None:
        path = unquote(urlsplit(self.path).path)
        try:
            question_id, asset_id, action = self._api_route(path)
            self._verify_same_origin()
            payload = self._json_body()
            result = self.asset_server.manager.dispatch(question_id, asset_id, action, payload)
            self._send_json(HTTPStatus.OK, result.model_dump(mode="json", exclude_none=True))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
        except (QBankError, ValidationError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        """Do not mix HTTP request logs into JSON-capable CLI output."""
        del format, args

    def _serve_preview(self, relative: str) -> None:
        target = _contained_path(
            self.asset_server.manager.context.paths.build / "preview", relative
        )
        if not target.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "preview file not found")
            return
        self._send_bytes(HTTPStatus.OK, target.read_bytes(), _mime_type(target))

    def _serve_registered_representation(self, path: str) -> None:
        parts = path.removeprefix("/_assets/").split("/")
        if len(parts) != 3 or not all(parts):
            self._send_error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        target = self.asset_server.manager.registered_file(parts[0], parts[1], parts[2])
        self._send_bytes(HTTPStatus.OK, target.read_bytes(), _mime_type(target))

    def _api_route(self, path: str) -> tuple[str, str, str]:
        parts = path.strip("/").split("/")
        if len(parts) != 5 or parts[:2] != ["api", "assets"] or not all(parts[2:]):
            raise DataValidationError("asset_command_rejected: invalid API route")
        return parts[2], parts[3], parts[4]

    def _verify_same_origin(self) -> None:
        token = self.headers.get("X-QBank-Token")
        if token != self.asset_server.manager.token:
            raise DataValidationError("asset_command_rejected: missing or invalid local token")
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.asset_server.server_port}"
        if origin is not None and origin != expected:
            raise DataValidationError("asset_command_rejected: cross-origin request rejected")

    def _json_body(self) -> Mapping[str, object]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise DataValidationError("asset_command_rejected: Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise DataValidationError("asset_command_rejected: invalid Content-Length") from exc
        max_length = self.asset_server.manager.context.config.assets.download_max_bytes * 2
        if length < 0 or length > max_length:
            raise DataValidationError("asset_command_rejected: request body is too large")
        decoded = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise DataValidationError("asset_command_rejected: JSON body must be an object")
        return cast(dict[str, object], decoded)

    def _send_json(self, status: HTTPStatus, value: object) -> None:
        self._send_bytes(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def _send_bytes(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def create_asset_management_server(
    context: ProjectContext,
    assets: AssetApplicationService,
    renderer: RenderingPort,
    *,
    questions: int,
    port: int,
) -> tuple[AssetManagementServer, AssetServeResult]:
    """Create, but do not start, a 127.0.0.1-only management server."""
    if not 0 <= port <= 65535:
        raise DataValidationError("invalid_filter: --port must be between 0 and 65535")
    manager = _AssetManager(context, assets, renderer, questions=questions)
    server = AssetManagementServer(port, manager)
    result = AssetServeResult(
        ok=True,
        host="127.0.0.1",
        port=server.server_port,
        url=f"http://127.0.0.1:{server.server_port}/",
        questions=questions,
        assets=len(assets.repository.list(strict=False)),
    )
    return server, result


def _representation(
    representations: Sequence[AssetRepresentation],
    representation_id: str,
) -> AssetRepresentation:
    for representation in representations:
        if representation.representation_id == representation_id:
            return representation
    raise DataValidationError(f"asset_representation_missing: {representation_id}")


def _render_formats(value: object) -> tuple[AssetFormat, ...]:
    if value is None:
        return _DEFAULT_RENDER_FORMATS
    if not isinstance(value, list) or not value:
        raise DataValidationError("asset_command_rejected: formats must be a non-empty array")
    raw_formats = cast(list[object], value)
    if not all(isinstance(item, str) for item in raw_formats):
        raise DataValidationError("asset_command_rejected: formats must contain strings")
    try:
        formats = tuple(AssetFormat(cast(str, item)) for item in raw_formats)
    except ValueError as exc:
        raise DataValidationError("asset_command_rejected: unsupported render format") from exc
    return formats


def _uploaded_representation(payload: Mapping[str, object]) -> AssetPackageRepresentation:
    data_uri = _required_text(payload, "data_uri")
    return AssetPackageRepresentation(
        representation_id=str(payload.get("representation_id") or "replacement"),
        format=AssetFormat(_required_text(payload, "format")),
        data_uri=data_uri,
        purpose=str(payload.get("purpose") or "replacement"),
        editable=bool(payload.get("editable", False)),
    )


def _required_text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"asset_command_rejected: {name} is required")
    return value.strip()


def _contained_path(root: Path, relative: str) -> Path:
    candidate = (root.resolve() / relative).resolve()
    if not is_relative_to(candidate, root.resolve()):
        raise DataValidationError("asset_path_escape: preview path escapes output root")
    return candidate


def _mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
