# DeviceBezels Catalog Tools

This repository now includes a tiny Python utility that walks through the `bezels/`
directory and emits a JSON catalog describing every device, category, and asset file.

## Python environment

1. Create a virtual environment (Python 3.10+):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install the local package in editable mode so the CLI works:
   ```bash
   pip install -r requirements.txt
   ```

## Generate the catalog

```bash
python -m devicebezels.catalog --pretty
```

Arguments (all optional):

- `--devices-root`: location of the device folders (defaults to `bezels/devices`)
- `--output`: JSON destination (defaults to `bezels/catalog.json`)
- `--repo-root`: force the root that relative paths are built from
- `--pretty`: add indentation to the resulting JSON

### Catalog schema

The generated JSON is intentionally flat to simplify syncing with GitHub and
ingesting the catalog elsewhere:

```json
{
  "generated_at": "ISO-8601 timestamp",
  "files_count": 123,
  "files": [
    {
      "category": "Phones",
      "name": "Apple iPhone 13 Pro",
      "has_shadow": true,
      "slug": "apple-iphone-13-pro-iphone-13-pro-sierra-blue-shadow",
      "relative_path": "bezels/devices/Phones/Apple iPhone 13 Pro/Device With Shadow/...",
      "image_dimensions": { "width": 2000, "height": 4000 },
      "viewport_dimensions": { "width": 1290, "height": 2796 },
      "viewport_origin": { "x": 355, "y": 420 },
      "size_bytes": 123456
    }
  ]
}
```

Only `.png` files are cataloged (Sketch sources are ignored), which keeps the
focus solely on renderable bezels.

### Viewport extraction

To auto-match bezels to screenshots _and_ position the screenshot correctly even
when there is a notch/camera cut-out, the generator inspects the alpha channel
for each PNG:

1. Load the PNG via Pillow (`RGBA`) and build two masks:
   - the **transparent mask** marks pixels with alpha ≤ 10 (potential viewport)
   - the **solid mask** marks pixels with alpha ≥ 200 (unquestionably bezel)
2. Crop both masks to the solid mask’s bounding box. This strips away any far
   off-canvas padding while keeping every bezel detail.
3. Downscale the transparent mask if it is enormous (max dimension 2000 px) to
   keep the subsequent flood-fill fast while preserving ratios.
4. Flood-fill from every edge pixel to erase the transparent component that is
   connected to the image border (background). The only remaining transparent
   pixels are enclosed “holes” in the bezel — i.e., the viewport (and any notch
   cut-outs).
5. Convert the cleaned mask’s bounding box back into the original coordinates.
   Those coordinates become `viewport_origin` and `viewport_dimensions`.

Because we rely on the actual transparency that designers bake into each bezel,
rectangular screens, rounded corners, pill cut-outs, and irregular notches all
produce accurate viewport metadata. When compositing, place the screenshot at
`viewport_origin`, scale it to `viewport_dimensions`, and then draw the bezel
PNG over the top — the bezel’s opaque pixels naturally occlude any notch areas.

## Shadow filename helper

If you add new assets inside a `Device with Shadow` directory, run:

```bash
python scripts/add_shadow_suffix.py
```

This script scans for every file living under any `Device with Shadow` (case
insensitive) folder and appends `with Shadow` to the filename so the image name
mirrors its directory context. Pass `--dry-run` first if you just want to see
which files would be touched.

## Credits

The bezels included in this catalog originate from:

- [Meta Design Resources](https://design.facebook.com/tools/devices/)
- [Apple Design Resources](https://developer.apple.com/design/resources/)
