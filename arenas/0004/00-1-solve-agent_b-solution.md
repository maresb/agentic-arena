## PLAN — Numbered key decisions with rationale.
1. Select Qwen2.5-VL-72B (or Qwen2-VL-72B if 2.5 is unavailable in Ollama) because it is one of the strongest open vision-language models for OCR and UI/document understanding while remaining feasible on a 96GB GPU with quantization.
2. Use a two-pass capture strategy (global downscaled view plus high-res tiles) to preserve layout context while keeping text legible, avoiding the downscaling hallucination problem you observed.
3. Require structured, tile-level outputs with coordinates to enable deterministic merging, deduplication, and later classification without storing raw screenshots.
4. Store only text, layout metadata, and session context (active window title, app, mouse activity) to reduce storage and to prepare for future classification and RL workflows.

## CHANGES — Unified diff or precise change descriptions.
- Added report files:
  - arenas/0004/00-1-solve-agent_b-solution.md
  - arenas/0004/00-1-solve-agent_b-analysis.md

## REPORT
### 1) Model selection (primary recommendation)
**Model:** Qwen2.5-VL-72B Instruct  
**Fallback if not available in Ollama:** Qwen2-VL-72B Instruct

**Why this model**
- **State-of-the-art open performance:** In recent public benchmarks and community reports, the Qwen2.x-VL line consistently leads or is near the top on OCR-heavy and document-focused tasks (TextVQA, DocVQA, ChartQA, UI understanding), which directly matches your goal of accurate screen reading.
- **High-resolution handling:** The Qwen2.x-VL family supports dynamic image sizes and multi-image inputs, making it practical to feed tiled screenshots and preserve small UI text.
- **Hardware fit:** A 72B model is large but feasible on a 96GB GPU with quantization (Q4 or Q5) in Ollama/gguf-style runtimes, leaving headroom for KV cache and multiple images per request.
- **Strong text recognition:** Community usage notes highlight that Qwen2.x-VL produces fewer OCR hallucinations than earlier LLaVA variants when given high-res tiles and explicit OCR prompts.

**What people say about it (summary of public sentiment)**
- Frequently cited as one of the best open models for real-world OCR and document understanding.
- Praised for consistency in structured extraction (tables, UI labels, menu items) when prompts request verbatim text.
- Common caveat: it still benefits greatly from high-res tiling and explicit OCR-oriented prompting; downscaled full-screen images can degrade accuracy.

### 2) Detailed specifications (verify exact values for the Ollama build)
**Model family:** Qwen2.5-VL (fallback: Qwen2-VL)  
**Parameter size:** ~72B parameters  
**Vision backbone:** large ViT/CLIP-style encoder (multi-scale, patch-based)  
**Context length:** typically 32k to 128k tokens depending on the exact build  
**Image input:** dynamic resolution; supports multi-image inputs; internally converts images to patch tokens  
**Strengths:** OCR, doc/UI understanding, chart and table reading, multi-image reasoning  
**Weaknesses:** high latency; needs quantization for consumer GPUs; still sensitive to downscaling

**Hardware guidance on RTX PRO 6000 Blackwell Max-Q (96GB)**
- **Recommended quantization:** Q4_K_M or Q5_K_M (Q6+ if you prefer quality and latency allows).
- **Rough VRAM use:** 72B Q4 is typically ~36-45GB model weights; expect additional memory for KV cache and image tokens. Your 96GB is ample for multi-tile batches.
- **Batching:** You can send several tiles per call, but keep an eye on total image tokens and context length.

### 3) Alternative models (when to choose them)
- **InternVL2.5-76B:** Often competitive or better on some OCR/document benchmarks. Choose if you find Qwen2.5-VL not available or underperforming on your data.
- **LLaVA-OneVision-72B:** Strong general reasoning and multi-image performance, but OCR can be slightly less reliable than Qwen2.x-VL/InternVL2.x.
- **Qwen2.5-VL-14B or 7B:** If you need lower latency or higher throughput at the cost of reduced OCR fidelity.

### 4) Screenshot preparation and tiling strategy
**Why tiling is needed:** Full 4K (3840x2160) images downscaled to a model’s max input (often around 1024 to 1536 on the short side) can make UI text illegible. Tiling keeps text at native or near-native scale.

**Recommended strategy (two-pass)**
1. **Global pass (layout):** Downscale full screenshot so the short side is 1024-1536. Ask for a high-level layout summary (windows, panels, main regions).
2. **Tile pass (OCR/detail):** Split the original screenshot into overlapping tiles and run OCR-focused prompts per tile.

**Tile sizing**
- Start with **tile size 1344x1344** (or 1280x1280) for high-fidelity text.
- Use **10-15% overlap** to avoid text being cut at tile boundaries.
- If latency is too high, drop to **1024x1024** and increase overlap slightly (12-18%).

**Example for 3840x2160 (tile = 1344, overlap = 12%)**
- Stride = 1344 * (1 - 0.12) = 1182  
- Horizontal tiles = ceil((3840 - 1344) / 1182) + 1 = 4  
- Vertical tiles = ceil((2160 - 1344) / 1182) + 1 = 2  
- **Total tiles = 8**

**If you upgrade to 5120x2880**
- With the same 1344 tile and 12% overlap:
  - Horizontal tiles = ceil((5120 - 1344) / 1182) + 1 = 5  
  - Vertical tiles = ceil((2880 - 1344) / 1182) + 1 = 3  
  - **Total tiles = 15**

**Do tiles need to overlap?**
Yes. Overlap prevents word splits and yields better OCR continuity. 10-15% is a solid default.

### 5) How to merge tile outputs into a single description
**Prompt each tile to output structured JSON**, for example:
```
{
  "tile_bbox": [x0, y0, x1, y1],
  "text_blocks": [
    {"text": "...", "bbox": [x0, y0, x1, y1], "confidence": 0.0-1.0}
  ],
  "ui_elements": [
    {"type": "button|menu|tab|input|icon", "label": "...", "bbox": [...]}
  ],
  "summary": "Short summary of this tile"
}
```

**Merging workflow**
1. Convert tile-relative bboxes to global coordinates using the tile origin.
2. Deduplicate text blocks by:
   - bbox overlap (IoU threshold, e.g., > 0.6), and
   - text similarity (e.g., normalized Levenshtein > 0.9).
3. Keep the higher-confidence block when duplicates overlap.
4. Combine tile summaries into a global summary using the global layout pass as a guide.

### 6) Supplementary tools and workflow components
**Capture**
- GNOME screenshot tools: `gnome-screenshot` or the GNOME Shell screenshot API.
- Your extension’s active-window title and mouse-activity signals should be stored alongside the screenshot metadata.

**Preprocessing**
- **pyvips** or **OpenCV** for fast, memory-efficient tiling and resizing.
- Save **lossless PNG** to avoid compression artifacts.

**Postprocessing**
- Optional secondary OCR (Tesseract or RapidOCR) for cross-checking critical text.
- Use SQLite (with FTS) or a lightweight document store to save text, layout, and session metadata.

### 7) Expected results and quality notes
- With proper tiling, you should get **near-verbatim text** for normal UI font sizes (12-16px and above).
- Small or low-contrast text may still be imperfect; overlap and slightly larger tiles help.
- A two-pass approach (global layout + tiles) significantly reduces hallucination compared to downscaling a full 4K image.

### 8) Architectural considerations for future classification
- **Session segmentation:** group events by active window/app and idle gaps to build coherent activity segments.
- **Delta storage:** store only text/layout diffs between consecutive frames to reduce storage and improve training signal.
- **Hierarchical labeling:** first classify high-level category (client A vs personal), then subtask, then intent.
- **Privacy:** keep all processing local; consider redaction rules for secrets (tokens, passwords).
- **Human-in-the-loop:** periodically sample segments for manual review to catch drift and refine labeling.
