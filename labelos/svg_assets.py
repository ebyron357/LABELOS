"""Safe resolution of external raster assets referenced by SVG artwork."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

_SVG_DOCTYPE_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def local_svg_image_path(svg_path: Path, href: str) -> Path | None:
    """Return a safe local image path, or ``None`` for an embedded data URI.

    SVG artwork is a release input, so image references may not escape the artwork
    directory, use a network/file URI, point at a symlink, or include a query or
    fragment that would make the packaged dependency ambiguous.
    """

    if href.startswith("data:"):
        if not href.startswith("data:image/"):
            raise ValueError("image data URI must declare an image media type")
        return None
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError("image href must be a local relative path")
    if parsed.query or parsed.fragment:
        raise ValueError("image href must not contain a query or fragment")
    if not parsed.path:
        raise ValueError("image href is empty")

    svg_directory = svg_path.parent.resolve()
    candidate = (svg_directory / unquote(parsed.path)).resolve()
    try:
        candidate.relative_to(svg_directory)
    except ValueError as error:
        raise ValueError("image href escapes the SVG directory") from error
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("image href does not name a regular local file")
    return candidate


def linked_svg_image_paths(svg_path: Path) -> list[Path]:
    """Return external image dependencies in an SVG after applying path policy."""

    text = svg_path.read_text(encoding="utf-8", errors="replace")
    if _SVG_DOCTYPE_RE.search(text):
        raise ValueError("SVG contains a DOCTYPE or entity declaration")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValueError(f"SVG is not valid XML: {error}") from error

    paths: list[Path] = []
    for image in (element for element in root.iter() if _local_name(element.tag) == "image"):
        href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href")
        if href is None:
            raise ValueError("SVG image has no href")
        path = local_svg_image_path(svg_path, href)
        if path is not None and path not in paths:
            paths.append(path)
    return paths


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
