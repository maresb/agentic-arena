# Final Revised: Desktop Vision Model for Screenshot Classification

*Round 01 revision. Incorporates: Z-order occlusion handling (Agent C), removed
unverified benchmark numbers (Agent B), reduced verbosity, removed impractical
quantization-switching discussion.*

## PLAN

### 1. Model: Qwen2.5-VL-72B-Instruct (Unanimous)

All agents independently selected this model across two rounds. High confidence.

- **Dynamic resolution** via configurable pixel budget — avoids forced downscaling.
- **Strong OCR and UI understanding** — frequently cited by the local VLM community as
  the top open model for text-heavy visual tasks. Verify against the latest published
  benchmarks before deployment; newer models (Qwen3-VL, InternVL3) may exist by then.
- **Fits 96 GB VRAM** at Q4_K_M (~42 GB weights), leaving ~54 GB for KV cache and overhead.
- **Available on Ollama** as `qwen2.5-vl:72b`.

**Quantization: Q4_K_M** (consensus). Test Q5_K_M if OCR quality on small text is
insufficient. Q8_0 is too tight once visual-token KV cache is included.

### 2. Screenshot Preparation: Window-Aware Cropping (Consensus)

#### Step 0 — Empirical Sanity Check

Before building the full pipeline, test whether Ollama downscales 4K images:

1. Capture a 4K screenshot with known small text (e.g., 12px terminal font).
2. Send to Qwen2.5-VL-72B via Ollama, ask it to read the small text verbatim.
3. If it reads accurately → the default pixel budget suffices for many cases.
4. If it fails → proceed with the window-aware pipeline below.

#### Phase 1 — Global Layout (low-res, full screenshot)

- Process the full 3840x2160 at the model's default pixel budget (~1M pixels).
- Prompt:

  > Describe this desktop layout as JSON. For each visible window, provide its
  > approximate position and application type. Do not read small text.

- Output: JSON layout summary.
- Purpose: spatial context for classification; not for text extraction.

#### Phase 2 — Window-Aware Detail (high-res, per-window crops)

- Obtain window geometry (x, y, width, height) and z-order from the GNOME extension
  or via `gdbus` into GNOME Shell's Mutter interface.
- **Skip minimized or fully occluded windows** (adopted from Agent C). If z-order is
  unavailable, process only the top 3 largest visible windows.
- Crop each visible window from the full-resolution screenshot at native pixel density.
- Include the window title in the prompt for grounding (all agents agree).
- Prompt per window:

  > The window title is '{title}'. Respond with JSON only. Extract:
  > "app", "text_blocks" (array of {"text", "region"}),
  > "ui_elements" (array of {"type", "label"}), "summary".
  > Only describe what you can clearly see. Use [illegible] for unclear text.

- Output: structured JSON per window.
- Use `temperature: 0` for deterministic, low-hallucination output.

**Region taxonomy for `text_blocks`:** header, body, sidebar, footer, tab, toolbar, statusbar.
**Types for `ui_elements`:** button, menu, tab, input, icon, image, chart, table.

#### Phase 3 — Synthesis (optional)

For early prototyping, skip this. Store per-window JSONs directly. If a unified
description is needed later, merge programmatically or with a text-only LLM pass.

#### Fallback: Grid Tiling (if window geometry is unavailable)

- Tile size: ~1920x1080 (landscape, 16:9). Total: 4 tiles for 3840x2160.
- Overlap: 10-15% to prevent cutting text at boundaries.
- Deduplicate overlap regions using text similarity (normalized Levenshtein), not
  pixel-level bboxes (which VLMs produce unreliably).

### 3. Delta Storage (adopted from Agent B)

1. Compute a perceptual hash (pHash) of each screenshot.
2. If unchanged from previous frame → store `{"delta": "no_change"}` and skip.
3. If only the active window changed → re-process only that window.

### 4. Tools and NixOS Configuration

```nix
# configuration.nix
services.ollama = {
  enable = true;
  acceleration = "cuda";
  environmentVariables = {
    OLLAMA_MAX_LOADED_MODELS = "1";
    OLLAMA_NUM_PARALLEL = "1";
  };
};
hardware.nvidia.modesetting.enable = true;
```

- **Capture:** `gnome-screenshot` (test on Wayland first); fallback to GNOME D-Bus portal.
- **Format:** PNG only (lossless; JPEG artifacts harm OCR).
- **Trigger:** `systemd.timer` every 5 minutes, or on window-focus-change events.
- **Image processing:** pyvips (memory-efficient); Pillow as fallback.
- **Optional OCR cross-check:** Tesseract or PaddleOCR to catch VLM hallucinations.
- **Storage:** SQLite with FTS5. Schema:

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
      "text_blocks": [{"text": "import numpy as np", "region": "body"}],
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

### 5. Processing Pipeline (pseudocode)

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
MODEL = "qwen2.5-vl:72b"


def crop_window(screenshot_path: Path, w: dict) -> bytes:
    if USE_PYVIPS:
        img = pyvips.Image.new_from_file(str(screenshot_path))
        return img.crop(w["x"], w["y"], w["width"], w["height"]).write_to_buffer(".png")
    img = Image.open(screenshot_path)
    box = (w["x"], w["y"], w["x"] + w["width"], w["y"] + w["height"])
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    return buf.getvalue()


def query_vision(image_bytes: bytes, prompt: str) -> str:
    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": 0},
    }, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def process_screenshot(screenshot_path: Path, ctx: dict) -> dict:
    # Phase 1: Global layout
    with open(screenshot_path, "rb") as f:
        layout = query_vision(f.read(),
            "Describe this desktop layout as JSON. List visible windows, "
            "positions, and app types. Do not read small text.")

    # Phase 2: Per-window detail (skip occluded/minimized)
    windows = []
    for w in ctx.get("windows", []):
        if w.get("minimized") or w.get("occluded"):
            continue
        crop_bytes = crop_window(screenshot_path, w)
        desc = query_vision(crop_bytes,
            f"Window title: '{w['title']}'. Respond JSON only. Extract: "
            '"app", "text_blocks" [{{"text","region"}}], '
            '"ui_elements" [{{"type","label"}}], "summary". '
            "Only describe what you see. Use [illegible] for unclear text.")
        windows.append({"title": w["title"], "geometry": w, "description": desc})

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

### 6. Classification Architecture (future)

1. **Hierarchical labels:** `client > project > activity_type`.
2. **Features:** Window title (high signal), app list, time-of-day, structured text.
3. **Session segmentation:** Group by active window + idle gaps.
4. **Models:** Embedding + classifier (fast), few-shot LLM (zero training), or
   fine-tuned small model (best accuracy/speed trade-off).
5. **Human-in-the-loop:** Periodic manual review for drift detection.
6. **Privacy:** All local. Store only text. Consider per-client encryption.

## CHANGES

Research deliverable — no code changes to the existing codebase.

**Revisions from round 00:**
1. Added Z-order occlusion handling (Agent C) — skip minimized/occluded windows.
2. Removed unverified benchmark numbers (Agent B) — replaced with community sentiment.
3. Reduced verbosity (~40% shorter than round 00 revision).
4. Removed impractical quantization-switching paragraph.
5. Tightened pseudocode while keeping it functional.
6. All prior revisions retained: structured JSON, delta storage, Step 0 check, pyvips,
   secondary OCR, fixed pseudocode bug, NixOS config.
