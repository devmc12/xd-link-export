#!/usr/bin/env python3
"""Capture native-scale Adobe XD artboard PNGs from a specs page."""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    # Parse command-line options for standalone artboard capture.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Adobe XD screen specs URL")
    parser.add_argument("--output-dir", required=True, help="Folder for artboard PNG outputs")
    parser.add_argument("--design-width", type=int, required=True, help="Artboard design width")
    parser.add_argument("--design-height", type=int, required=True, help="Artboard design height")
    parser.add_argument("--wait-ms", type=int, default=15000, help="Maximum wait for XD UI after navigation")
    parser.add_argument("--post-zoom-wait-ms", type=int, default=200, help="Short settle wait after changing XD zoom")
    parser.add_argument("--scales", default="1", help='Native output scales: "1", "2", "1,2", or "2,1"')
    parser.add_argument(
        "--metadata-file",
        help="Optional JSON file for standalone capture metadata",
    )
    return parser.parse_args()


def parse_scale_list(text: str) -> list[int]:
    # Parse native export scales from a comma-separated string.
    if text is None or not text.strip():
        raise RuntimeError('--scales must be one of: "1", "2", "1,2", or "2,1".')

    values = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            raise RuntimeError('--scales must be one of: "1", "2", "1,2", or "2,1".')
        if chunk not in {"1", "2"}:
            raise RuntimeError('--scales only supports native scales 1 and 2.')
        value = int(chunk)
        if value not in values:
            values.append(value)
    return values


def capture_order(scale_values: list[int]) -> list[int]:
    # Capture larger native scales first because XD downgrades zoom state more reliably than it upgrades it.
    unique_values = []
    for value in scale_values:
        if value not in unique_values:
            unique_values.append(value)
    return sorted(unique_values, reverse=True)


def launch_capture_browser(playwright: Any) -> Any:
    # Launch Chrome when available and fall back to bundled Chromium.
    try:
        return playwright.chromium.launch(channel="chrome", headless=True)
    except Exception:
        pass

    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        raise RuntimeError(
            "Unable to launch a browser for XD export. "
            "Install Google Chrome or run 'python -m playwright install chromium' first."
        ) from exc


def png_size(png_bytes: bytes) -> tuple[int, int]:
    # Read PNG dimensions directly from the IHDR header.
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Captured artboard is not a valid PNG image.")
    width = int.from_bytes(png_bytes[16:20], byteorder="big")
    height = int.from_bytes(png_bytes[20:24], byteorder="big")
    return width, height


def build_candidate_viewports(design_width: int, design_height: int, scale_value: int) -> list[dict[str, int]]:
    # Build orientation-aware viewport candidates for the requested XD zoom scale.
    target_width = design_width * scale_value
    target_height = design_height * scale_value
    is_portrait = design_height >= design_width

    if is_portrait:
        pads = [(1050, 800), (1300, 1050)] if scale_value == 1 else [(700, 350), (950, 600)]
    else:
        pads = [(680, 1280), (930, 1500)] if scale_value == 1 else [(450, 850), (700, 1100)]

    return [
        {
            "width": target_width + width_pad,
            "height": target_height + height_pad,
        }
        for width_pad, height_pad in pads
    ]


def wait_for_capture_ui(page: Any, wait_ms: int) -> None:
    # Wait for the XD specs canvas, zoom input, and artboard overlay to exist.
    timeout_ms = max(wait_ms, 1000)
    page.wait_for_selector("canvas", state="visible", timeout=timeout_ms)
    page.wait_for_selector('[data-auto="zoomInputBox"]', state="visible", timeout=timeout_ms)
    page.wait_for_selector('[data-auto="svgContainer"]', state="attached", timeout=timeout_ms)
    page.wait_for_function(
        """() => {
          const canvas = Array.from(document.querySelectorAll("canvas")).find((node) => {
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && node.width > 0 && node.height > 0;
          });
          const rect = document.querySelector('[data-auto="svgContainer"] svg rect');
          if (!canvas || !rect) return false;
          const bounds = rect.getBoundingClientRect();
          return bounds.width > 0 && bounds.height > 0;
        }""",
        timeout=timeout_ms,
    )


def set_xd_zoom(page: Any, scale_value: int, design_width: int, wait_ms: int) -> None:
    # Set XD's own zoom input to the requested percentage.
    target_value = str(scale_value * 100)
    target_text = f"{target_value}%"
    input_locator = page.locator('[data-auto="zoomInputBox"]')
    current_value = input_locator.input_value()
    if current_value not in {target_value, target_text}:
        input_locator.click()
        input_locator.press("Control+A")
        input_locator.type(target_value)
        input_locator.press("Enter")

    page.wait_for_function(
        """(args) => {
          const input = document.querySelector('[data-auto="zoomInputBox"]');
          const rect = document.querySelector('[data-auto="svgContainer"] svg rect');
          if (!input || !rect) return false;
          const bounds = rect.getBoundingClientRect();
          return (
            (input.value === args.targetValue || input.value === args.targetText) &&
            Math.abs(bounds.width - args.targetWidth) <= 2
          );
        }""",
        arg={
            "targetValue": target_value,
            "targetText": target_text,
            "targetWidth": design_width * scale_value,
        },
        timeout=10000,
    )
    page.wait_for_timeout(wait_ms)


def collect_dom_geometry(page: Any) -> dict[str, Any]:
    # Read canvas and XD overlay rect geometry from the live specs DOM.
    return page.evaluate(
        """
        () => {
          const toRect = (r) => ({
            x: r.x,
            y: r.y,
            width: r.width,
            height: r.height,
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
          });

          const canvases = Array.from(document.querySelectorAll("canvas")).map((node, index) => {
            const rect = node.getBoundingClientRect();
            return {
              index,
              rect: toRect(rect),
              width: node.width,
              height: node.height,
              clientWidth: node.clientWidth,
              clientHeight: node.clientHeight,
            };
          });

          const rects = [];
          Array.from(document.querySelectorAll('[data-auto="svgContainer"]')).forEach((container, containerIndex) => {
            const containerRect = container.getBoundingClientRect();
            container.querySelectorAll("svg rect").forEach((node, rectIndex) => {
              const rect = node.getBoundingClientRect();
              rects.push({
                containerIndex,
                rectIndex,
                rect: toRect(rect),
                containerRect: toRect(containerRect),
                attrX: node.getAttribute("x"),
                attrY: node.getAttribute("y"),
                attrWidth: node.getAttribute("width"),
                attrHeight: node.getAttribute("height"),
                stroke: node.getAttribute("stroke"),
                fill: node.getAttribute("fill"),
              });
            });
          });

          return {
            devicePixelRatio: window.devicePixelRatio || 1,
            zoomValue: document.querySelector('[data-auto="zoomInputBox"]')?.value || null,
            canvases,
            rects,
          };
        }
        """
    )


def choose_canvas(canvases: list[dict[str, Any]]) -> dict[str, Any]:
    # Pick the visible canvas with the largest rendered area.
    visible = [
        canvas
        for canvas in canvases
        if canvas["rect"]["width"] > 0
        and canvas["rect"]["height"] > 0
        and canvas["width"] > 0
        and canvas["height"] > 0
    ]
    if not visible:
        raise RuntimeError("XD viewer canvas was not found.")
    return max(visible, key=lambda item: item["rect"]["width"] * item["rect"]["height"])


def rect_intersection_area(a: dict[str, float], b: dict[str, float]) -> float:
    # Compute overlap area between two rectangles.
    left = max(a["left"], b["left"])
    top = max(a["top"], b["top"])
    right = min(a["right"], b["right"])
    bottom = min(a["bottom"], b["bottom"])
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def choose_rect_candidate(
    rects: list[dict[str, Any]],
    canvas: dict[str, Any],
    design_width: int,
    design_height: int,
) -> dict[str, Any]:
    # Select the overlay rect that best matches the XD artboard.
    if not rects:
        raise RuntimeError("XD artboard overlay rect was not found.")

    design_ratio = design_width / max(design_height, 1)
    canvas_rect = canvas["rect"]
    canvas_area = canvas_rect["width"] * canvas_rect["height"]
    canvas_center_x = canvas_rect["x"] + canvas_rect["width"] / 2
    canvas_center_y = canvas_rect["y"] + canvas_rect["height"] / 2
    scored: list[dict[str, Any]] = []

    for candidate in rects:
        rect = candidate["rect"]
        width = rect["width"]
        height = rect["height"]
        if width <= 0 or height <= 0:
            continue

        rect_area = width * height
        overlap_area = rect_intersection_area(rect, canvas_rect)
        overlap_ratio = overlap_area / rect_area if rect_area else 0.0
        ratio = width / height
        ratio_error = abs(math.log(max(ratio, 1e-9) / design_ratio))
        rect_center_x = rect["x"] + width / 2
        rect_center_y = rect["y"] + height / 2
        center_distance = math.hypot(
            (rect_center_x - canvas_center_x) / max(canvas_rect["width"], 1),
            (rect_center_y - canvas_center_y) / max(canvas_rect["height"], 1),
        )
        area_ratio = rect_area / max(canvas_area, 1.0)
        scored.append(
            {
                **candidate,
                "metrics": {
                    "ratio": ratio,
                    "ratioError": ratio_error,
                    "overlapArea": overlap_area,
                    "overlapRatio": overlap_ratio,
                    "centerDistance": center_distance,
                    "areaRatioVsCanvas": area_ratio,
                },
                "score": (
                    ratio_error,
                    -overlap_ratio,
                    center_distance,
                    -area_ratio,
                ),
            }
        )

    if not scored:
        raise RuntimeError("XD artboard overlay rect was found, but no visible candidate was usable.")
    scored.sort(key=lambda item: item["score"])
    return scored[0]


def projected_raw_size(rect_candidate: dict[str, Any], canvas: dict[str, Any]) -> dict[str, float]:
    # Estimate source pixels available under the selected artboard rect.
    rect = rect_candidate["rect"]
    canvas_rect = canvas["rect"]
    scale_x = canvas["width"] / max(canvas_rect["width"], 1)
    scale_y = canvas["height"] / max(canvas_rect["height"], 1)
    return {
        "width": rect["width"] * scale_x,
        "height": rect["height"] * scale_y,
        "scaleX": scale_x,
        "scaleY": scale_y,
    }


def is_rect_inside_canvas(rect_candidate: dict[str, Any], canvas: dict[str, Any]) -> bool:
    # Check whether the selected artboard rect is fully visible inside the canvas.
    rect = rect_candidate["rect"]
    canvas_rect = canvas["rect"]
    return (
        rect["left"] >= canvas_rect["left"]
        and rect["top"] >= canvas_rect["top"]
        and rect["right"] <= canvas_rect["right"]
        and rect["bottom"] <= canvas_rect["bottom"]
    )


def capture_artboard_png(page: Any, rect_candidate: dict[str, Any], target_width: int, target_height: int) -> bytes:
    # Capture only the artboard display rect and hide XD's overlay stroke first.
    page.evaluate(
        """
        () => {
          document.querySelectorAll('[data-auto="svgContainer"]').forEach((node) => {
            node.style.visibility = "hidden";
          });
        }
        """
    )
    try:
        page.wait_for_timeout(100)

        rect = rect_candidate["rect"]
        scale = target_width / max(rect["width"], 1)
        cdp = page.context.new_cdp_session(page)
        shot = cdp.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {
                    "x": rect["left"],
                    "y": rect["top"],
                    "width": rect["width"],
                    "height": rect["height"],
                    "scale": scale,
                },
                "captureBeyondViewport": True,
                "fromSurface": True,
            },
        )
    finally:
        page.evaluate(
            """
            () => {
              document.querySelectorAll('[data-auto="svgContainer"]').forEach((node) => {
                node.style.visibility = "";
              });
            }
            """
        )

    png_bytes = base64.b64decode(shot["data"])
    actual_width, actual_height = png_size(png_bytes)
    if (actual_width, actual_height) != (target_width, target_height):
        raise RuntimeError(
            f"Captured PNG size {actual_width}x{actual_height} did not match "
            f"target {target_width}x{target_height}."
        )
    return png_bytes


def capture_scale_on_page(
    page: Any,
    output_path: Path,
    design_width: int,
    design_height: int,
    scale_value: int,
    post_zoom_wait_ms: int,
) -> dict[str, Any]:
    # Export one native-scale artboard PNG on an already-loaded XD specs page.
    target_width = design_width * scale_value
    target_height = design_height * scale_value
    attempts: list[dict[str, Any]] = []

    for viewport in build_candidate_viewports(design_width, design_height, scale_value):
        try:
            page.set_viewport_size(viewport)
            page.wait_for_timeout(250)
            set_xd_zoom(page, scale_value, design_width, post_zoom_wait_ms)
            dom_geometry = collect_dom_geometry(page)
            canvas = choose_canvas(dom_geometry["canvases"])
            selected_rect = choose_rect_candidate(
                dom_geometry["rects"],
                canvas,
                design_width,
                design_height,
            )
            raw_size = projected_raw_size(selected_rect, canvas)
            fits = is_rect_inside_canvas(selected_rect, canvas)
            zoom_value = dom_geometry.get("zoomValue")
            target_zoom_values = {str(scale_value * 100), f"{scale_value * 100}%"}
            pass_native = (
                zoom_value in target_zoom_values
                and fits
                and raw_size["width"] >= target_width
                and raw_size["height"] >= target_height
            )
            attempt = {
                "viewport": viewport,
                "zoomValue": zoom_value,
                "fits": fits,
                "projectedRaw": raw_size,
                "targetSize": {"width": target_width, "height": target_height},
                "passNative": pass_native,
            }
            attempts.append(attempt)

            if not pass_native:
                continue

            png_bytes = capture_artboard_png(page, selected_rect, target_width, target_height)
            output_path.write_bytes(png_bytes)
            return {
                "zoomValue": f"{scale_value * 100}%",
                "viewport": viewport,
                "canvas": canvas,
                "selectedRect": selected_rect,
                "projectedRaw": raw_size,
                "targetSize": {"width": target_width, "height": target_height},
                "outputSize": {"width": target_width, "height": target_height},
                "attempts": attempts,
            }
        except Exception as exc:
            attempts.append(
                {
                    "viewport": viewport,
                    "passNative": False,
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                }
            )

    raise RuntimeError(f"Unable to capture native {scale_value}x artboard after {len(attempts)} attempts.")


def capture_scale_output(
    browser: Any,
    capture_url: str,
    output_path: Path,
    design_width: int,
    design_height: int,
    scale_value: int,
    wait_ms: int,
    post_zoom_wait_ms: int,
) -> dict[str, Any]:
    # Export one native-scale artboard PNG through XD zoom and overlay rect geometry.
    initial_viewport = build_candidate_viewports(design_width, design_height, scale_value)[0]
    context = browser.new_context(viewport=initial_viewport, device_scale_factor=1)
    page = context.new_page()
    try:
        page.goto(capture_url, wait_until="domcontentloaded", timeout=max(wait_ms + 5000, 20000))
        wait_for_capture_ui(page, wait_ms)
        return capture_scale_on_page(
            page=page,
            output_path=output_path,
            design_width=design_width,
            design_height=design_height,
            scale_value=scale_value,
            post_zoom_wait_ms=post_zoom_wait_ms,
        )
    finally:
        page.close()
        context.close()


def capture_artboard_scales(
    browser: Any,
    capture_url: str,
    output_dir: Path,
    design_width: int,
    design_height: int,
    scale_values: list[int],
    wait_ms: int,
    post_zoom_wait_ms: int,
) -> dict[str, Any]:
    # Capture each requested native artboard scale in an isolated XD specs page.
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    scales: dict[str, Any] = {}
    ordered_scales = capture_order(scale_values)
    for scale_value in ordered_scales:
        scale_key = f"{scale_value}x"
        output_name = "artboard-1x.png" if scale_value == 1 else f"artboard-{scale_value}x.png"
        output_path = output_dir / output_name
        scales[scale_key] = capture_scale_output(
            browser=browser,
            capture_url=capture_url,
            output_path=output_path,
            design_width=design_width,
            design_height=design_height,
            scale_value=scale_value,
            wait_ms=wait_ms,
            post_zoom_wait_ms=post_zoom_wait_ms,
        )
        files[scale_key] = str(output_path)

    return {
        "strategy": "xd-zoom-svg-rect",
        "files": files,
        "scales": scales,
    }


def main() -> int:
    # Run standalone native artboard capture.
    args = parse_args()
    output_dir = Path(args.output_dir)
    try:
        scale_values = parse_scale_list(args.scales)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    with sync_playwright() as p:
        browser = launch_capture_browser(p)
        try:
            result = capture_artboard_scales(
                browser=browser,
                capture_url=args.url,
                output_dir=output_dir,
                design_width=args.design_width,
                design_height=args.design_height,
                scale_values=scale_values,
                wait_ms=args.wait_ms,
                post_zoom_wait_ms=args.post_zoom_wait_ms,
            )
        finally:
            browser.close()

    payload = {
        "url": args.url,
        "designWidth": args.design_width,
        "designHeight": args.design_height,
        "capture": {
            "strategy": result["strategy"],
            "scales": result["scales"],
        },
        "files": result["files"],
    }
    if args.metadata_file:
        Path(args.metadata_file).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
