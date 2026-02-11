# Desktop Vision Model for Screenshot Classification — Revised Solution

*Major revision: upgrades primary model from Qwen2.5-VL-72B (year-old) to Qwen3-VL-32B
(released Sep-Oct 2025), adds GLM-OCR as secondary OCR specialist, updates pixel budget
math for Qwen3-VL's 32-multiple rounding, and incorporates zoom-in tool pathway.*

## PLAN

### 1. Model Stack (Revised)

The previous consensus on Qwen2.5-VL-72B was reasonable for early 2025 but is outdated
as of February 2026. Two important shifts occurred:

#### Primary: Qwen3-VL-32B Instruct

Available on Ollama as `qwen3-vl:32b`. Apache-2.0 license.

- **Direct successor** to the Qwen2.5-VL line, released Sep-Oct 2025.
- **Explicit upgrades** for GUI understanding, OCR, and spatial awareness.
- **256K native context window** — dramatically larger than Qwen2.5-VL's 32K-128K,
  enabling more visual tokens and longer text extraction without truncation.
- **Dimension rounding to multiples of 32** (not 28 as in Qwen2.5-VL). This matters
  for tile sizing and coordinate mapping between crops and the original screenshot.
- **"Think with images" paradigm** with tool calling, including an `image_zoom_in_tool`
  that takes `(image_index, [x1, y1, x2, y2])` for on-demand region zoom. This enables
  a future upgrade path from deterministic tiling to hybrid "coverage + zoom."
- **32B fits easily on 96 GB VRAM** — even at Q8_0 (~34 GB weights), leaving ~62 GB for
  KV cache, visual tokens, and overhead. Q4_K_M (~19 GB) is also viable for faster
  throughput if quality is sufficient.

**Why 32B and not the 235B variant?** The 235B (MoE) is too large for comfortable single-GPU
use on 96 GB. For frequent screenshot summarization, throughput and stability matter more
than marginal benchmark gains. The 32B is the practical sweet spot.

**What practitioners report:** Strong OCR/captioning performance, but accuracy depends on
correct image resizing and coordinate conventions in local runtimes. Users experimenting
with the zoom-in tool report large accuracy improvements on fine details versus one-shot
full-image inference.

#### Secondary OCR Specialist: GLM-OCR

Available on Ollama as `glm-ocr`. Apache-2.0 license. ~0.9B parameters.

- **Purpose-built for document OCR** with an architecture using layout analysis +
  parallel recognition — directly relevant to screenshots (which are functionally
  documents with UI chrome).
- **Top score on OmniDocBench v1.5** for real-world document understanding.
- **Tiny footprint** (~0.9B params, <1 GB VRAM) — runs alongside Qwen3-VL with
  negligible resource impact.
- **Use case:** Run on the same window crops as Qwen3-VL. If Qwen3-VL claims a text
  block that GLM-OCR does not find, mark it as low confidence. This cross-check directly
  attacks the hallucination failure mode.

This hybrid is not scope-creep — it directly addresses the user's core failure mode
(text illegible → hallucination) by separating "what is on screen" (Qwen3-VL) from
"what does the text say" (GLM-OCR).

#### Alternatives Worth Knowing

- **Llama 4 Scout:** Available on Ollama, strong DocVQA/ChartQA results, natively
  multimodal MoE. Not the top pick due to licensing complexity (vs Apache-2.0) and
  less screenshot/OCR-centric workflow tooling than Qwen3-VL.
- **DeepSeek-OCR:** OCR-centric VLM on Ollama. Smaller context window and prompt
  sensitivity warnings. Viable as a GLM-OCR alternative if needed.

### 2. Quantization

With Qwen3-VL-32B (much smaller than the old 72B recommendation), the 96 GB GPU has
abundant headroom:

| Quantization | Weights | Remaining VRAM | Recommendation |
|---|---|---|---|
| Q8_0 | ~34 GB | ~62 GB | **Recommended starting point** — quality is near-lossless |
| Q6_K | ~26 GB | ~70 GB | Good balance if Q8 latency is too high |
| Q4_K_M | ~19 GB | ~77 GB | Maximum throughput; test OCR quality first |

With the 32B model, **Q8_0 is now the recommended default** — the previous Q4_K_M
recommendation was driven by the 72B model's size, which is no longer relevant.

GLM-OCR at ~0.9B adds <1 GB regardless of quantization.

### 3. Screenshot Preparation

#### Why the earlier attempt failed

VLM stacks convert pixels into a limited number of visual tokens. If you don't control
that conversion, the stack silently enforces a max pixel budget and downscales.

Concrete example: Qwen2-VL's image processor defaults to `max_pixels = 28 * 28 * 1280`
(~1.0 MP). A 4K screenshot is ~8.3 MP → downscaled ~8x. Qwen3-VL continues the
`min_pixels` / `max_pixels` pattern, and additionally supports explicit `resized_height`
/ `resized_width` (rounded to multiples of 32).

**Critical:** If using `qwen-vl-utils` for resizing, disable resizing in the processor
to avoid double-resizing.

#### Step 0 — Empirical Sanity Check

1. Pull `qwen3-vl:32b` and `glm-ocr`.
2. Capture a 4K screenshot with known small text (12px terminal font).
3. Send to Qwen3-VL via Ollama, ask it to read the small text verbatim.
4. If it reads accurately → the default pixel budget may suffice.
5. If it fails → proceed with the window-aware pipeline below.

#### Phase 1 — Global Layout (low-res, full screenshot)

- Process the full 3840x2160, resized to a modest budget (~1-1.5 MP). You *want*
  resizing here — this pass is for spatial context, not text.
- Prompt:

  > Describe this desktop layout as JSON. For each visible window, provide its
  > approximate position and application type. Do not read small text.

- Output: JSON layout summary.
- Model: Qwen3-VL-32B.

#### Phase 2 — Window-Aware Detail (high-res, per-window crops)

- Obtain window geometry (x, y, width, height) and z-order from GNOME extension
  or `gdbus` into Mutter.
- **Skip minimized or fully occluded windows.** If z-order unavailable, process
  top 3 largest.
- Crop each visible window at native pixel density.

**Per-window processing (dual-model):**

1. **Qwen3-VL-32B** — scene understanding:

   > The window title is '{title}'. Respond with JSON only. Extract:
   > "app", "text_blocks" (array of {"text", "region"}),
   > "ui_elements" (array of {"type", "label"}), "summary".
   > Only describe what you can clearly see. Use [illegible] for unclear text.

2. **GLM-OCR** — faithful text extraction (run on same crop):

   > Extract all visible text from this UI screenshot as structured Markdown.
   > Preserve layout (headings, code blocks, tables). Mark illegible regions.

3. **Cross-check:** If Qwen3-VL claims text that GLM-OCR does not find, mark the
   block as `"confidence": "low"`. Keep GLM-OCR's text as the authoritative
   transcription; keep Qwen3-VL's semantic understanding (app type, UI elements,
   activity summary).

- Use `temperature: 0` for deterministic output.
- **JSON reliability:** Ollama's `format: "json"` if available, `json-repair` package,
  retry up to 2 times on parse failure.

**Region taxonomy:** header, body, sidebar, footer, tab, toolbar, statusbar.
**UI element types:** button, menu, tab, input, icon, image, chart, table.

#### Sub-Tiling for Maximized/Large Windows

If a window crop exceeds your pixel budget `B`:

- **Tile size:** 1920x1088 (1088 instead of 1080 because it's divisible by 32,
  satisfying Qwen3-VL's rounding requirement). `1920 * 1088 ≈ 2.09 MP`.
- **Overlap:** 192x96 (~10%), rounded to multiples of 32 for clean coordinate mapping.
- **Grid for full 4K:** 2x2 = 4 tiles.
- **Grid for 8K (7680x4320):** 4x4 = 16 tiles at the same tile size.

**Precise tile placement for 3840x2160 (B=2.09 MP):**

```
Tile 0 (top-left):     x=[0, 1920+192],   y=[0, 1088+96]
Tile 1 (top-right):    x=[1920-192, 3840], y=[0, 1088+96]
Tile 2 (bottom-left):  x=[0, 1920+192],   y=[1088-96, 2160]
Tile 3 (bottom-right): x=[1920-192, 3840], y=[1088-96, 2160]
```

For higher text fidelity, increase to B=4.2 MP (~2048x2048 tiles), which reduces tiles
but increases compute per tile.

#### Future: Model-Driven Zoom (upgrade path)

Qwen3-VL's `image_zoom_in_tool` enables a hybrid approach:

1. Run deterministic tiling for guaranteed coverage.
2. If a tile's OCR confidence is poor, invoke the zoom tool on that region.
3. This is not needed for the initial prototype but is the natural next step.

#### Phase 3 — Synthesis (optional)

Skip for early prototyping. Store per-window records directly.

If a unified description is needed, merge **deterministically first:**
- Concatenate text blocks in reading order (top-to-bottom, left-to-right).
- Deduplicate overlap regions using string similarity on normalized text (collapse
  whitespace, normalize quotes), keeping the longer variant.
- Then optionally run a text-only summarization pass for a compact "activity summary."

#### Fallback: Grid Tiling (if window geometry unavailable)

- Tile size: 1920x1088 (landscape, 32-aligned).
- Overlap: 192x96 (10%, 32-aligned).
- Total: 4 tiles for 3840x2160.
- Deduplicate via text similarity (normalized Levenshtein), not pixel bboxes.

### 4. Delta Storage

1. Compute pHash of each screenshot.
2. If unchanged → store `{"delta": "no_change"}` and skip.
3. If only active window changed → re-process only that window.

### 5. Tools and NixOS Configuration

```nix
# configuration.nix
services.ollama = {
  enable = true;
  acceleration = "cuda";
  environmentVariables = {
    OLLAMA_MAX_LOADED_MODELS = "2";  # Qwen3-VL + GLM-OCR
    OLLAMA_NUM_PARALLEL = "1";
  };
};
hardware.nvidia.modesetting.enable = true;
```

```bash
# Pull both models
ollama pull qwen3-vl:32b
ollama pull glm-ocr
```

- **Capture:** `gnome-screenshot` (test on Wayland); fallback to GNOME D-Bus portal.
- **Format:** PNG only (lossless).
- **Trigger:** `systemd.timer` every 5 minutes, or on window-focus-change.
- **Image processing:** pyvips; Pillow as fallback.
- **Storage:** SQLite with FTS5.

```json
{
  "id": "uuid",
  "timestamp": "2026-02-10T14:30:00Z",
  "screenshot_hash": "phash_hex",
  "delta": "full|partial|no_change",
  "layout": {"windows": [{"position": "...", "app": "..."}]},
  "windows": [
    {
      "title": "VS Code - project/main.py",
      "app": "code",
      "text_blocks": [
        {"text": "import numpy as np", "region": "body", "source": "glm-ocr", "confidence": "high"}
      ],
      "ui_elements": [{"type": "tab", "label": "main.py"}],
      "summary": "Editing Python code in VS Code."
    }
  ],
  "active_window": "VS Code - project/main.py",
  "mouse_region": "center",
  "idle_seconds": 5,
  "label": null
}
```

### 6. Processing Pipeline

```python
import json, base64, io, subprocess
from pathlib import Path
from datetime import datetime, UTC
import requests

try:
    import pyvips
    USE_PYVIPS = True
except ImportError:
    from PIL import Image
    USE_PYVIPS = False

OLLAMA_URL = "http://localhost:11434/api/chat"
VLM_MODEL = "qwen3-vl:32b"
OCR_MODEL = "glm-ocr"
MAX_CROP_PIXELS = 2_090_000  # ~1920x1088; adjust based on Step 0
TILE_W, TILE_H = 1920, 1088  # multiples of 32 for Qwen3-VL
OVERLAP_X, OVERLAP_Y = 192, 96  # ~10%, multiples of 32


def crop_region(screenshot_path: Path, x: int, y: int, w: int, h: int) -> bytes:
    if USE_PYVIPS:
        img = pyvips.Image.new_from_file(str(screenshot_path))
        return img.crop(x, y, w, h).write_to_buffer(".png")
    img = Image.open(screenshot_path)
    buf = io.BytesIO()
    img.crop((x, y, x + w, y + h)).save(buf, format="PNG")
    return buf.getvalue()


def make_tiles(wx: int, wy: int, ww: int, wh: int) -> list[tuple[int, int, int, int]]:
    """Generate overlapping tiles for a window that exceeds MAX_CROP_PIXELS."""
    tiles = []
    y = wy
    while y < wy + wh:
        th = min(TILE_H, wy + wh - y)
        x = wx
        while x < wx + ww:
            tw = min(TILE_W, wx + ww - x)
            tiles.append((x, y, tw, th))
            x += TILE_W - OVERLAP_X
        y += TILE_H - OVERLAP_Y
    return tiles


def query_model(model: str, image_bytes: bytes, prompt: str) -> str:
    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(OLLAMA_URL, json={
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": 0},
    }, timeout=180)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def process_window(screenshot_path: Path, w: dict) -> dict:
    wx, wy, ww, wh = w["x"], w["y"], w["width"], w["height"]

    if ww * wh > MAX_CROP_PIXELS:
        regions = make_tiles(wx, wy, ww, wh)
    else:
        regions = [(wx, wy, ww, wh)]

    vlm_descs, ocr_descs = [], []
    for rx, ry, rw, rh in regions:
        crop_bytes = crop_region(screenshot_path, rx, ry, rw, rh)

        vlm_desc = query_model(VLM_MODEL, crop_bytes,
            f"Window title: '{w['title']}'. Respond JSON only. Extract: "
            '"app", "text_blocks" [{{"text","region"}}], '
            '"ui_elements" [{{"type","label"}}], "summary". '
            "Only describe what you see. Use [illegible] for unclear text.")
        vlm_descs.append(vlm_desc)

        ocr_desc = query_model(OCR_MODEL, crop_bytes,
            "Extract all visible text as structured Markdown. "
            "Preserve layout. Mark illegible regions with [illegible].")
        ocr_descs.append(ocr_desc)

    return {
        "title": w["title"],
        "geometry": w,
        "vlm_description": vlm_descs if len(vlm_descs) > 1 else vlm_descs[0],
        "ocr_text": ocr_descs if len(ocr_descs) > 1 else ocr_descs[0],
    }


def process_screenshot(screenshot_path: Path, ctx: dict) -> dict:
    # Phase 1: Global layout (Qwen3-VL only)
    with open(screenshot_path, "rb") as f:
        layout = query_model(VLM_MODEL, f.read(),
            "Describe this desktop layout as JSON. List visible windows, "
            "positions, and app types. Do not read small text.")

    # Phase 2: Per-window detail (dual model, skip occluded/minimized)
    windows = []
    for w in ctx.get("windows", []):
        if w.get("minimized") or w.get("occluded"):
            continue
        windows.append(process_window(screenshot_path, w))

    return {
        "id": str(__import__("uuid").uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "layout": layout,
        "windows": windows,
        "active_window": ctx.get("active_window", "unknown"),
        "mouse_position": (ctx.get("mouse_x"), ctx.get("mouse_y")),
        "idle_seconds": ctx.get("idle_seconds", 0),
        "label": None,
    }
```

### 7. Classification Architecture (future)

1. **Hierarchical labels:** `client > project > activity_type`.
2. **Two-layer dataset:** Event stream (one row per screen state) + session segments
   (grouped by stable active window title + idle gaps).
3. **Features:** Window title, repository/file names, ticket IDs, domains (high signal);
   app identity; text snippets; temporal structure (sessions, context switches).
4. **Fast baseline:** TF-IDF / embeddings on `(window_title + ocr_text + summary)`.
5. **Next:** Lightweight per-client/project classifier with human-in-the-loop corrections.
6. **Only after stable labels:** RL-style training. VLM stage stays fixed (data reduction);
   train only the classifier stage.
7. **Upgrade path:** Start with deterministic tiling now, later upgrade to hybrid
   "coverage + Qwen3-VL zoom tool" without changing the core model.

## CHANGES

Research deliverable — no code changes to the existing codebase.

**Major revision changes:**
1. **Primary model upgraded** from Qwen2.5-VL-72B to **Qwen3-VL-32B** — the direct
   successor, released Sep-Oct 2025, with GUI understanding upgrades, 256K context,
   and Apache-2.0 license.
2. **Secondary OCR model added:** **GLM-OCR** (~0.9B, Apache-2.0) for faithful text
   extraction and cross-validation against VLM hallucination.
3. **Quantization upgraded** to Q8_0 as default — the 32B model is small enough that
   near-lossless precision is comfortable on 96 GB.
4. **Tile dimensions updated** to multiples of 32 (1920x1088, overlap 192x96) per
   Qwen3-VL's documented rounding requirements.
5. **Dual-model pipeline** in pseudocode: Qwen3-VL for scene understanding, GLM-OCR
   for text extraction, with cross-check for hallucination detection.
6. **Zoom-in tool pathway** documented as a future upgrade from deterministic tiling
   to hybrid model-driven zoom.
7. **NixOS config updated** with `OLLAMA_MAX_LOADED_MODELS = "2"` for dual-model serving.
8. **All prior architecture retained:** window-aware cropping, delta storage, Step 0
   check, Z-order occlusion handling, structured JSON, text-similarity deduplication.
