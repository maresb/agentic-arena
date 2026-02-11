## PLAN
1. **Select Qwen2.5-VL-72B Instruct** for strongest open OCR/UI performance; keep a minimal fallback only if Qwen is unavailable.
2. **Verify downscaling behavior first** (native 4K sanity check), then use **window-aware crops** to preserve text fidelity.
3. **Use a two-pass workflow** (global low-res layout + high-res per-window extraction) with optional text-only synthesis.
4. **Emit structured JSON** (no pixel-precise bboxes) with JSON reliability measures (format, repair, retry).
5. **Optimize for classification** via delta hashing, session segmentation, and rich metadata (window title, app, mouse, idle time).

## CHANGES
- Added revised arena report files:
  - arenas/0004/agent_b-solution.md
  - arenas/0004/agent_b-analysis.md

## REVISED REPORT

### 1) Model selection
**Primary:** Qwen2.5-VL-72B Instruct  
**Fallback (only if Qwen is unavailable):** InternVL2.5-78B

**Quantization guidance**
- Start with **Q4_K_M** for safety and headroom.
- Test **Q5_K_M** if OCR accuracy is insufficient.
- **Q8_0** is only advisable for small crops; it can be tight for full 4K due to visual KV cache.

### 2) NixOS setup (Ollama + CUDA)
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

### 3) Workflow

#### Step 0 — Native 4K sanity check
Send one full-resolution screenshot and ask for a few known tiny text strings.  
If it reads them correctly, full-image processing may be viable.  
If it fails (common with default pixel budgets), use the multi-pass workflow below.

#### Phase 1 — Global layout (low-res, full screen)
- Downscale so the short side is ~1024–1536.
- Prompt for layout only (no detailed text).
- Example prompt (JSON-only):
  - "Describe the desktop layout as JSON. For each visible window, provide approximate
    position (top-left/top-right/center/bottom-left/bottom-right/maximized) and app type.
    Do not attempt to read small text."

#### Phase 2 — High-res detail (window-aware crops; preferred)
1. Use GNOME geometry (extension or `gdbus`) to get window bounds and z-order.
2. Crop each visible window from the original full-res screenshot.
3. Skip minimized or fully occluded windows; prioritize the active window and top N visible windows.
4. If a **maximized window** still gets downscaled, **split it into two vertical tiles**
   with 10–12% overlap.

**Per-window prompt (JSON-only, anti-hallucination):**
- "The active window title is '{title}'. Respond with JSON only. Extract:
  - app
  - text_lines (array of strings, verbatim)
  - ui_elements (array of {type, label, region})
  - summary (1–2 sentences)
  Only describe what is clearly visible. Use '[illegible]' for unclear text."

#### Phase 2 (fallback) — Grid tiling (if geometry is unavailable)
- Use **landscape tiles** to match 16:9:
  - **Tile size:** 1920x1080
  - **Overlap:** 10–12%
- Tile counts:
  - 3840x2160 → 2x2 (4 tiles)
  - 5120x2880 → 3x3 (9 tiles)

#### Phase 3 — Text-only synthesis (optional)
If a single unified description is needed, merge the layout summary with per-window (or per-tile) JSON in a text-only pass. For early prototypes, store per-window JSON as-is.

### 4) Structured output (robust schema, no pixel-precise bboxes)
```
{
  "window": {
    "title": "VS Code — project",
    "app": "code",
    "bbox": [x, y, width, height]   // from GNOME, not the model
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
- Use Ollama `format: "json"` if available.
- Validate/repair JSON on parse failure; retry once or twice.

### 5) Merge and deduplication
- **Window crops:** no merge needed beyond combining per-window outputs.
- **Grid tiles:** dedupe by text similarity; keep the longest non-truncated line.
- Avoid pixel IoU dedupe; VLM spatial accuracy is unreliable.

### 6) Supplemental tools
- **Capture:** `gnome-screenshot` or GNOME Shell screenshot D-Bus API (Wayland-safe).
- **Geometry:** GNOME extension or `gdbus` to `global.get_window_actors()`.
- **Image processing:** `pyvips` (preferred) or OpenCV.
- **Optional OCR cross-check:** Tesseract or RapidOCR for critical text.

### 7) Classification-ready storage
- Use **delta hashing** (pHash) to skip unchanged frames.
- Store per-window records + metadata (active window title, mouse, idle time).
- Use SQLite + FTS or JSONL for searchable, compact storage.

### 8) Expected results
- Strong text fidelity on typical UI sizes (12–16px+) with window crops.
- Small/low-contrast text may need sub-tiling or OCR cross-check.
- Hallucinations drop substantially with strict prompts + temperature=0.
