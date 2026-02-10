# Revised: Desktop Vision Model Selection for Screenshot Classification Pipeline

*Incorporates feedback from all three agent critiques. Key revisions: simplified pipeline
with optional synthesis, structured JSON output, delta storage, qualified benchmark claims,
fixed pseudocode, added empirical verification step.*

## PLAN

### 1. Model Selection: Qwen2.5-VL-72B-Instruct (Unanimous)

All three agents independently selected the same model. This is the consensus
recommendation with high confidence.

**Rationale:**
- **Dynamic resolution** via configurable pixel budget — the single most important feature
  for avoiding the user's previous downscaling/hallucination problem.
- **Strong OCR and document understanding** — benchmarks place it among the top open models
  for text-heavy visual tasks (approximate scores: DocVQA mid-90s, OCRBench high-800s,
  ChartQA high-80s — *these are approximate and should be verified against the latest
  published results*).
- **Comfortable fit on 96 GB VRAM** at Q4_K_M quantization (~42 GB weights), with room
  for KV cache and visual tokens.
- **Available on Ollama** as `qwen2.5-vl:72b` with vision API support.
- **Alternatives considered:** InternVL2.5-78B (strong alternative, tile-based dynamic
  resolution), DeepSeek-VL2 (MoE, smaller active params), Gemma 3 27B (too small for
  this task). The user should check for newer models (Qwen3-VL, InternVL3, etc.) that
  may have been released by the time of deployment.

### 2. Quantization: Start with Q4_K_M, Empirically Test Q5_K_M

**Revised from original recommendation.** Agent C advocated Q8_0; Agents A and B
preferred Q4_K_M. The revised recommendation is:

1. **Start with Q4_K_M** (~42 GB weights). This leaves ~54 GB for KV cache, visual tokens,
   and overhead — ample room for window-crop processing.
2. **Test Q5_K_M** (~49 GB weights) if Q4 OCR quality is insufficient. Still leaves ~47 GB.
3. **Q8_0 is viable only for small crops** (individual windows), not full 4K images.
   Q8_0 weights (~72-77 GB) plus KV cache for large images may exceed 96 GB.

Agent C's point that 96 GB allows higher precision is valid for per-window crops (which
are much smaller than full 4K), so Q5_K_M or even Q6_K could be used in the window-crop
phase if quality demands it.

### 3. Screenshot Preparation: Window-Aware Cropping (Consensus)

All three agents converged on window-aware cropping as superior to blind grid tiling
(Agent C adopted this from my original proposal; Agent B acknowledged it in their
critique). This is now the consensus primary strategy.

#### Step 0 — Empirical Verification (adopted from Agent C's feedback)

Before committing to the full pipeline, run a quick sanity check:

1. Capture a 4K screenshot with known text at various sizes.
2. Send it to Qwen2.5-VL-72B via Ollama at default settings.
3. Ask the model to read specific small text.
4. **If it can read 12px+ text accurately → the default pixel budget may suffice for
   many use cases, simplifying the pipeline.**
5. If it cannot → proceed with the window-aware cropping pipeline below.

This "try native first" step avoids over-engineering if the model's default resolution
handling proves adequate.

#### Primary Strategy: Two-Phase Processing + Optional Synthesis

**Simplified from the original three-phase approach** based on Agent B's and Agent C's
feedback that the full three-phase pipeline is heavy for early prototyping. The synthesis
phase is now optional.

**Phase 1 — Global Layout Scan (low-res, full screenshot)**

- Process the full 3840x2160 screenshot at default `max_pixels` (~1M pixels).
- At this resolution, window positions and application types are identifiable, but fine
  text is not legible.
- Prompt:

  > Describe the desktop layout as JSON. For each visible window, provide its approximate
  > position (top-left, top-right, center, bottom-left, bottom-right, maximized) and the
  > application type if identifiable. Do not attempt to read small text.

- Output: structured JSON layout description.
- VRAM usage: ~46-48 GB (comfortable).

**Phase 2 — Window-Aware Detailed Extraction (high-res, per-window crops)**

- Use GNOME Shell's `gdbus` interface or the user's existing GNOME extension to obtain
  window geometry (x, y, width, height) and z-order.
- Crop each visible window from the full-resolution screenshot at native pixel density.
- Process each window crop independently via the Ollama API.
- Include the window title from the GNOME extension in the prompt (all agents agree this
  is a critical grounding technique).

- Prompt per window (requesting structured JSON output — adopted from Agent B):

  > The active window title is '{window_title}'. This is a cropped screenshot of that
  > window at native resolution. Respond with JSON only.
  >
  > Extract:
  > - "app": application name
  > - "text_blocks": array of {"text": "verbatim text", "region": "header|body|sidebar|footer|tab|toolbar|statusbar"}
  > - "ui_elements": array of {"type": "button|menu|tab|input|icon|image|chart|table", "label": "description"}
  > - "summary": one-paragraph description of the window's content and the user's apparent activity
  >
  > Only describe what you can clearly see. If text is unclear, use "[illegible]".
  > Do not guess or infer content that is not visible.

- Output: structured JSON per window.
- VRAM usage: ~48-52 GB per window (comfortable; individual window crops are much
  smaller than full 4K).
- Latency: ~10-30 seconds per window.

**Phase 3 — Synthesis (optional, text-only merge)**

- If a single unified description is needed (e.g., for a classification model that
  expects one text input), combine Phase 1 layout with Phase 2 per-window JSONs.
- This can be a simple programmatic merge (concatenate JSONs into a structured document)
  or an LLM synthesis pass.
- **For early prototyping, skip this phase** and store per-window descriptions directly.
  A classification model can consume the structured per-window data without synthesis.

#### Fallback: Grid-Based Tiling (if window geometry is unavailable)

If the GNOME extension does not expose window geometry, fall back to tiling:

- **Tile size:** 1920x1080 (landscape, matching the 16:9 aspect ratio — more efficient
  than Agent B's square 1344x1344 tiles, producing 4 tiles instead of 8).
- **Overlap:** 10-15% (192x108 px at 10%) to avoid cutting text at boundaries.
- **Total tiles for 3840x2160:** 4 (2x2 grid).
- **Merge:** Collect tile descriptions, deduplicate using text similarity on overlap
  regions (prefer text-similarity-based deduplication over pixel-level bboxes, which
  VLMs produce unreliably — per Agent A's critique of Agent B).

### 4. Delta Storage Between Consecutive Frames (adopted from Agent B)

To reduce redundant processing and storage:

1. Compute a perceptual hash (e.g., pHash) of each screenshot.
2. Compare with the previous frame's hash.
3. If the difference is below a threshold, skip full processing and store only
   `{"delta": "no_change", "timestamp": "..."}`.
4. For partial changes (e.g., only the active window changed), re-process only the
   changed windows using GNOME's focus-change events.

This optimization is especially valuable for the user's consulting workflow where long
periods may be spent in a single application.

### 5. Supplementary Tools and Workflow

**NixOS configuration (unchanged, validated by all agents):**

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
# Ensure NVIDIA drivers are configured:
hardware.nvidia.modesetting.enable = true;
```

**Screenshot capture:**
- Primary: `gnome-screenshot --file=/path/to/screenshot.png` (test on Wayland first)
- Fallback: GNOME Shell D-Bus screenshot portal
- Format: **PNG only** (lossless; JPEG artifacts harm OCR — all agents agree)
- Trigger: `systemd.timer` at fixed intervals (e.g., every 5 minutes) or on
  window-focus-change events

**Image processing:**
- **pyvips** (adopted from Agent B) for memory-efficient cropping of large images.
- Fallback to Pillow if pyvips is unavailable on NixOS.

**Optional secondary OCR (adopted from Agent B):**
- Run Tesseract or PaddleOCR on window crops as a cross-check.
- If the VLM's text extraction and the dedicated OCR diverge significantly, flag the
  result for review. This catches hallucinations without requiring manual inspection.

**Data storage:**

```json
{
  "id": "uuid",
  "timestamp": "2026-02-10T14:30:00Z",
  "screenshot_hash": "phash_hex",
  "delta": "full|partial|no_change",
  "layout": {"windows": [{"position": "...", "app": "..."}]},
  "windows": [
    {
      "title": "VS Code - arena/solution.md",
      "app": "code",
      "text_blocks": [{"text": "...", "region": "body"}],
      "ui_elements": [{"type": "tab", "label": "solution.md"}],
      "summary": "Editing solution.md in VS Code..."
    }
  ],
  "active_window": "VS Code - arena/solution.md",
  "mouse_region": "center",
  "idle_seconds": 5,
  "label": null
}
```

Storage: SQLite with FTS5 for full-text search on descriptions.

### 6. Revised Processing Pipeline (pseudocode, bug fixed)

```python
import json, base64, io, subprocess
from pathlib import Path
from datetime import datetime, UTC

import requests

# Use pyvips if available, fall back to Pillow
try:
    import pyvips
    USE_PYVIPS = True
except ImportError:
    from PIL import Image
    USE_PYVIPS = False

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5-vl:72b"


def capture_screenshot() -> Path:
    path = Path(f"/tmp/screenshots/{datetime.now(UTC).isoformat()}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gnome-screenshot", "--file", str(path)], check=True)
    return path


def get_window_context() -> dict:
    """Read window titles, geometry, and mouse data from GNOME extension."""
    return json.loads(Path("/tmp/window_context.json").read_text())


def crop_window_pyvips(screenshot_path: Path, w: dict) -> bytes:
    img = pyvips.Image.new_from_file(str(screenshot_path))
    crop = img.crop(w["x"], w["y"], w["width"], w["height"])
    return crop.write_to_buffer(".png")


def crop_window_pillow(screenshot_path: Path, w: dict) -> bytes:
    img = Image.open(screenshot_path)
    box = (w["x"], w["y"], w["x"] + w["width"], w["y"] + w["height"])
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    return buf.getvalue()


def crop_window(screenshot_path: Path, w: dict) -> bytes:
    if USE_PYVIPS:
        return crop_window_pyvips(screenshot_path, w)
    return crop_window_pillow(screenshot_path, w)


def query_vision(image_bytes: bytes, prompt: str) -> str:
    """Send an image + prompt to Ollama's vision API."""
    image_b64 = base64.b64encode(image_bytes).decode()
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "user", "content": prompt, "images": [image_b64]}
            ],
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def query_text(prompt: str) -> str:
    """Send a text-only prompt (no image) to Ollama."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def process_screenshot(screenshot_path: Path) -> dict:
    ctx = get_window_context()

    # Phase 1: Global layout
    with open(screenshot_path, "rb") as f:
        full_image_bytes = f.read()

    layout = query_vision(
        full_image_bytes,
        "Describe this desktop screenshot layout as JSON. "
        "For each visible window, provide its approximate position and "
        "application type. Do not read small text.",
    )

    # Phase 2: Per-window detail
    window_descriptions = []
    for w in ctx.get("windows", []):
        crop_bytes = crop_window(screenshot_path, w)
        desc = query_vision(
            crop_bytes,
            f"The window title is '{w['title']}'. "
            "Respond with JSON only. Extract: "
            '"app", "text_blocks" (array of {{"text","region"}}), '
            '"ui_elements" (array of {{"type","label"}}), '
            '"summary". '
            "Only describe what you can clearly see. "
            "Use [illegible] for unclear text.",
        )
        window_descriptions.append(
            {"title": w["title"], "geometry": w, "description": desc}
        )

    return {
        "id": str(__import__("uuid").uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "layout": layout,
        "windows": window_descriptions,
        "active_window": ctx.get("active_window", "unknown"),
        "mouse_position": (ctx.get("mouse_x"), ctx.get("mouse_y")),
        "idle_seconds": ctx.get("idle_seconds", 0),
        "label": None,
    }
```

### 7. Architectural Considerations for Future Classification

**Unchanged from original, with additions from Agent B:**

1. **Hierarchical labeling:** `client > project > activity_type`.
2. **Feature extraction:** Window title (high signal), application list (categorical),
   time-of-day/day-of-week (contextual), structured text blocks (primary).
3. **Session segmentation** (adopted from Agent B): Group events by active window/app
   and idle gaps to build coherent activity segments before classification.
4. **Human-in-the-loop** (adopted from Agent B): Periodically sample descriptions for
   manual review to catch drift and refine labels.
5. **Classification models:** Embedding + classifier (fast), few-shot LLM (zero training),
   or fine-tuned small model (best accuracy/speed trade-off).
6. **Privacy:** All local. Store only text. Consider per-client encryption.

## CHANGES

This is a research and analysis deliverable. No code changes to the existing codebase.

**Revisions from original solution:**
1. **Qualified benchmark claims** — scores now presented as approximate ranges with an
   explicit note to verify against published results (addressing Agent B's critique).
2. **Simplified pipeline** — synthesis phase made optional; two-phase (layout + window
   crops) is the default (addressing Agents B and C's complexity concerns).
3. **Structured JSON output** — adopted Agent B's per-tile schema, adapted for per-window
   use (addressing my own self-critique and Agent B's feedback).
4. **Delta storage** — adopted from Agent B to reduce redundant processing.
5. **Fixed pseudocode bug** — `query_vision("", ...)` replaced with a separate
   `query_text()` function that omits the `images` field entirely.
6. **Added Step 0 empirical verification** — adopted from Agent C's "try native first"
   philosophy.
7. **pyvips recommendation** — adopted from Agent B for memory-efficient image processing.
8. **Secondary OCR cross-checking** — promoted from open question to recommended practice.
9. **Quantization guidance refined** — Q4_K_M as starting point, Q5_K_M as quality
   upgrade, Q8_0 viable for per-window crops only.
