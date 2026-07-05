#!/usr/bin/env python3
"""Export Adobe XD page metadata and a page bundle from a share link."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from capture_xd_artboard import capture_artboard_scales, launch_capture_browser, parse_scale_list
from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    # Parse command-line options for the XD page bundle exporter.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Adobe XD share/specs URL")
    parser.add_argument(
        "--output-root",
        default=".xd-export",
        help="Root export folder. Defaults to .xd-export in the current project",
    )
    parser.add_argument("--browser-width", type=int, default=1600, help="Initial metadata viewport width")
    parser.add_argument("--browser-height", type=int, default=1200, help="Initial metadata viewport height")
    parser.add_argument("--wait-ms", type=int, default=12000, help="Initial wait after navigation")
    parser.add_argument("--post-zoom-wait-ms", type=int, default=1000, help="Wait after changing XD zoom")
    parser.add_argument("--capture-scales", default="1,2", help="Comma-separated native output scales")
    return parser.parse_args()


def slugify(text: str) -> str:
    # Convert a screen title into a filesystem-safe slug.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-")
    return cleaned or "xd-screen"


def safe_path_component(text: str) -> str:
    # Sanitize text for use in a folder name.
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", text.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned or "xd-share"


def normalize_display_title(text: str) -> str:
    # Normalize spacing and underscores for human-readable titles.
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip() or "xd-project"


def extract_screen_id(url: str) -> str | None:
    # Extract a screen UUID from an XD URL.
    match = re.search(r"/screen/([0-9a-f-]{36})(?:/|$)", url, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def extract_view_base_url(url: str) -> str | None:
    # Extract the shared XD view root from a URL.
    match = re.match(r"(https://xd\.adobe\.com/view/[^/]+)", url, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def build_grid_url(view_base_url: str) -> str:
    # Build the grid route for the shared XD view.
    return view_base_url.rstrip("/") + "/grid"


def build_screen_url(view_base_url: str, screen_id: str) -> str:
    # Build the canonical screen route for a screen id.
    return view_base_url.rstrip("/") + f"/screen/{screen_id}/"


def build_screen_specs_url(view_base_url: str, screen_id: str) -> str:
    # Build the canonical specs route for a screen id.
    return build_screen_url(view_base_url, screen_id) + "specs/"


def extract_inline_json_assignment(html_text: str, assignment_name: str) -> Any:
    # Parse an inline JSON object assigned in the HTML response.
    marker = f"{assignment_name} ="
    start = html_text.find(marker)
    if start == -1:
        raise RuntimeError(f"Unable to find inline assignment for {assignment_name}.")
    brace_start = html_text.find("{", start)
    if brace_start == -1:
        raise RuntimeError(f"Unable to find JSON object start for {assignment_name}.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(brace_start, len(html_text)):
        char = html_text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html_text[brace_start : index + 1])

    raise RuntimeError(f"Unable to parse inline JSON object for {assignment_name}.")


def extract_meta_content(html_text: str, attr_name: str, attr_value: str) -> str | None:
    # Read a meta tag value from the HTML as a fallback.
    patterns = [
        rf'<meta[^>]+{attr_name}="{re.escape(attr_value)}"[^>]+content="([^"]*)"',
        rf"<meta[^>]+{attr_name}='{re.escape(attr_value)}'[^>]+content='([^']*)'",
        rf'<meta[^>]+content="([^"]*)"[^>]+{attr_name}="{re.escape(attr_value)}"',
        rf"<meta[^>]+content='([^']*)'[^>]+{attr_name}='{re.escape(attr_value)}'",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return None


def extract_document_title(html_text: str) -> str | None:
    # Read the document title from the HTML as a fallback.
    match = re.search(r"<title>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return html.unescape(match.group(1)).strip()
    return None


def version_tag_from_modified_date(modified_date_ms: int | None) -> str | None:
    # Convert the XD modified timestamp into a version tag.
    if not modified_date_ms:
        return None
    dt = datetime.fromtimestamp(modified_date_ms / 1000)
    return f"v{dt.month:02d}{dt.day:02d}{dt.hour:02d}{dt.minute:02d}"


def resolve_target_screen_id(
    artboards: list[dict[str, Any]],
    requested_screen_id: str | None,
) -> str:
    # Resolve the requested screen id or fall back to the first artboard.
    if not artboards:
        raise RuntimeError("Unable to find any artboards in window.prototypeData.")

    if requested_screen_id:
        if any(artboard.get("id") == requested_screen_id for artboard in artboards):
            return requested_screen_id
        raise RuntimeError(
            f"Unable to find screen id {requested_screen_id} in window.prototypeData manifest artboards."
        )

    first_screen_id = artboards[0].get("id")
    if not first_screen_id:
        raise RuntimeError("Unable to resolve a default screen id from the first artboard.")
    return first_screen_id


def build_run_dir(
    version_dir: Path,
    screen_title: str,
    screen_index: int | None,
) -> Path:
    # Build a page export directory and append a timestamp on collision.
    slug = slugify(screen_title)
    base_name = f"{screen_index}-{slug}" if screen_index is not None else slug
    candidate = version_dir / base_name
    if not candidate.exists():
        return candidate
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return version_dir / f"{base_name}-{timestamp}"


def build_version_dir(output_root: Path, project_title: str, version_tag: str | None) -> Path:
    # Build the version-level export directory from project metadata.
    project_label = safe_path_component(normalize_display_title(project_title))
    version_dir_name = f"{project_label} - {version_tag}" if version_tag else project_label
    return output_root / version_dir_name


def relative_path_str(path: Path, root: Path) -> str:
    # Convert an absolute path into a path relative to the working root.
    return os.path.relpath(path, start=root)


def build_page_source_entry(
    artboard: dict[str, Any],
    screen_index: int,
    view_base_url: str,
) -> dict[str, Any]:
    # Build normalized page metadata for index and page output files.
    bounds = artboard.get("bounds", {})
    viewport = artboard.get("viewport", {})
    design_width = int(bounds.get("width"))
    design_height = int(bounds.get("height"))
    screen_id = artboard.get("id")
    return {
        "screenId": screen_id,
        "screenIndex": screen_index,
        "screenTitle": artboard.get("name"),
        "url": build_screen_url(view_base_url, screen_id),
        "viewportWidth": int(viewport.get("width", design_width)),
        "viewportHeight": int(viewport.get("height", design_height)),
        "designWidth": design_width,
        "designHeight": design_height,
    }


def update_pages_index(
    pages_index_path: Path,
    prototype_data: dict[str, Any],
    version_dir: Path,
    run_dir: Path,
    current_page_source: dict[str, Any],
    project_title: str,
    modified_date: int | None,
    version_tag: str | None,
    root_dir: Path,
    exported_at: str,
    view_base_url: str,
) -> None:
    # Update the version-level page index with the latest export entry.
    existing: dict[str, Any] = {}
    if pages_index_path.exists():
        try:
            existing = json.loads(pages_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    existing_pages = {}
    for page_entry in existing.get("pages", []):
        screen_id = page_entry.get("screenId")
        if screen_id:
            existing_pages[screen_id] = page_entry

    manifest = prototype_data.get("manifest", {})
    artboards = manifest.get("artboards", [])
    version_dir_rel = relative_path_str(version_dir, root_dir)
    xd_metadata_rel = relative_path_str(version_dir / "xd-metadata.json", root_dir)
    run_dir_rel = relative_path_str(run_dir, root_dir)

    pages_payload = []
    for zero_index, artboard in enumerate(artboards):
        screen_index = zero_index + 1
        source = build_page_source_entry(artboard, screen_index, view_base_url)
        screen_id = source["screenId"]
        existing_page = existing_pages.get(screen_id, {})
        exports = [
            {
                "exportedAt": item.get("exportedAt"),
                "directory": item.get("directory"),
            }
            for item in existing_page.get("exports", [])
            if item.get("directory")
        ]

        if screen_id == current_page_source["screenId"]:
            current_export = {
                "exportedAt": exported_at,
                "directory": run_dir_rel,
            }
            if not any(item.get("directory") == run_dir_rel for item in exports):
                exports.append(current_export)
            latest_directory = run_dir_rel
        else:
            latest_directory = existing_page.get("directory")

        pages_payload.append(
            {
                **source,
                "directory": latest_directory,
                "exports": exports,
            }
        )

    payload = {
        "project": {
            "projectTitle": project_title,
            "modifiedDate": modified_date,
            "versionTag": version_tag,
            "screenCount": len(artboards),
            "url": build_grid_url(view_base_url),
            "versionDirectory": version_dir_rel,
            "xdMetadataFile": xd_metadata_rel,
        },
        "pages": pages_payload,
    }
    pages_index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_xd_metadata(page: Any, input_url: str, wait_ms: int) -> dict[str, Any]:
    # Read the XD HTML response, inline prototype data, and resolved route.
    response = page.goto(input_url, wait_until="load", timeout=90000)
    if response is None:
        raise RuntimeError("Unable to read the initial XD HTML response.")
    html_text = response.text()
    page.wait_for_timeout(wait_ms)
    return {
        "htmlText": html_text,
        "resolvedUrl": page.url,
        "prototypeData": extract_inline_json_assignment(html_text, "window.prototypeData"),
    }


def main() -> int:
    # Run the metadata-first XD export workflow from input URL to output files.
    args = parse_args()
    output_root = Path(args.output_root)
    root_dir = Path.cwd()
    input_url = args.url
    exported_at = datetime.now().isoformat(timespec="seconds")

    with sync_playwright() as p:
        browser = launch_capture_browser(p)
        try:
            page = browser.new_page(viewport={"width": args.browser_width, "height": args.browser_height})
            try:
                metadata_source = read_xd_metadata(page, input_url, args.wait_ms)
            finally:
                page.close()

            html_text = metadata_source["htmlText"]
            input_resolved_url = metadata_source["resolvedUrl"]
            prototype_data = metadata_source["prototypeData"]
            view_base_url = extract_view_base_url(input_resolved_url) or extract_view_base_url(input_url)
            if not view_base_url:
                raise RuntimeError("Unable to resolve XD view base URL.")

            manifest = prototype_data.get("manifest", {})
            artboards = manifest.get("artboards", [])
            screen_count = len(artboards)
            requested_screen_id = extract_screen_id(input_resolved_url) or extract_screen_id(input_url)
            screen_id = resolve_target_screen_id(artboards, requested_screen_id)
            capture_url = build_screen_specs_url(view_base_url, screen_id)
            matched_index = next(index for index, artboard in enumerate(artboards) if artboard.get("id") == screen_id)

            artboard = artboards[matched_index]
            project_title = (
                manifest.get("name")
                or extract_meta_content(html_text, "property", "og:title")
                or extract_meta_content(html_text, "name", "twitter:title")
                or extract_document_title(html_text)
                or "xd-project"
            )
            screen_title = (
                artboard.get("name")
                or extract_meta_content(html_text, "property", "og:title")
                or extract_meta_content(html_text, "name", "twitter:title")
                or extract_document_title(html_text)
                or "xd-screen"
            )
            modified_date = prototype_data.get("modifiedDate")
            version_tag = version_tag_from_modified_date(modified_date)
            screen_index = matched_index + 1
            current_page_source = build_page_source_entry(artboard, screen_index, view_base_url)
            design_width = current_page_source["designWidth"]
            design_height = current_page_source["designHeight"]
            viewport_width = current_page_source["viewportWidth"]
            viewport_height = current_page_source["viewportHeight"]
            screen_url = current_page_source["url"]

            version_dir = build_version_dir(output_root, project_title, version_tag)
            version_dir.mkdir(parents=True, exist_ok=True)
            xd_metadata_path = version_dir / "xd-metadata.json"
            xd_metadata_path.write_text(
                json.dumps(prototype_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            run_dir = build_run_dir(version_dir, screen_title, screen_index)
            run_dir.mkdir(parents=True, exist_ok=True)

            capture_result = capture_artboard_scales(
                browser=browser,
                capture_url=capture_url,
                output_dir=run_dir,
                design_width=design_width,
                design_height=design_height,
                scale_values=parse_scale_list(args.capture_scales),
                wait_ms=args.wait_ms,
                post_zoom_wait_ms=args.post_zoom_wait_ms,
            )
        finally:
            browser.close()

    scale_outputs_rel = {
        key: relative_path_str(Path(path), root_dir)
        for key, path in capture_result["files"].items()
    }
    metadata = {
        "source": {
            "url": screen_url,
            "projectTitle": project_title,
            "modifiedDate": modified_date,
            "screenId": screen_id,
            "screenTitle": screen_title,
            "screenIndex": screen_index,
            "screenCount": screen_count,
            "viewportWidth": viewport_width,
            "viewportHeight": viewport_height,
            "designWidth": design_width,
            "designHeight": design_height,
        },
        "capture": {
            "strategy": capture_result["strategy"],
            "scales": capture_result["scales"],
        },
        "outputs": {
            "versionDirectory": relative_path_str(version_dir, root_dir),
            "directory": relative_path_str(run_dir, root_dir),
            "xdMetadataFile": relative_path_str(xd_metadata_path, root_dir),
            "files": scale_outputs_rel,
        },
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    update_pages_index(
        pages_index_path=version_dir / "pages.json",
        prototype_data=prototype_data,
        version_dir=version_dir,
        run_dir=run_dir,
        current_page_source=current_page_source,
        project_title=project_title,
        modified_date=modified_date,
        version_tag=version_tag,
        root_dir=root_dir,
        exported_at=exported_at,
        view_base_url=view_base_url,
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
