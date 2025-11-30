from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None  # allow very high resolution assets without warnings

SHADOW_DIR_NAMES = {"device with shadow", "device with shadows"}
ALPHA_THRESHOLD = 10  # pixels <= this alpha are considered transparent viewport
SOLID_ALPHA_THRESHOLD = 200  # pixels >= this alpha are considered solid bezel
MAX_MASK_DIMENSION = 2000  # downscale masks larger than this to keep flood fill fast


def slugify(value: str) -> str:
    """Convert a string into a filesystem/URL safe slug."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "unknown"


def path_has_shadow(path: Path) -> bool:
    """True if any path segment indicates the asset includes shadows."""
    return any(part.lower() in SHADOW_DIR_NAMES for part in path.parts)


def relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def iter_device_pngs(devices_root: Path) -> Iterable[Tuple[str, str, Path]]:
    """Yield (category, device name, file path) for every PNG file."""
    for category_dir in sorted(p for p in devices_root.iterdir() if p.is_dir()):
        category = category_dir.name
        for device_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            device_name = device_dir.name
            for file_path in sorted(device_dir.rglob("*.png")):
                if file_path.is_file() and file_path.suffix.lower() == ".png":
                    yield category, device_name, file_path


def compute_viewport(image: Image.Image) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Determine the viewport origin and size by looking at near-transparent pixels.
    The algorithm strips away any transparent padding that touches the outer edge
    so only the enclosed screen aperture remains.
    """
    if "A" not in image.getbands():
        width, height = image.size
        return (0, 0), (width, height)

    alpha = image.getchannel("A")
    transparent_mask = alpha.point(lambda value: 255 if value <= ALPHA_THRESHOLD else 0)
    solid_mask = alpha.point(lambda value: 255 if value >= SOLID_ALPHA_THRESHOLD else 0)

    device_bbox = solid_mask.getbbox() or alpha.getbbox()
    if device_bbox is None:
        return (0, 0), (image.width, image.height)

    cropped_mask = transparent_mask.crop(device_bbox)
    crop_width, crop_height = cropped_mask.size

    scale = 1.0
    max_dim = max(crop_width, crop_height)
    if max_dim > MAX_MASK_DIMENSION:
        scale = MAX_MASK_DIMENSION / max_dim
        new_size = (
            max(1, int(math.ceil(crop_width * scale))),
            max(1, int(math.ceil(crop_height * scale))),
        )
        scaled_mask = cropped_mask.resize(new_size, resample=Image.NEAREST)
    else:
        scaled_mask = cropped_mask

    width, height = scaled_mask.size
    pixels = scaled_mask.load()

    def flood_if_transparent(x: int, y: int) -> None:
        if pixels[x, y] == 255:
            ImageDraw.floodfill(scaled_mask, (x, y), 0, thresh=0)

    for x in range(width):
        flood_if_transparent(x, 0)
        flood_if_transparent(x, height - 1)
    for y in range(height):
        flood_if_transparent(0, y)
        flood_if_transparent(width - 1, y)

    viewport_bbox = scaled_mask.getbbox()
    if viewport_bbox is None:
        return (0, 0), (image.width, image.height)

    inverse_scale = 1.0 if scale == 1.0 else 1.0 / scale
    left = device_bbox[0] + int(round(viewport_bbox[0] * inverse_scale))
    top = device_bbox[1] + int(round(viewport_bbox[1] * inverse_scale))
    right = device_bbox[0] + int(round(viewport_bbox[2] * inverse_scale))
    bottom = device_bbox[1] + int(round(viewport_bbox[3] * inverse_scale))

    viewport_width = right - left
    viewport_height = bottom - top
    return (left, top), (viewport_width, viewport_height)


def describe_png(category: str, device_name: str, path: Path, repo_root: Path) -> Dict[str, object]:
    """Return the flattened metadata for a single PNG asset."""
    stat = path.stat()
    with Image.open(path) as image:
        width, height = image.size
        viewport_origin, viewport_size = compute_viewport(image.convert("RGBA"))

    rel_path = relative_path(path, repo_root)
    slug = slugify(f"{device_name}-{path.stem}")

    return {
        "category": category,
        "name": device_name,
        "has_shadow": path_has_shadow(path.parent),
        "slug": slug,
        "relative_path": rel_path,
        "image_dimensions": {"width": width, "height": height},
        "viewport_dimensions": {"width": viewport_size[0], "height": viewport_size[1]},
        "viewport_origin": {"x": viewport_origin[0], "y": viewport_origin[1]},
        "size_bytes": stat.st_size,
    }


def build_catalog(devices_root: Path, repo_root: Path) -> Dict[str, object]:
    """Generate the flattened catalog with metadata for every PNG asset."""
    if not devices_root.exists():
        raise FileNotFoundError(f"Could not find devices root: {devices_root}")

    files: List[Dict[str, object]] = []
    for category, device_name, file_path in iter_device_pngs(devices_root):
        files.append(describe_png(category, device_name, file_path, repo_root))

    files.sort(key=lambda entry: (entry["category"], entry["name"], entry["relative_path"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_count": len(files),
        "files": files,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a JSON catalog describing every bezel asset."
    )
    parser.add_argument(
        "--devices-root",
        default="bezels/devices",
        help="Path to the directory that contains the device categories (default: %(default)s).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root used to build relative paths (defaults to the project root).",
    )
    parser.add_argument(
        "--output",
        default="bezels/catalog.json",
        help="Where to write the generated JSON catalog (default: %(default)s).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty print the JSON output with indentation.",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    devices_root = Path(args.devices_root).expanduser()
    if not devices_root.is_absolute():
        devices_root = (repo_root / devices_root).resolve()

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (repo_root / output_path).resolve()

    catalog = build_catalog(devices_root, repo_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2 if args.pretty else None)
        handle.write("\n")

    try:
        display_path = output_path.relative_to(repo_root).as_posix()
    except ValueError:
        display_path = str(output_path)

    print(f"Wrote catalog with {catalog['files_count']} files to {display_path}")


if __name__ == "__main__":
    main()
