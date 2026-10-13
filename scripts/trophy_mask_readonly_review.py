from pathlib import Path
import json
import sqlite3
import sys

from PIL import Image, ImageDraw, ImageFont

DATA = Path(r"D:/image-editor-development/mixed-input-preview-data")
OUT = Path(r"D:/image-editor-experiments/trophy-mask-review")
OUT.mkdir(parents=True, exist_ok=True)
DRAFT_PREFIX = "2fba2af"
SOURCE_PREFIX = "54c46a"
MASK_PREFIX = "c64c05"

con = sqlite3.connect((DATA / "editor.sqlite").as_uri() + "?mode=ro", uri=True)
con.row_factory = sqlite3.Row
row = con.execute("select state from drafts where id like ?", (DRAFT_PREFIX + "%",)).fetchone()
assert row, "draft not found"
state = json.loads(row["state"])
mapping = next(m for m in state["mappings"] if (m.get("source") or {}).get("image_id", "").startswith(SOURCE_PREFIX))
source_id = mapping["source"]["image_id"]
mask_id = mapping["source"]["mask_id"]
assert mask_id.startswith(MASK_PREFIX)

def meta(asset_id):
    value = con.execute("select meta from assets where id=?", (asset_id,)).fetchone()
    assert value, asset_id
    return json.loads(value["meta"])

source_meta, mask_meta = meta(source_id), meta(mask_id)
source = Image.open(DATA / source_meta["path"]).convert("RGB")
mask_rgba = Image.open(DATA / mask_meta["path"]).convert("RGBA")
alpha = mask_rgba.getchannel("A")
origin_box = mask_meta["origin"]["box"]
mask_bbox = mask_meta["bbox"]
w, h = source.size
box_px = [round(origin_box[0] * w), round(origin_box[1] * h), round(origin_box[2] * w), round(origin_box[3] * h)]
bbox_px = [round(mask_bbox[0] * w), round(mask_bbox[1] * h), round(mask_bbox[2] * w), round(mask_bbox[3] * h)]

# This reproduces the current focus visualization only; it does not alter persisted data.
softened = Image.blend(source, Image.new("RGB", source.size, (235, 235, 235)), 0.72)
focused = Image.composite(source, softened, alpha)
margin_x = (mask_bbox[2] - mask_bbox[0]) * 0.08
margin_y = (mask_bbox[3] - mask_bbox[1]) * 0.08
crop_px = [
    max(0, int((mask_bbox[0] - margin_x) * w)),
    max(0, int((mask_bbox[1] - margin_y) * h)),
    min(w, int((mask_bbox[2] + margin_x) * w + 1)),
    min(h, int((mask_bbox[3] + margin_y) * h + 1)),
]
actual_crop = focused.crop(crop_px)

# Composite mask in magenta, and draw only the persisted origin box.
overlay = source.convert("RGBA")
color = Image.new("RGBA", source.size, (255, 0, 170, 0))
color.putalpha(alpha.point(lambda p: min(180, p)))
overlay = Image.alpha_composite(overlay, color)
draw = ImageDraw.Draw(overlay)
draw.rectangle(box_px, outline=(0, 220, 255, 255), width=6)
draw.rectangle(bbox_px, outline=(255, 215, 0, 255), width=4)

source.save(OUT / "01-original.png")
overlay.convert("RGB").save(OUT / "02-origin-box-and-mask-overlay.png")
alpha.save(OUT / "03-mask-alpha.png")
actual_crop.save(OUT / "04-actual-focus-crop.png")

# Build a readable side-by-side contact sheet.
def fit(im, width=420, height=520):
    out = im.copy(); out.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(out, ((width-out.width)//2, (height-out.height)//2))
    return canvas

panels = [
    ("Original", source),
    ("Persisted origin box + mask", overlay.convert("RGB")),
    ("Stored mask alpha", Image.merge("RGB", (alpha, alpha, alpha))),
    ("Actual focus crop", actual_crop),
]
sheet = Image.new("RGB", (840, 1120), "white")
d = ImageDraw.Draw(sheet)
for i, (title, im) in enumerate(panels):
    x = (i % 2) * 420; y = (i // 2) * 560
    sheet.paste(fit(im), (x, y + 28)); d.text((x + 10, y + 7), title, fill="black")
sheet.save(OUT / "00-comparison.png")

# Quantify whether mask alpha exists in the persisted box margins that users identified visually.
regions = {
    "left_box_margin": [box_px[0], box_px[1], bbox_px[0], box_px[3]],
    "bottom_box_margin": [box_px[0], bbox_px[3], box_px[2], box_px[3]],
}
stats = {}
for name, rect in regions.items():
    crop = alpha.crop(rect)
    hist = crop.histogram()
    total = crop.width * crop.height
    nonzero = total - hist[0] if total else 0
    stats[name] = {"pixels": total, "nonzero_mask_pixels": nonzero, "nonzero_fraction": round(nonzero / total, 8) if total else None}

report = {
    "read_only": True,
    "draft_id": state["id"],
    "draft_revision": state["revision"],
    "mapping_display_index": mapping["display_index"],
    "source": {"id": source_id, "size": [w, h], "label": mapping["source"].get("label"), "label_source": mapping["source"].get("label_source")},
    "mask": {"id": mask_id, "method": mask_meta["origin"]["method"], "score": mask_meta["origin"].get("score"), "origin_box": origin_box, "origin_box_pixels": box_px, "mask_bbox": mask_bbox, "mask_bbox_pixels": bbox_px},
    "focus": {"enabled_in_draft": mapping.get("subject_focus") is True, "outside_blend": 0.72, "original_retained_outside_mask": 0.28, "actual_crop_pixels": crop_px},
    "box_margin_mask_stats": stats,
    "gemini_provenance": {"confirmed": False, "reason": "Recognition cache is process-memory only and the live endpoint now returns idle; persisted mask metadata records SlimSAM box input but not the upstream Gemini response/model."},
    "files": ["00-comparison.png", "01-original.png", "02-origin-box-and-mask-overlay.png", "03-mask-alpha.png", "04-actual-focus-crop.png"],
}
(OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
