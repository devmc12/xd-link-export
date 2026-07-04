#!/usr/bin/env python3
"""Crop an XD artboard from a viewer canvas screenshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    # Parse command-line options for the crop helper.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Canvas screenshot path")
    parser.add_argument("--output-dir", required=True, help="Directory for cropped outputs")
    parser.add_argument("--design-width", type=int, required=True, help="XD design width")
    parser.add_argument("--design-height", type=int, required=True, help="XD design height")
    parser.add_argument("--white-threshold", type=int, default=248, help="RGB threshold treated as blank viewer area")
    parser.add_argument("--min-row-coverage", type=float, default=0.03, help="Minimum non-blank row/column coverage")
    parser.add_argument("--lock-design-ratio", action="store_true", help="Infer full crop height from the design ratio")
    parser.add_argument("--min-leading-span", type=int, default=20, help="Ignore very short leading row spans as noise")
    parser.add_argument("--export-scales", default="1,2", help="Comma-separated normalized scales to export")
    parser.add_argument("--save-raw", action="store_true", help="Also write the uncropped-resolution artboard image for debugging")
    return parser.parse_args()


def is_non_blank(rgb: tuple[int, int, int], threshold: int) -> bool:
    # Decide whether a pixel should count as artboard content.
    red, green, blue = rgb
    return not (red >= threshold and green >= threshold and blue >= threshold)


def longest_consecutive_span(indices: list[int]) -> tuple[int, int]:
    # Find the longest continuous span in a sorted index list.
    best_start = indices[0]
    best_end = indices[0]
    start = indices[0]
    end = indices[0]

    for index in indices[1:]:
        if index == end + 1:
            end = index
            continue
        if end - start > best_end - best_start:
            best_start, best_end = start, end
        start = end = index

    if end - start > best_end - best_start:
        best_start, best_end = start, end
    return best_start, best_end


def consecutive_spans(indices: list[int]) -> list[tuple[int, int, int]]:
    # Split a sorted index list into continuous spans with lengths.
    spans: list[tuple[int, int, int]] = []
    start = indices[0]
    end = indices[0]
    for index in indices[1:]:
        if index == end + 1:
            end = index
            continue
        spans.append((start, end, end - start + 1))
        start = end = index
    spans.append((start, end, end - start + 1))
    return spans


def detect_bbox(
    image: Image.Image,
    threshold: int,
    min_row_coverage: float,
    lock_design_ratio: bool,
    design_width: int,
    design_height: int,
    min_leading_span: int,
) -> tuple[int, int, int, int]:
    # Detect the artboard bounding box inside a viewer screenshot.
    width, height = image.size
    pixels = image.load()

    row_hits: list[int] = []
    for y in range(height):
        count = 0
        for x in range(width):
            if is_non_blank(pixels[x, y], threshold):
                count += 1
        row_hits.append(count)

    col_hits: list[int] = []
    for x in range(width):
        count = 0
        for y in range(height):
            if is_non_blank(pixels[x, y], threshold):
                count += 1
        col_hits.append(count)

    valid_rows = [index for index, count in enumerate(row_hits) if count > width * min_row_coverage]
    valid_cols = [index for index, count in enumerate(col_hits) if count > height * min_row_coverage]
    if not valid_rows or not valid_cols:
        raise RuntimeError("Unable to detect a non-blank artboard region.")

    left, right = longest_consecutive_span(valid_cols)
    row_spans = consecutive_spans(valid_rows)
    leading_span = next((span for span in row_spans if span[2] >= min_leading_span), row_spans[0])
    top = leading_span[0]

    if lock_design_ratio:
        detected_width = right - left + 1
        expected_height = round(detected_width * design_height / design_width)
        bottom = min(height - 1, top + expected_height - 1)
    else:
        bottom = max(valid_rows)
    return (left, top, right, bottom)


def parse_scales(scales_text: str) -> list[int]:
    # Parse normalized export scales from a comma-separated string.
    output: list[int] = []
    for chunk in scales_text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        output.append(int(chunk))
    if not output:
        raise ValueError("At least one export scale is required.")
    return output


def main() -> int:
    # Run the crop helper from input image to normalized outputs.
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(input_path).convert("RGB")
    left, top, right, bottom = detect_bbox(
        image=image,
        threshold=args.white_threshold,
        min_row_coverage=args.min_row_coverage,
        lock_design_ratio=args.lock_design_ratio,
        design_width=args.design_width,
        design_height=args.design_height,
        min_leading_span=args.min_leading_span,
    )
    cropped = image.crop((left, top, right + 1, bottom + 1))

    scales = parse_scales(args.export_scales)
    normalized_outputs: dict[str, str] = {}
    raw_path: Path | None = None
    if args.save_raw:
        raw_path = output_dir / "artboard-raw.png"
        cropped.save(raw_path)
    for scale in scales:
        target = (
            args.design_width * scale,
            args.design_height * scale,
        )
        normalized = cropped.resize(target, resample=Image.Resampling.LANCZOS)
        if scale == 1:
            output_path = output_dir / "artboard-1x.png"
        else:
            output_path = output_dir / f"artboard-{scale}x.png"
        normalized.save(output_path)
        normalized_outputs[f"{scale}x"] = str(output_path)

    payload = {
        "input": str(input_path),
        "inputSize": {"width": image.width, "height": image.height},
        "designSize": {"width": args.design_width, "height": args.design_height},
        "bbox": {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": cropped.width,
            "height": cropped.height,
        },
        "whiteThreshold": args.white_threshold,
        "minRowCoverage": args.min_row_coverage,
        "lockDesignRatio": args.lock_design_ratio,
        "minLeadingSpan": args.min_leading_span,
        "outputs": (
            {"raw": str(raw_path), **normalized_outputs}
            if raw_path is not None
            else normalized_outputs
        ),
    }
    (output_dir / "artboard-crop.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
