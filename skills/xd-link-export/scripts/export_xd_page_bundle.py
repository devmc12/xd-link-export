#!/usr/bin/env python3
"""Export Adobe XD page metadata and a page bundle from a share link."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from capture_xd_artboard import (
    build_candidate_viewports,
    capture_scale_on_page,
    launch_capture_browser,
    parse_scale_list,
    wait_for_capture_ui,
)
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
    parser.add_argument("--wait-ms", type=int, default=15000, help="Maximum wait for XD UI after navigation")
    parser.add_argument("--post-zoom-wait-ms", type=int, default=200, help="Short settle wait after changing XD zoom")
    parser.add_argument("--scales", default="1", help='Native output scales: "1", "2", "1,2", or "2,1"')
    parser.add_argument(
        "--pages",
        help='1-based page selector, for example "1", "1-5,4-7,19", or "01,02,03,13-18"',
    )
    parser.add_argument("--all", action="store_true", help="Export all XD pages")
    parser.add_argument("--parallel", action="store_true", help="Run 1x and 2x scale workers in parallel")
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


def parse_page_selector(selector: str | None, page_count: int) -> list[int]:
    # Parse a 1-based XD page selector into unique page indexes.
    if selector is None or not selector.strip():
        return list(range(1, page_count + 1))

    pages: list[int] = []
    seen: set[int] = set()
    for raw_chunk in selector.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue

        match = re.fullmatch(r"(\d+)(?:-(\d+))?", chunk)
        if not match:
            raise RuntimeError(f"Invalid page selector chunk: {chunk!r}.")

        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        if start < 1 or end < 1:
            raise RuntimeError("XD page indexes are 1-based.")
        if start > end:
            raise RuntimeError(f"Invalid descending page range: {chunk!r}.")
        if end > page_count:
            raise RuntimeError(f"Page range {chunk!r} exceeds XD page count {page_count}.")

        for page_index in range(start, end + 1):
            if page_index not in seen:
                pages.append(page_index)
                seen.add(page_index)

    if not pages:
        raise RuntimeError("No XD pages were selected.")
    return pages


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


def build_page_dir_base(version_dir: Path, screen_title: str, screen_index: int | None) -> Path:
    # Build the stable page directory path before collision handling.
    slug = slugify(screen_title)
    base_name = f"{screen_index}-{slug}" if screen_index is not None else slug
    return version_dir / base_name


def build_work_dir(version_dir: Path, screen_title: str, screen_index: int | None) -> Path:
    # Build a temporary page work directory that is committed only after success.
    slug = slugify(screen_title)
    base_name = f"{screen_index}-{slug}" if screen_index is not None else slug
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return version_dir / ".tmp" / f"{base_name}-{timestamp}-{os.getpid()}"


def is_complete_export_dir(directory: Path, scale_values: list[int]) -> bool:
    # Check whether a page directory already has all requested final files.
    if not directory.exists():
        return False
    if not (directory / "metadata.json").exists():
        return False
    return all((directory / scale_output_name(scale)).exists() for scale in scale_values)


def commit_page_work_dir(work_dir: Path, base_dir: Path, scale_values: list[int]) -> Path:
    # Move a successful temporary page bundle into the final export directory.
    final_dir = build_run_dir(base_dir.parent, base_dir.name, None) if is_complete_export_dir(base_dir, scale_values) else base_dir
    final_dir.mkdir(parents=True, exist_ok=True)
    for item in work_dir.iterdir():
        target = final_dir / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
    try:
        work_dir.rmdir()
        work_dir.parent.rmdir()
    except OSError:
        pass
    return final_dir


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
    response = page.goto(input_url, wait_until="domcontentloaded", timeout=30000)
    if response is None:
        raise RuntimeError("Unable to read the initial XD HTML response.")
    html_text = response.text()
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    return {
        "htmlText": html_text,
        "resolvedUrl": page.url,
        "prototypeData": extract_inline_json_assignment(html_text, "window.prototypeData"),
    }


def scale_key(scale_value: int) -> str:
    # Format a native scale value for output metadata.
    return f"{scale_value}x"


def scale_output_name(scale_value: int) -> str:
    # Build the PNG file name for a native scale value.
    return "artboard-1x.png" if scale_value == 1 else f"artboard-{scale_value}x.png"


def build_page_export_plan(
    version_dir: Path,
    artboard: dict[str, Any],
    screen_index: int,
    screen_count: int,
    project_title: str,
    modified_date: int | None,
    root_dir: Path,
    view_base_url: str,
) -> dict[str, Any]:
    # Prepare one page directory and immutable source metadata before capture.
    screen_id = artboard.get("id")
    if not screen_id:
        raise RuntimeError(f"Unable to resolve a screen id for page index {screen_index}.")

    current_page_source = build_page_source_entry(artboard, screen_index, view_base_url)
    screen_title = artboard.get("name") or f"xd-screen-{screen_index}"
    capture_url = build_screen_specs_url(view_base_url, screen_id)
    base_dir = build_page_dir_base(version_dir, screen_title, screen_index)
    work_dir = build_work_dir(version_dir, screen_title, screen_index)
    work_dir.mkdir(parents=True, exist_ok=True)

    return {
        "artboard": artboard,
        "source": current_page_source,
        "screenIndex": screen_index,
        "screenCount": screen_count,
        "screenId": screen_id,
        "screenTitle": screen_title,
        "captureUrl": capture_url,
        "baseDir": base_dir,
        "workDir": work_dir,
        "runDir": None,
        "projectTitle": project_title,
        "modifiedDate": modified_date,
        "rootDir": root_dir,
    }


def capture_scale_worker(
    scale_value: int,
    page_plans: list[dict[str, Any]],
    wait_ms: int,
    post_zoom_wait_ms: int,
) -> dict[str, Any]:
    # Capture one native scale for all selected pages while reusing one specs page.
    results: dict[int, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    key = scale_key(scale_value)

    try:
        with sync_playwright() as p:
            browser = launch_capture_browser(p)
            try:
                context: Any | None = None
                page: Any | None = None
                first_plan = page_plans[0]
                initial_viewport = build_candidate_viewports(
                    first_plan["source"]["designWidth"],
                    first_plan["source"]["designHeight"],
                    scale_value,
                )[0]
                context = browser.new_context(viewport=initial_viewport, device_scale_factor=1)
                page = context.new_page()
                try:
                    for plan in page_plans:
                        output_path = plan["workDir"] / scale_output_name(scale_value)
                        try:
                            page.set_viewport_size(
                                build_candidate_viewports(
                                    plan["source"]["designWidth"],
                                    plan["source"]["designHeight"],
                                    scale_value,
                                )[0]
                            )
                            page.goto(
                                plan["captureUrl"],
                                wait_until="domcontentloaded",
                                timeout=max(wait_ms + 5000, 20000),
                            )
                            wait_for_capture_ui(page, wait_ms)
                            capture = capture_scale_on_page(
                                page=page,
                                output_path=output_path,
                                design_width=plan["source"]["designWidth"],
                                design_height=plan["source"]["designHeight"],
                                scale_value=scale_value,
                                post_zoom_wait_ms=post_zoom_wait_ms,
                            )
                            results[plan["screenIndex"]] = {
                                "files": {key: str(output_path)},
                                "scales": {key: capture},
                            }
                        except Exception as exc:
                            errors.append(
                                {
                                    "screenIndex": plan["screenIndex"],
                                    "screenId": plan["screenId"],
                                    "screenTitle": plan["screenTitle"],
                                    "scale": key,
                                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                                }
                            )
                finally:
                    if page is not None:
                        page.close()
                    if context is not None:
                        context.close()
            finally:
                browser.close()
    except Exception as exc:
        for plan in page_plans:
            errors.append(
                {
                    "screenIndex": plan["screenIndex"],
                    "screenId": plan["screenId"],
                    "screenTitle": plan["screenTitle"],
                    "scale": key,
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                }
            )

    return {"scale": scale_value, "results": results, "errors": errors}


def capture_selected_scales(
    scale_values: list[int],
    page_plans: list[dict[str, Any]],
    wait_ms: int,
    post_zoom_wait_ms: int,
    parallel: bool,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]], bool]:
    # Run scale-major capture, optionally parallelizing the 1x and 2x workers.
    capture_by_page = {
        plan["screenIndex"]: {"strategy": "xd-zoom-svg-rect", "files": {}, "scales": {}, "errors": []}
        for plan in page_plans
    }
    all_errors: list[dict[str, Any]] = []
    run_parallel = parallel and len(scale_values) > 1
    if not page_plans:
        return capture_by_page, all_errors, False

    def merge_worker_result(worker_result: dict[str, Any]) -> None:
        for screen_index, result in worker_result["results"].items():
            capture_by_page[screen_index]["files"].update(result["files"])
            capture_by_page[screen_index]["scales"].update(result["scales"])
        for error in worker_result["errors"]:
            all_errors.append(error)
            capture_by_page[error["screenIndex"]]["errors"].append(error)

    if run_parallel:
        with ThreadPoolExecutor(max_workers=len(scale_values)) as executor:
            futures = [
                executor.submit(capture_scale_worker, scale, page_plans, wait_ms, post_zoom_wait_ms)
                for scale in scale_values
            ]
            for future in as_completed(futures):
                merge_worker_result(future.result())
    else:
        for scale in scale_values:
            merge_worker_result(capture_scale_worker(scale, page_plans, wait_ms, post_zoom_wait_ms))

    return capture_by_page, all_errors, run_parallel


def write_page_metadata(
    plan: dict[str, Any],
    capture_result: dict[str, Any],
    version_dir: Path,
    xd_metadata_path: Path,
    root_dir: Path,
) -> dict[str, Any]:
    # Write the merged page source and capture metadata for one selected page.
    current_page_source = plan["source"]
    scale_outputs_rel = {
        key: relative_path_str(Path(path), root_dir)
        for key, path in capture_result.get("files", {}).items()
    }
    metadata = {
        "source": {
            "url": current_page_source["url"],
            "projectTitle": plan["projectTitle"],
            "modifiedDate": plan["modifiedDate"],
            "screenId": plan["screenId"],
            "screenTitle": plan["screenTitle"],
            "screenIndex": plan["screenIndex"],
            "screenCount": plan["screenCount"],
            "viewportWidth": current_page_source["viewportWidth"],
            "viewportHeight": current_page_source["viewportHeight"],
            "designWidth": current_page_source["designWidth"],
            "designHeight": current_page_source["designHeight"],
        },
        "capture": {
            "strategy": capture_result["strategy"],
            "scales": capture_result["scales"],
        },
        "outputs": {
            "versionDirectory": relative_path_str(version_dir, root_dir),
            "directory": relative_path_str(plan["runDir"], root_dir),
            "xdMetadataFile": relative_path_str(xd_metadata_path, root_dir),
            "files": scale_outputs_rel,
        },
    }
    if capture_result.get("errors"):
        metadata["capture"]["errors"] = capture_result["errors"]

    metadata_path = plan["runDir"] / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    # Run the metadata-first XD export workflow from input URL to output files.
    args = parse_args()
    output_root = Path(args.output_root)
    root_dir = Path.cwd()
    input_url = args.url
    try:
        scale_values = parse_scale_list(args.scales)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.pages and args.all:
        raise RuntimeError("Use either --pages or --all, not both.")

    with sync_playwright() as p:
        browser = launch_capture_browser(p)
        try:
            page = browser.new_page(viewport={"width": args.browser_width, "height": args.browser_height})
            try:
                metadata_source = read_xd_metadata(page, input_url, 0)
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
            if not artboards:
                raise RuntimeError("Unable to find any artboards in window.prototypeData.")

            project_title = (
                manifest.get("name")
                or extract_meta_content(html_text, "property", "og:title")
                or extract_meta_content(html_text, "name", "twitter:title")
                or extract_document_title(html_text)
                or "xd-project"
            )
            modified_date = prototype_data.get("modifiedDate")
            version_tag = version_tag_from_modified_date(modified_date)
            target_page_indexes = parse_page_selector(args.pages, screen_count)

            version_dir = build_version_dir(output_root, project_title, version_tag)
            version_dir.mkdir(parents=True, exist_ok=True)
            xd_metadata_path = version_dir / "xd-metadata.json"
            xd_metadata_path.write_text(
                json.dumps(prototype_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            page_plans: list[dict[str, Any]] = []
            exports: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for screen_index in target_page_indexes:
                artboard = artboards[screen_index - 1]
                try:
                    page_plans.append(
                        build_page_export_plan(
                            version_dir=version_dir,
                            artboard=artboard,
                            screen_index=screen_index,
                            screen_count=screen_count,
                            project_title=project_title,
                            modified_date=modified_date,
                            root_dir=root_dir,
                            view_base_url=view_base_url,
                        )
                    )
                except Exception as exc:
                    errors.append(
                        {
                            "screenIndex": screen_index,
                            "screenId": artboard.get("id"),
                            "screenTitle": artboard.get("name"),
                            "stage": "planning",
                            "error": {"type": exc.__class__.__name__, "message": str(exc)},
                        }
                    )
        finally:
            browser.close()

    capture_by_page, capture_errors, parallel_used = capture_selected_scales(
        scale_values=scale_values,
        page_plans=page_plans,
        wait_ms=args.wait_ms,
        post_zoom_wait_ms=args.post_zoom_wait_ms,
        parallel=args.parallel,
    )
    errors.extend(capture_errors)

    for plan in page_plans:
        try:
            capture_result = capture_by_page[plan["screenIndex"]]
            missing_scales = [
                scale_key(scale)
                for scale in scale_values
                if scale_key(scale) not in capture_result.get("files", {})
            ]
            if missing_scales or capture_result.get("errors"):
                if missing_scales:
                    errors.append(
                        {
                            "screenIndex": plan["screenIndex"],
                            "screenId": plan["screenId"],
                            "screenTitle": plan["screenTitle"],
                            "stage": "capture",
                            "error": {
                                "type": "MissingScaleOutput",
                                "message": f"Missing requested scale outputs: {', '.join(missing_scales)}",
                            },
                        }
                    )
                plan["workDir"].mkdir(parents=True, exist_ok=True)
                (plan["workDir"] / "capture-errors.json").write_text(
                    json.dumps(capture_result.get("errors", []), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                continue

            plan["runDir"] = commit_page_work_dir(plan["workDir"], plan["baseDir"], scale_values)
            capture_result["files"] = {
                key: str(plan["runDir"] / Path(path).name)
                for key, path in capture_result.get("files", {}).items()
            }
            metadata = write_page_metadata(
                plan=plan,
                capture_result=capture_result,
                version_dir=version_dir,
                xd_metadata_path=xd_metadata_path,
                root_dir=root_dir,
            )
            update_pages_index(
                pages_index_path=version_dir / "pages.json",
                prototype_data=prototype_data,
                version_dir=version_dir,
                run_dir=plan["runDir"],
                current_page_source=plan["source"],
                project_title=project_title,
                modified_date=modified_date,
                version_tag=version_tag,
                root_dir=root_dir,
                exported_at=datetime.now().isoformat(timespec="seconds"),
                view_base_url=view_base_url,
            )
            exports.append(metadata)
        except Exception as exc:
            errors.append(
                {
                    "screenIndex": plan["screenIndex"],
                    "screenId": plan["screenId"],
                    "screenTitle": plan["screenTitle"],
                    "stage": "metadata",
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                }
            )

    if len(exports) == 1 and not errors:
        print(json.dumps(exports[0], ensure_ascii=False, indent=2))
    else:
        summary = {
            "project": {
                "projectTitle": project_title,
                "modifiedDate": modified_date,
                "versionTag": version_tag,
                "screenCount": screen_count,
                "url": build_grid_url(view_base_url),
                "versionDirectory": relative_path_str(version_dir, root_dir),
                "xdMetadataFile": relative_path_str(xd_metadata_path, root_dir),
            },
            "selection": {
                "pages": target_page_indexes,
                "all": args.pages is None,
                "scales": [scale_key(scale) for scale in scale_values],
                "parallel": parallel_used,
            },
            "exports": exports,
            "errors": errors,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
