# Desktop Vision Model Selection for Screenshot Classification Pipeline

## PLAN

### 1. Model Selection: Qwen2.5-VL-72B-Instruct

**Rationale:** After evaluating the current landscape of locally-deployable vision-language
models as of February 2026, **Qwen2.5-VL-72B-Instruct** is the recommended model. It
represents the strongest balance of OCR accuracy, dynamic resolution handling, hardware
compatibility, and Ollama availability for the described use case.

**Candidates evaluated:**

| Model | Params | VRAM (Q4) | Dynamic Res | OCR Quality | Ollama | Verdict |
|---|---|---|---|---|---|---|
| **Qwen2.5-VL-72B** | 72B | ~42 GB | Yes (pixel-budget) | Best-in-class | Yes | **Selected** |
| InternVL2.5-78B | 78B | ~45 GB | Yes (tile-based) | Excellent | Yes | Strong alternative |
| Llama 3.2 Vision 90B | 90B | ~52 GB | No (fixed 560px) | Good | Yes | Ruled out: fixed resolution |
| Pixtral Large 124B | 124B | ~72 GB | Yes | Excellent | Limited | Ruled out: too large for comfortable use |
| DeepSeek-VL2 (MoE) | ~28B active | ~20 GB | Yes | Very good | Yes | Good backup; smaller active params |
| Gemma 3 27B | 27B | ~16 GB | Yes | Good | Yes | Ruled out: insufficient detail at 27B |
| Molmo 72B | 72B | ~42 GB | Limited | Good | Limited | Less mature ecosystem |

**Why Qwen2.5-VL-72B wins:**

- **Dynamic resolution via configurable pixel budget.** Unlike models that force a fixed
  input size (e.g., Llama 3.2 Vision at 560x560), Qwen2.5-VL allocates a variable number
  of visual tokens based on the actual image dimensions. The `min_pixels` and `max_pixels`
  parameters are user-configurable, allowing you to trade VRAM for resolution fidelity.
- **State-of-the-art OCR benchmarks.** Qwen2.5-VL-72B achieves DocVQA ~94.5%, OCRBench
  ~877/1000, ChartQA ~88%, TextVQA ~84%. These are the metrics that matter most for reading
  screen content accurately.
- **Proven text extraction from UIs.** The model was specifically trained on document
  understanding, chart reading, and GUI comprehension tasks, making it ideal for desktop
  screenshot analysis.
- **Comfortable fit on 96 GB VRAM.** At Q4_K_M quantization, weights occupy ~42 GB, leaving
  ~54 GB for KV cache, visual token activations, and system overhead. This is enough to
  process high-resolution images without OOM errors.
- **First-class Ollama support.** Available as `qwen2.5-vl:72b` (or specific quantization
  tags like `qwen2.5-vl:72b-instruct-q4_K_M`), with proper vision API support via
  Ollama's `/api/chat` endpoint.

---

### 2. Model Specifications in Detail

**Architecture:**
- Base: Qwen2.5 language model (72B parameters, 80 layers, hidden dim 8192)
- Vision encoder: SigLip-based ViT (~400M parameters)
- Patch size: 14x14 pixels
- Spatial merge factor: 2x2 (so effective patch = 28x28 pixels)
- Positional encoding: 2D Rotary Position Embeddings (2D-RoPE) for spatial awareness
- Context window: 32,768 tokens (expandable via RoPE scaling to 128K)

**Resolution handling:**
- Images are resized to fit within a pixel budget: `min_pixels` to `max_pixels`
- Default `max_pixels` = 1,003,520 (~1001x1001 equivalent)
- **Can be increased** to ~8,400,000 (full 4K) if VRAM allows
- Visual tokens for 3840x2160 at native: (3840/28) x (2160/28) = 137 x 77 = **~10,549 tokens**
- Visual tokens at default max_pixels: ~1,280 tokens (heavily downscaled)

**VRAM budget for full 4K processing (72B Q4):**

| Component | Estimated VRAM |
|---|---|
| Model weights (Q4_K_M) | ~42 GB |
| Visual tokens KV cache (10.5K tokens, 80 layers) | ~20-26 GB |
| Text generation KV cache (~2K tokens) | ~4-5 GB |
| Activations and overhead | ~5-8 GB |
| **Total** | **~71-81 GB** |

This is tight but feasible on 96 GB. For safety margin, the recommended approach uses
a two-pass strategy (see below).

**Quantization recommendations:**
- **Q4_K_M**: Best balance of quality and VRAM. ~42 GB weights. Recommended.
- **Q5_K_M**: Slightly better quality, ~49 GB weights. Use if VRAM allows after testing.
- **Q8_0**: Near-lossless, ~72 GB weights. Too large for comfortable full-4K processing.
- **Q4_K_S**: Slightly smaller than Q4_K_M, minimal quality loss. Fallback option.

---

### 3. Screenshot Preparation Strategy: Hybrid Two-Pass + Window-Aware Cropping

The critical insight from the user's previous failed attempt is that **naive downscaling
destroys text legibility**, causing the model to hallucinate content. The solution is a
multi-pass strategy that avoids aggressive downscaling entirely.

#### Recommended Approach: Three-Phase Processing

**Phase 1 — Global Layout Scan (low-res, full screenshot)**

- Process the full 3840x2160 screenshot at default `max_pixels` (~1M pixels)
- This downscales to approximately 1001x1001
- At this resolution, window positions and application types are visible, but fine text is not
- Prompt: *"Describe the desktop layout. List all visible windows, their approximate positions
  (top-left, center, etc.), and the application type if identifiable. Do not attempt to read
  small text."*
- Output: structured layout description (JSON preferred)
- VRAM usage: ~46-48 GB (comfortable)
- Latency: ~5-15 seconds

**Phase 2 — Window-Aware Detailed Extraction (high-res, per-window crops)**

- Use GNOME window manager data (from the title-polling extension) to get window boundaries
- Crop each visible window from the full-resolution screenshot
- Process each window crop at native resolution or near-native
- For a typical window (e.g., 1920x1200): ~(1920/28) x (1200/28) = 69 x 43 = ~2,967 visual tokens
- This is very comfortable on VRAM
- Prompt per window: *"This is a cropped screenshot of a [window_title] window. Read and
  transcribe ALL visible text verbatim. Describe all visual elements including images, icons,
  charts, code, tables, and UI components. Note the scroll position and any partially visible
  content."*
- Include window title and mouse position as supplementary context in the prompt
- Output: detailed per-window description
- VRAM usage: ~48-52 GB per window (comfortable)
- Latency: ~10-30 seconds per window

**Phase 3 — Synthesis (text-only merge)**

- Combine Phase 1 layout with Phase 2 per-window descriptions
- Can use the same Qwen2.5-VL model in text-only mode, or a separate text LLM
- Prompt: *"Given the following desktop layout and individual window descriptions, produce a
  unified, detailed description of the entire desktop state. Include: all application names,
  all visible text content, visual elements, and the user's apparent current activity."*
- Output: final unified description for storage
- VRAM usage: minimal (text-only)
- Latency: ~5-10 seconds

#### Fallback: Grid-Based Chunking (if window boundaries are unavailable)

If GNOME extension data is unavailable or windows overlap significantly:

**Chunk configuration for 3840x2160:**

| Grid | Tile Size | Overlap | Effective Tile | Total Tiles | Tokens/Tile |
|---|---|---|---|---|---|
| 2x2 | 1920x1080 | 10% (192x108) | 2112x1188 | 4 | ~3,200 |
| 2x2 | 1920x1080 | 15% (288x162) | 2208x1242 | 4 | ~3,500 |
| 3x2 | 1280x1080 | 10% (128x108) | 1408x1188 | 6 | ~2,400 |
| 4x3 | 960x720 | 10% (96x72) | 1056x792 | 12 | ~1,200 |

**Recommended: 2x2 grid with 10-15% overlap.**

- 4 tiles of ~2112x1188 (with overlap) or 1920x1080 (without)
- Each tile produces ~3,000-3,500 visual tokens — very comfortable on VRAM
- 10-15% overlap ensures no text is cut mid-line at tile boundaries
- Overlap regions can be used for deduplication during merge

**Overlap rationale:**
- Text lines are typically 14-24px tall at 4K. A 108px vertical overlap captures 4-7 full
  lines of text, ensuring no line is split without a complete copy in an adjacent tile.
- UI elements (buttons, menus, tabs) are typically 30-48px tall, well within the overlap margin.

**Tile placement (2x2 with 10% overlap on 3840x2160):**

```
Tile 0 (top-left):     x=[0, 2112],    y=[0, 1188]
Tile 1 (top-right):    x=[1728, 3840],  y=[0, 1188]
Tile 2 (bottom-left):  x=[0, 2112],    y=[972, 2160]
Tile 3 (bottom-right): x=[1728, 3840],  y=[972, 2160]
```

**Merge strategy for grid chunks:**
1. Process each tile with positional context: *"This is the [top-left/top-right/etc.] quadrant
   of a 3840x2160 desktop screenshot."*
2. Collect all 4 tile descriptions
3. Run a synthesis pass (text-only) that:
   - Deduplicates content that appears in overlap regions
   - Establishes spatial relationships between elements across tiles
   - Produces a coherent unified description

---

### 4. Supplementary Tools and Workflow

**Required components on NixOS:**

1. **Ollama** — Model serving
   - NixOS: `services.ollama.enable = true;` in configuration.nix, or via the `ollama` package
   - Pull model: `ollama pull qwen2.5-vl:72b`
   - Ensure CUDA support: `services.ollama.acceleration = "cuda";`

2. **Screenshot capture** — `gnome-screenshot`, `grim` (Wayland), or `scrot` (X11)
   - For GNOME on Wayland: `gnome-screenshot --file=/tmp/screenshot.png`
   - For periodic capture: `cron` or `systemd.timer`
   - Save as PNG (lossless) for maximum text fidelity — JPEG artifacts harm OCR

3. **GNOME extension data** — Active window title + mouse activity
   - Export as JSON alongside each screenshot
   - Format: `{"timestamp": "...", "active_window": "...", "mouse_x": N, "mouse_y": N, "idle_seconds": N}`

4. **Image processing** — Python with Pillow
   - Crop windows from screenshot using window geometry
   - Generate tiles for grid-based chunking
   - No resizing — preserve native resolution in crops

5. **Ollama API client** — Python `requests` or `ollama` Python package
   - Endpoint: `POST http://localhost:11434/api/chat`
   - Send base64-encoded image crops
   - Parse structured responses

6. **Data storage** — SQLite or simple JSON-lines file
   - Schema: timestamp, global_description, per_window_descriptions[], window_titles[],
     mouse_activity, client_label (for future classification)

**Recommended processing pipeline pseudocode:**

```python
import subprocess, json, base64, requests
from PIL import Image
from pathlib import Path
from datetime import datetime, UTC

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5-vl:72b"

def capture_screenshot() -> Path:
    path = Path(f"/tmp/screenshots/{datetime.now(UTC).isoformat()}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gnome-screenshot", "--file", str(path)], check=True)
    return path

def get_window_context() -> dict:
    # Read from GNOME extension's output file/DBus
    return json.loads(Path("/tmp/window_context.json").read_text())

def crop_windows(screenshot: Path, windows: list[dict]) -> list[tuple[str, Image.Image]]:
    img = Image.open(screenshot)
    crops = []
    for w in windows:
        box = (w["x"], w["y"], w["x"] + w["width"], w["y"] + w["height"])
        crops.append((w["title"], img.crop(box)))
    return crops

def image_to_base64(img: Image.Image) -> str:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def query_vision(image_b64: str, prompt: str) -> str:
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
    })
    return resp.json()["message"]["content"]

def process_screenshot(screenshot_path: Path) -> dict:
    ctx = get_window_context()

    # Phase 1: Global layout (model processes at default max_pixels)
    full_img = Image.open(screenshot_path)
    layout = query_vision(
        image_to_base64(full_img),
        "Describe the desktop layout. List all visible windows, their positions, "
        "and application types. Do not read small text."
    )

    # Phase 2: Per-window detail
    window_descriptions = {}
    if ctx.get("windows"):
        for title, crop in crop_windows(screenshot_path, ctx["windows"]):
            desc = query_vision(
                image_to_base64(crop),
                f"Window: '{title}'. Read ALL visible text verbatim. "
                f"Describe every visual element, image, chart, table, and UI component."
            )
            window_descriptions[title] = desc
    else:
        # Fallback: grid chunking
        window_descriptions = grid_chunk_and_process(full_img)

    # Phase 3: Synthesis
    synthesis_prompt = (
        f"Desktop layout:\n{layout}\n\n"
        f"Window details:\n{json.dumps(window_descriptions, indent=2)}\n\n"
        f"Active window: {ctx.get('active_window', 'unknown')}\n"
        f"Mouse position: ({ctx.get('mouse_x')}, {ctx.get('mouse_y')})\n\n"
        "Produce a unified, detailed description of the entire desktop state."
    )
    # This can be text-only (no image)
    final = query_vision("", synthesis_prompt)  # or use text-only endpoint

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "layout": layout,
        "windows": window_descriptions,
        "unified_description": final,
        "context": ctx,
    }
```

---

### 5. Expected Results and Quality

**What to expect from Qwen2.5-VL-72B on per-window crops:**

- **Code editors (VS Code, Neovim, etc.):** Near-complete transcription of visible code,
  correct identification of programming language, file name from tab, line numbers, syntax
  highlighting themes, and open terminal panels.
- **Web browsers:** Page title, URL bar content, main body text, navigation elements, images
  described by content, form fields with their labels and values.
- **Chat/messaging apps:** Conversation participants, message content (near-verbatim for
  visible messages), timestamps, unread indicators.
- **Terminal emulators:** Command history, current prompt, output text (especially effective
  since terminals have high-contrast text).
- **PDF viewers / document editors:** Document title, visible paragraphs transcribed, page
  numbers, formatting description.
- **Image editors / viewers:** Description of the image content, tool palette state, layer
  names if visible.

**Text accuracy expectations:**
- Large text (>16px at 4K): ~95-98% character accuracy
- Medium text (12-16px at 4K): ~90-95% accuracy
- Small text (8-12px at 4K): ~80-90% accuracy (benefits most from window cropping)
- Very small text (<8px at 4K): ~60-75% accuracy (may require 2x zoom crops)

---

### 6. Architectural Considerations for Future Classification

**Data schema for classification-ready descriptions:**

```json
{
  "id": "uuid",
  "timestamp": "2026-02-10T14:30:00Z",
  "description": "Unified text description...",
  "windows": [
    {"title": "...", "app": "...", "description": "..."}
  ],
  "active_window": "VS Code - arena/solution.md",
  "mouse_region": "center-right",
  "idle_seconds": 5,
  "label": null
}
```

**Classification architecture considerations:**

1. **Labeling scheme:** Define your client/project taxonomy upfront. Consider hierarchical
   labels: `client > project > activity_type` (e.g., `acme_corp > backend_api > code_review`).

2. **Feature extraction:** The unified text description is your primary feature. Consider
   also extracting:
   - Window title as a separate feature (high signal, low noise)
   - Application name list as a categorical feature
   - Time-of-day and day-of-week as contextual features

3. **Model options for classification:**
   - **Embedding + classifier:** Embed descriptions with a text embedding model, train a
     simple classifier (logistic regression, small MLP) on top. Fast, low-resource.
   - **Few-shot LLM classification:** Use the same Qwen2.5 model (text-only) with few-shot
     examples of labeled descriptions. Zero training needed, but slower inference.
   - **Fine-tuned small model:** Fine-tune a small LLM (e.g., Qwen2.5-3B) on your labeled
     descriptions. Best accuracy/speed trade-off for production.

4. **RL training considerations:** Once you have enough labeled data, you could fine-tune
   the classification model with reinforcement learning from your corrections. GRPO
   (Group Relative Policy Optimization) or DPO (Direct Preference Optimization) on a small
   model would be effective.

5. **Privacy:** All processing is local (Ollama), and you store only text descriptions,
   not screenshots. This is excellent for client confidentiality. Consider encrypting the
   description database and implementing per-client access controls.

6. **Throughput:** Processing one screenshot end-to-end (3 phases, 3-5 windows) takes
   approximately 60-120 seconds on the RTX PRO 6000. For periodic sampling (e.g., every
   5 minutes), this is well within budget. For continuous monitoring, consider processing
   only when window focus changes.

## CHANGES

This is a research and analysis deliverable. No code changes to the existing codebase are
required. The recommended implementation involves:

1. **New file: Screenshot capture and processing pipeline** (Python script using Pillow,
   requests, and the Ollama API)
2. **New file: NixOS configuration additions** for Ollama with CUDA and screenshot tools
3. **New file: GNOME extension data bridge** for window geometry and mouse activity export
4. **New file: Data storage schema** (SQLite or JSON-lines)

These would be implemented as a new project/module. The pseudocode in section 4 above
provides the core implementation blueprint.

### Ollama Setup Commands

```bash
# Pull the model (will download ~42GB)
ollama pull qwen2.5-vl:72b

# Verify it works with a test image
ollama run qwen2.5-vl:72b "Describe this image" --images /tmp/test_screenshot.png

# For NixOS configuration.nix:
# services.ollama = {
#   enable = true;
#   acceleration = "cuda";
#   environmentVariables = {
#     OLLAMA_MAX_LOADED_MODELS = "1";
#     OLLAMA_NUM_PARALLEL = "1";
#   };
# };
```

### Key Configuration for High-Resolution Processing

When using the Ollama API, the model's resolution handling is typically controlled by
the model's built-in configuration. To maximize resolution fidelity via the Ollama API:

1. Send images as **PNG** (not JPEG) to avoid compression artifacts
2. Send **native resolution crops** — do not pre-resize
3. The model will internally allocate visual tokens based on the image dimensions
4. For the Qwen2.5-VL model served through Ollama, the `max_pixels` parameter may need
   to be adjusted in the Modelfile if the default is too restrictive:

```
# Custom Modelfile for higher resolution support
FROM qwen2.5-vl:72b
PARAMETER num_ctx 32768
```

If Ollama does not expose the `max_pixels` parameter directly, the window-cropping
approach (Phase 2) inherently solves this by sending smaller, native-resolution images
that fall within the default pixel budget.
