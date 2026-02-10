## PLAN
1. **Select Qwen2.5-VL-72B Instruct** (fallback: Qwen2-VL-72B or InternVL2.5-78B) for best open-weights OCR/UI performance on local hardware.
2. **Verify downscaling behavior first** with a native 4K sanity check, then **prefer window-aware crops** to preserve text legibility and semantic boundaries.
3. **Use a two-pass workflow** (global low-res layout + high-res per-window extraction) with an optional text-only synthesis pass.
4. **Emit structured JSON** that avoids pixel-precise bboxes and includes JSON reliability measures (format hints, repair, retries).
5. **Optimize for classification** via delta storage, session segmentation, and metadata (active window title, mouse, idle time).

## CHANGES
- Added revised arena report files:
  - arenas/0004/01-3-revise-agent_b-solution.md
  - arenas/0004/01-3-revise-agent_b-analysis.md

## REVISED REPORT

### 1) Model selection
**Primary:** Qwen2.5-VL-72B Instruct  
**Fallbacks:** Qwen2-VL-72B Instruct; InternVL2.5-78B (if Qwen is unavailable or underperforms)

**Why**
- Strong OCR + UI understanding in open-weight models.
- Dynamic resolution + multi-image support fits tiling/cropping workflows.
- Feasible on 96GB VRAM with Q4/Q5 quantization.

### 2) Hardware + quantization guidance
- **Start with Q4_K_M**, move to **Q5_K_M** if OCR accuracy is insufficient.
- **Q8_0** is only advisable for smaller crops; it can be tight on full 4K when visual KV cache is included.
- Use **temperature=0** for deterministic, low-hallucination output.

### 3) Screenshot preparation and workflow

#### Step 0 — Native 4K sanity check (fast gate)
Send one full-resolution screenshot and ask for a few known tiny text strings.  
If it reads them correctly, you can attempt full-image processing.  
If it fails (common with default pixel budgets), use the multi-pass workflow below.

#### Phase 1 — Global layout (low-res, full screen)
- Downscale the screenshot so the short side is ~1024-1536.
- Prompt for **layout only** (windows, positions, app types), not detailed text.
- Example prompt (JSON-only):
  - "Describe the desktop layout as JSON. For each visible window, provide approximate
    position (top-left/top-right/center/bottom-left/bottom-right/maximized) and app type.
    Do not attempt to read small text."

#### Phase 2 — High-res detail (window-aware crops; preferred)
1. Get window geometry (x, y, width, height) from your GNOME extension or `gdbus`.
2. Crop each visible window from the original full-resolution screenshot (PNG).
3. Prioritize **active window + top N visible windows**; skip minimized or fully occluded windows if z-order is available.
4. If a window is too large for the runtime, sub-tile **within that window**.

**Why window crops are best:** they preserve semantics (one app per crop), keep text readable, and avoid arbitrary splits across UI elements.

**Per-window prompt (JSON-only, anti-hallucination):**
- "The active window title is '{title}'. Respond with JSON only. Extract:
  - app
  - text_lines (array of strings, verbatim)
  - ui_elements (array of {type, label, region})
  - summary (1-2 sentences)
  Only describe what is clearly visible. Use '[illegible]' for unclear text."

#### Phase 2 (fallback) — Grid tiling (when window geometry is unavailable)
Use landscape tiles to match desktop aspect ratio:
- **Tile size:** 1920x1080 (16:9)
- **Overlap:** 10-12%

**Tile counts**
- 3840x2160: 2x2 tiles (4 total)
- 5120x2880: 3x3 tiles (9 total)

#### Phase 3 — Text-only synthesis (optional)
If you need a single unified description, merge the layout summary with per-window (or per-tile) outputs in a text-only pass. For early prototypes, store per-window JSON as-is.

### 4) Structured outputs (robust schema without pixel-precise bboxes)
Use GNOME geometry for window bounds and only coarse regions in the model output:
```
{
  "window": {
    "title": "VS Code — project",
    "app": "code",
    "bbox": [x, y, width, height]
  },
  "text_lines": [
    {"line": "def process_frame(...):", "region": "center-left"},
    {"line": "[illegible]", "region": "footer"}
  ],
  "ui_elements": [
    {"type": "tab", "label": "main.py", "region": "top"},
    {"type": "button", "label": "Run", "region": "top-right"}
  ],
  "summary": "Editing Python code in VS Code."
}
```

**JSON reliability**
- Use Ollama `format: "json"` when available.
- Validate + repair JSON on parse failure, and retry once or twice.

### 5) Merge and deduplication
- **Window crops:** no merge needed beyond combining per-window outputs.
- **Grid tiles:** dedupe by text similarity; keep the longest non-truncated line.
- Avoid pixel IoU dedupe; VLM spatial accuracy is unreliable.

### 6) Supplementary tools and workflow
- **Capture:** `gnome-screenshot` or GNOME Shell screenshot D-Bus API (Wayland-safe).
- **Geometry:** GNOME extension or `gdbus` to `global.get_window_actors()`.
- **Image processing:** `pyvips` (preferred) or OpenCV.
- **Optional OCR cross-check:** Tesseract or RapidOCR for critical text.
- **Storage:** SQLite/JSONL with FTS + metadata (active window title, mouse, idle time).

### 7) Expected results
- High accuracy on typical UI text (12-16px+) with window crops.
- Small or low-contrast text may need sub-tiling or OCR cross-checking.
- Hallucinations drop significantly with strict prompts + temperature=0.

### 8) Architectural considerations for classification
- **Session segmentation:** group by active window and idle gaps.
- **Delta storage:** store only changes between frames.
- **Hierarchical labels:** client -> project -> activity.
- **Privacy:** store text + metadata only; keep screenshots transient.
