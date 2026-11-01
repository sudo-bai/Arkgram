#!/usr/bin/env python3
"""Vectorize a monochrome JPEG icon without hand-authoring its geometry.

Pipeline:
  1. Grayscale + Gaussian smoothing + Otsu threshold.
  2. Keep the largest dark component and fill its interior to recover the disk.
  3. Keep bright details only inside that disk as independent foreground shapes.
  4. Trace both masks with Potrace, combine them into one transparent SVG.
  5. Render an RGBA PNG and verify it against the threshold masks.

The resulting SVG has a transparent exterior, a black vector disk, and white
vector details. No background-colored rectangle is embedded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


PATH_RE = re.compile(r'<path\b[^>]*\bd="([^"]+)"', re.IGNORECASE | re.DOTALL)
GROUP_TRANSFORM_RE = re.compile(
    r'<g\b[^>]*\btransform="([^"]+)"', re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class Parameters:
    blur_sigma: float = 1.5
    min_feature_area: int = 20
    turdsize: int = 5
    alphamax: float = 1.0
    opttolerance: float = 0.2
    potrace_unit: int = 10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mask_to_potrace_pgm(mask: np.ndarray, path: Path) -> None:
    """Write foreground as black (0) and background as white (255)."""
    raster = np.where(mask > 0, 0, 255).astype(np.uint8)
    Image.fromarray(raster, mode="L").save(path)


def trace_mask(
    mask: np.ndarray,
    output_svg: Path,
    work_dir: Path,
    name: str,
    params: Parameters,
) -> tuple[str, str]:
    if shutil.which("potrace") is None:
        raise RuntimeError("potrace is required but was not found on PATH")

    pgm_path = work_dir / f"{name}.pgm"
    mask_to_potrace_pgm(mask, pgm_path)
    command = [
        "potrace",
        str(pgm_path),
        "--svg",
        "--output",
        str(output_svg),
        "--flat",
        "--turdsize",
        str(params.turdsize),
        "--alphamax",
        str(params.alphamax),
        "--opttolerance",
        str(params.opttolerance),
        "--unit",
        str(params.potrace_unit),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    svg_text = output_svg.read_text(encoding="utf-8")
    paths = PATH_RE.findall(svg_text)
    if not paths:
        raise RuntimeError(f"Potrace emitted no path data for {name}")
    transforms = GROUP_TRANSFORM_RE.findall(svg_text)
    transform = transforms[0] if transforms else ""
    path_data = " ".join(" ".join(path.split()) for path in paths)
    return path_data, transform


def render_svg(svg_path: Path, png_path: Path, size: int) -> None:
    if shutil.which("rsvg-convert"):
        subprocess.run(
            [
                "rsvg-convert",
                "-w",
                str(size),
                "-h",
                str(size),
                "-b",
                "transparent",
                str(svg_path),
                "-o",
                str(png_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return
    if shutil.which("magick"):
        subprocess.run(
            [
                "magick",
                "-background",
                "none",
                str(svg_path),
                "-resize",
                f"{size}x{size}",
                str(png_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return
    raise RuntimeError("rsvg-convert or ImageMagick is required to render the SVG")


def mask_iou(actual: np.ndarray, expected: np.ndarray) -> float:
    actual_bool = actual.astype(bool)
    expected_bool = expected.astype(bool)
    union = np.logical_or(actual_bool, expected_bool).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(actual_bool, expected_bool).sum() / union)


def boundary_distance_stats(actual: np.ndarray, expected: np.ndarray) -> dict[str, float]:
    """Measure how far rendered boundaries sit from the thresholded target."""
    actual_u8 = actual.astype(np.uint8)
    expected_u8 = expected.astype(np.uint8)
    actual_boundary = cv2.morphologyEx(
        actual_u8,
        cv2.MORPH_GRADIENT,
        np.ones((3, 3), np.uint8),
        borderType=cv2.BORDER_REPLICATE,
    )
    expected_boundary = cv2.morphologyEx(
        expected_u8,
        cv2.MORPH_GRADIENT,
        np.ones((3, 3), np.uint8),
        borderType=cv2.BORDER_REPLICATE,
    )
    # distanceTransform gives the distance to the nearest zero pixel.
    distance_to_expected = cv2.distanceTransform(
        1 - expected_boundary, cv2.DIST_L2, 5
    )
    distances = distance_to_expected[actual_boundary > 0]
    if distances.size == 0:
        return {"mean_px": 0.0, "p95_px": 0.0, "max_px": 0.0}
    return {
        "mean_px": float(distances.mean()),
        "p95_px": float(np.percentile(distances, 95)),
        "max_px": float(distances.max()),
    }


def make_checkerboard_preview(icon: Image.Image, output: Path) -> None:
    size = 64
    tile = 16
    preview = Image.new("RGBA", icon.size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(preview)
    light = (236, 238, 241, 255)
    dark = (204, 208, 214, 255)
    for y in range(0, size, tile):
        for x in range(0, size, tile):
            color = light if ((x // tile) + (y // tile)) % 2 == 0 else dark
            draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=color)
    preview.alpha_composite(icon)
    preview.save(output)


def vectorize(
    input_path: Path,
    output_dir: Path,
    params: Parameters,
    render_size: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    source = Image.open(input_path).convert("L")
    gray = np.asarray(source, dtype=np.uint8)
    smooth = cv2.GaussianBlur(gray, (0, 0), params.blur_sigma)
    otsu_threshold, thresholded = cv2.threshold(
        smooth, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    dark = (thresholded == 0).astype(np.uint8)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    if component_count <= 1:
        raise RuntimeError("No dark foreground component was found")
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    largest_component = (labels == largest_label).astype(np.uint8)

    contours, _ = cv2.findContours(
        largest_component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        raise RuntimeError("The largest dark component has no external contour")
    disk_mask = np.zeros_like(largest_component)
    cv2.drawContours(disk_mask, contours, -1, 1, thickness=cv2.FILLED)

    bright = ((thresholded == 255) & (disk_mask > 0)).astype(np.uint8)
    white_count, white_labels, white_stats, _ = cv2.connectedComponentsWithStats(
        bright, 8
    )
    white_mask = np.zeros_like(bright)
    kept_white_areas: list[int] = []
    rejected_white_areas: list[int] = []
    for label in range(1, white_count):
        area = int(white_stats[label, cv2.CC_STAT_AREA])
        if area >= params.min_feature_area:
            white_mask[white_labels == label] = 1
            kept_white_areas.append(area)
        else:
            rejected_white_areas.append(area)

    if not kept_white_areas:
        raise RuntimeError("No white foreground details survived noise filtering")

    with tempfile.TemporaryDirectory(prefix="arkgram-vectorize-") as temp_name:
        work_dir = Path(temp_name)
        disk_svg = work_dir / "disk.svg"
        white_svg = work_dir / "white.svg"
        disk_d, disk_transform = trace_mask(
            disk_mask, disk_svg, work_dir, "disk", params
        )
        white_d, white_transform = trace_mask(
            white_mask, white_svg, work_dir, "white", params
        )

    transform = disk_transform or white_transform
    transform_attr = f' transform="{transform}"' if transform else ""
    svg_path = output_dir / "arkgram_icon.svg"
    svg_text = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="2048" height="2048" viewBox="0 0 2048 2048" preserveAspectRatio="xMidYMid meet" shape-rendering="geometricPrecision">
  <title>Arkgram icon</title>
  <desc>Transparent-background vector conversion of the supplied monochrome Arkgram icon.</desc>
  <g{transform_attr} fill-rule="evenodd" clip-rule="evenodd">
    <path id="black-disk" fill="#000000" d="{disk_d}"/>
    <path id="white-details" fill="#FFFFFF" d="{white_d}"/>
  </g>
</svg>
'''
    svg_path.write_text(svg_text, encoding="utf-8")

    png_path = output_dir / f"arkgram_icon_{render_size}.png"
    render_svg(svg_path, png_path, render_size)

    rendered = Image.open(png_path).convert("RGBA")
    rendered.save(png_path, format="PNG", optimize=True, dpi=(300, 300))
    rendered = Image.open(png_path).convert("RGBA")
    rgba = np.asarray(rendered, dtype=np.uint8)
    alpha = rgba[:, :, 3]
    opaque = alpha > 127

    if render_size == gray.shape[0] and render_size == gray.shape[1]:
        white_render = opaque & (rgba[:, :, 0] > 127)
        black_render = opaque & (rgba[:, :, 0] <= 127)
        black_expected = disk_mask.astype(bool) & ~white_mask.astype(bool)
        white_expected = white_mask.astype(bool)
        disc_iou = mask_iou(opaque, disk_mask.astype(bool))
        white_iou = mask_iou(white_render, white_expected)
        black_iou = mask_iou(black_render, black_expected)
        white_boundary_distance = boundary_distance_stats(
            white_render, white_expected
        )
    else:
        disc_iou = white_iou = black_iou = None
        white_boundary_distance = None

    outside_disk = disk_mask == 0
    outside_alpha_nonzero = int(np.count_nonzero(alpha[outside_disk]))
    dilated_disk = cv2.dilate(
        disk_mask.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1
    )
    outside_dilated_disk = dilated_disk == 0
    outside_dilated_alpha_nonzero = int(
        np.count_nonzero(alpha[outside_dilated_disk])
    )
    fully_transparent_fraction = float(np.mean(alpha == 0))
    corners = [rgba[0, 0, 3], rgba[0, -1, 3], rgba[-1, 0, 3], rgba[-1, -1, 3]]

    mask_path = output_dir / "arkgram_icon_black_mask.png"
    Image.fromarray((disk_mask * 255).astype(np.uint8), mode="L").save(mask_path)
    preview_path = output_dir / "arkgram_icon_preview_checkerboard.png"
    make_checkerboard_preview(rendered, preview_path)

    report: dict[str, object] = {
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "source_size": [int(source.width), int(source.height)],
        "parameters": asdict(params),
        "otsu_threshold": float(otsu_threshold),
        "dark_component_count": int(component_count - 1),
        "largest_dark_component_area_px": int(
            stats[largest_label, cv2.CC_STAT_AREA]
        ),
        "disk_area_px": int(np.count_nonzero(disk_mask)),
        "white_component_count_kept": len(kept_white_areas),
        "white_component_areas_px": sorted(kept_white_areas, reverse=True),
        "white_component_areas_rejected_px": sorted(
            rejected_white_areas, reverse=True
        ),
        "white_area_px": int(np.count_nonzero(white_mask)),
        "outputs": {
            "svg": str(svg_path),
            "png": str(png_path),
            "mask": str(mask_path),
            "checkerboard_preview": str(preview_path),
        },
        "svg_sha256": sha256(svg_path),
        "png_sha256": sha256(png_path),
        "render_size": [int(rendered.width), int(rendered.height)],
        "validation": {
            "disk_iou_at_render_size": disc_iou,
            "white_iou_at_render_size": white_iou,
            "black_iou_at_render_size": black_iou,
            "white_boundary_distance_px": white_boundary_distance,
            "alpha_nonzero_outside_disk_px": outside_alpha_nonzero,
            "alpha_nonzero_outside_disk_plus_2px_px": outside_dilated_alpha_nonzero,
            "fully_transparent_pixel_fraction": fully_transparent_fraction,
            "corner_alpha_values": [int(value) for value in corners],
        },
    }
    report_path = output_dir / "vectorization_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input JPEG/PNG icon")
    parser.add_argument("output_dir", type=Path, help="Directory for generated files")
    parser.add_argument("--blur-sigma", type=float, default=1.5)
    parser.add_argument("--min-feature-area", type=int, default=20)
    parser.add_argument("--turdsize", type=int, default=5)
    parser.add_argument("--alphamax", type=float, default=1.0)
    parser.add_argument("--opttolerance", type=float, default=0.2)
    parser.add_argument("--potrace-unit", type=int, default=10)
    parser.add_argument("--render-size", type=int, default=2048)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    params = Parameters(
        blur_sigma=args.blur_sigma,
        min_feature_area=args.min_feature_area,
        turdsize=args.turdsize,
        alphamax=args.alphamax,
        opttolerance=args.opttolerance,
        potrace_unit=args.potrace_unit,
    )
    report = vectorize(args.input.expanduser(), args.output_dir, params, args.render_size)
    validation = report["validation"]
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
