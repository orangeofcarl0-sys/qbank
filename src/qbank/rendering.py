"""Shared sandboxed Jinja and MarkdownIt rendering services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Protocol, cast

from jinja2 import (
    FileSystemLoader,
    PackageLoader,
    StrictUndefined,
    select_autoescape,
)
from jinja2.sandbox import SandboxedEnvironment
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

from qbank.assets import AssetKind, classify_resource_uri
from qbank.context import ProjectContext


class _ImageRule(Protocol):
    def __call__(
        self,
        tokens: Sequence[Token],
        index: int,
        options: OptionsDict,
        environment: EnvType,
    ) -> str: ...


def number_text(value: float | int | None) -> str:
    """Format paper score values without unnecessary decimal zeroes."""
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


class RenderService:
    """Render trusted templates and untrusted Markdown with shared policy."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def environment(self, *, html: bool = False) -> SandboxedEnvironment:
        """Create a sandboxed environment for project-owned paper templates."""
        environment = SandboxedEnvironment(
            loader=FileSystemLoader(self.context.paths.templates),
            autoescape=select_autoescape(["html", "xml"]) if html else False,
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        environment.filters["number"] = number_text
        return environment

    def internal_environment(self) -> SandboxedEnvironment:
        """Create a sandboxed environment for immutable package templates."""
        return SandboxedEnvironment(
            loader=PackageLoader("qbank", "resources"),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def project_template(
        self,
        name: str,
        values: Mapping[str, object],
        *,
        html: bool = False,
    ) -> str:
        """Render one trusted project template inside the sandbox."""
        return self.environment(html=html).get_template(name).render(**values)

    def internal_template(
        self,
        name: str,
        values: Mapping[str, object],
    ) -> str:
        """Render one immutable package template inside the sandbox."""
        return self.internal_environment().get_template(name).render(**values)

    def markdown_html(
        self,
        markdown: str,
        *,
        asset_prefix: str | None = None,
    ) -> str:
        """Render Markdown with raw HTML disabled and optional token URI mapping."""
        return self._render_markdown(
            markdown,
            asset_prefix=asset_prefix,
            asset_bindings={},
        )

    def interactive_markdown_html(
        self,
        markdown: str,
        *,
        asset_bindings: Mapping[str, str],
    ) -> str:
        """Render images with stable IDs for the desktop interaction bridge."""
        return self._render_markdown(
            markdown,
            asset_prefix=None,
            asset_bindings=asset_bindings,
        )

    def _render_markdown(
        self,
        markdown: str,
        *,
        asset_prefix: str | None,
        asset_bindings: Mapping[str, str],
    ) -> str:
        parser = MarkdownIt("commonmark", {"html": False})
        if asset_prefix is not None or asset_bindings:
            renderer = cast(RendererHTML, parser.renderer)
            rules = cast(dict[str, _ImageRule], renderer.rules)
            default_image = rules["image"]

            def image_rule(
                tokens: Sequence[Token],
                index: int,
                options: OptionsDict,
                environment: EnvType,
            ) -> str:
                token = tokens[index]
                source = token.attrGet("src")
                if isinstance(source, str) and source:
                    asset_id = asset_bindings.get(source)
                    if asset_id is not None:
                        token.attrSet("data-asset-id", asset_id)
                        token.attrSet("draggable", "true")
                    if asset_prefix is not None:
                        token.attrSet(
                            "src",
                            self.preview_asset_uri(source, asset_prefix),
                        )
                return default_image(tokens, index, options, environment)

            rules["image"] = image_rule
        return parser.render(markdown)

    def preview_asset_uri(self, uri: str, asset_prefix: str) -> str:
        """Map a configured project asset URI into preview output layout."""
        reference = classify_resource_uri(uri)
        if reference.kind != AssetKind.LOCAL or reference.normalized is None:
            return uri
        configured = PurePosixPath(self.context.config.paths.assets)
        candidate = PurePosixPath(reference.normalized)
        if not candidate.is_relative_to(configured):
            return uri
        relative = candidate.relative_to(configured).as_posix()
        return f"{asset_prefix}assets/{relative}"

    def html_document(
        self,
        *,
        title: str,
        language: str,
        markdown: str,
    ) -> str:
        """Render Markdown inside the shared sandboxed HTML document."""
        body_html = self.markdown_html(markdown)
        template = self.environment(html=True).get_template("paper.html.j2")
        return template.render(
            language=language,
            title=title,
            body_html=body_html,
        )
