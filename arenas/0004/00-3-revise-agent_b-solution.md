## PLAN
1. **Select Qwen2.5-VL-72B Instruct (fallback: Qwen2-VL-72B or InternVL2.5-78B)** because it is the strongest open OCR/UI model that runs locally on a 96GB GPU with quantization and supports dynamic image sizes.
2. **Prefer window-aware cropping** using GNOME window geometry to preserve text legibility and keep semantic units intact; use grid tiling only as a fallback.
3. **Use a two-pass workflow** (global low-res layout + high-res window crops) with an optional text-only synthesis step; add a quick “native 4K sanity check” to decide if downscaling is occurring.
4. **Use structured, robust outputs** that avoid pixel-precise bboxes and instead rely on ordered text lines and approximate regions to reduce hallucinated spatial data.
5. **Reduce storage and future classification friction** by storing only text + metadata and delta changes between frames.

## CHANGES
- Added revised arena report files:
  - arenas/0004/00-3-revise-agent_b-solution.md
  - arenas/0004/00-3-revise-agent_b-analysis.md

## REVISED REPORT

### 1) Model selection (primary recommendation)
**Primary:** Qwen2.5-VL-72B Instruct  
**Fallbacks:** Qwen2-VL-72B Instruct; InternVL2.5-78B (if Qwen is unavailable or underperforms on your screens)

**Why this model**
- **Top-tier OCR + UI understanding** among open-weights models, which is the critical requirement for reading screen text accurately.
- **Dynamic resolution** and multi-image support, which lets you feed tiles or window crops without forcing a single fixed size.
- **Practical on a 96GB GPU** with Q4/Q5 quantization, leaving headroom for visual KV cache and multiple image inputs.

**What people say (high-level, not benchmark-anchored)**
- Frequently recommended by local VLM users for OCR-heavy tasks (documents, UI, charts).
- Generally more reliable on text extraction than older LLaVA-class models when given high-res crops and explicit “verbatim text” prompts.
- Still sensitive to downscaling or overly compressed inputs; most users prefer cropping/tiling for 4K+ screens.

### 2) Model specifications (verify exact values in your Ollama build)
- **Size:** ~72B parameters  
- **Context length:** typically 32k+ (some builds support larger)  
- **Vision encoder:** ViT/SigLIP-like backbone with patch tokens  
- **Image input:** dynamic resolution with an internal pixel budget (often configurable in the model/runtime)

**Key caution:** Ollama (or the model’s processor) may apply a **max_pixels** cap. If the cap is low (e.g., ~1M pixels), a 4K image will be downscaled. This is the most likely cause of hallucination from illegible text.

### 3) Hardware + quantization guidance (RTX PRO 6000 Blackwell 96GB)
- **Recommended starting quantization:** Q4_K_M (or Q5_K_M if you want higher fidelity and can tolerate extra VRAM and latency).
- **Q8_0** is feasible for *smaller crops* but can be tight for **full 4K** due to visual KV cache; test before committing.
- Use **temperature=0** and short max output limits for deterministic, low-hallucination extraction.

### 4) Screenshot preparation and workflow

#### Step 0 — Quick sanity check (native 4K)
Run one full-resolution screenshot and ask for a few tiny text strings you can verify.  
If it reads them correctly, you may be able to process full images without heavy chunking.  
If it fails (common with default pixel budgets), proceed with the multi-pass workflow below.

#### Phase 1 — Global layout (low-res, full screen)
- Downscale the full screenshot so the short side is ~1024-1536.
- Prompt for **layout only** (windows, positions, app types), not for text.
- Output: JSON with window regions and a short layout summary.

#### Phase 2 — High-res detail (window-aware crops; preferred)
1. Collect window geometry (x, y, width, height) via your GNOME extension or `gdbus`.
2. Crop each visible window from the original full-resolution screenshot.
3. Send each crop at native resolution (PNG).
4. If a window crop is still too large for your runtime, sub-tile **within that window** using the same grid fallback below.

**Why window crops are best:** they preserve semantics (one app per crop), keep text readable, and avoid arbitrary splits across UI elements.

#### Phase 2 (fallback) — Grid tiling (when window geometry is unavailable)
Use **landscape tiles** to match desktop aspect ratio and reduce tile count:
- **Tile size:** 2048x1152 (16:9)
- **Overlap:** 10-12% (prevents line splits)
- **Stride:** tile_size * (1 - overlap)

**Tile counts (example)**
- For **3840x2160** with 2048x1152 and 10% overlap:
  - Horizontal tiles = ceil((3840 - 2048) / 1843) + 1 = 2  
  - Vertical tiles = ceil((2160 - 1152) / 1037) + 1 = 2  
  - **Total tiles: 4**
- For **5120x2880** with the same settings:
  - Horizontal tiles = ceil((5120 - 2048) / 1843) + 1 = 3  
  - Vertical tiles = ceil((2880 - 1152) / 1037) + 1 = 3  
  - **Total tiles: 9**

#### Phase 3 — Text-only synthesis (optional)
If you need a single unified description, run a text-only pass that merges the layout summary + per-window (or per-tile) descriptions into a single report.

### 5) Structured output format (robust, no pixel-precise bboxes)
Use a JSON schema that avoids fragile pixel coordinates. Example:
```
{
  "window": {
    "title": "VS Code — project",
    "app": "code",
    "bbox": [x, y, width, height]   // from GNOME, not the model
  },
  "text_lines": [
    {"line": "import numpy as np", "region": "top-left"},
    {"line": "def process_frame(...):", "region": "center-left"}
  ],
  "ui_elements": [
    {"type": "tab", "label": "main.py", "region": "top"},
    {"type": "button", "label": "Run", "region": "top-right"}
  ],
  "summary": "Editor showing Python code and a file tree."
}
```

**Why this works:** it gives deterministic structure for downstream classification without relying on the model to invent precise bboxes.

### 6) Merge and deduplication strategy
- **Window crops:** no merge needed beyond combining per-window outputs.
- **Grid tiles:** dedupe by text similarity (normalized Levenshtein or token Jaccard).  
  Avoid pixel IoU since spatial coordinates are unreliable.
- If overlap produces near-duplicate lines, keep the most complete line (longest non-truncated).

### 7) Supplementary tools / workflow
- **Capture:** `gnome-screenshot` (Wayland-safe), or GNOME Screenshot D-Bus API.
- **Window geometry:** GNOME extension or `gdbus` query to Mutter.
- **Image processing:** `pyvips` (fast, low memory) or OpenCV for crops/tiles.
- **Post-processing:** optional OCR cross-check (Tesseract or RapidOCR) for critical text.
- **Storage:** SQLite + FTS or JSONL with per-window records + timestamps + active window title + mouse activity.

### 8) Expected results
- High accuracy on normal UI text (12-16px+), especially from window crops.
- Small or low-contrast text may need sub-tiling or OCR cross-checking.
- Hallucinations drop significantly when you avoid aggressive downscaling and use strict prompts.

### 9) Architectural considerations for classification
- **Session segmentation:** group events by active window and idle gaps.
- **Delta storage:** store only differences between consecutive snapshots.
- **Hierarchical labels:** client -> project -> activity.
- **Privacy:** keep raw screenshots transient; store only text + metadata.
