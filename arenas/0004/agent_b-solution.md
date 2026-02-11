## PLAN — Numbered key decisions with rationale.
1. **Primary model: Qwen3-VL-32B Instruct** because it is the current (2026-02) successor line with improved GUI/OCR focus, long context, and Apache-2.0 licensing, while remaining practical on a single 96GB GPU.
2. **Secondary model: GLM-OCR** to maximize faithful text extraction for code/terminal/PDF-heavy windows; this directly mitigates the “downscaled → hallucinated text” failure mode.
3. **Resolution control first, tiling second:** explicitly control pixel budgets (min/max pixels or resized dims) and use window-aware crops; only tile when a crop still exceeds budget.
4. **Structured, conservative outputs:** JSON-only responses, explicit “[illegible]” markers, and JSON repair/retry to reduce hallucination and parsing failures.
5. **Classification-ready storage:** store text + metadata + deltas (no screenshots) to enable future labeling and RL without large image retention.

## CHANGES — Unified diff or precise change descriptions.
- Updated arena report files:
  - arenas/0004/agent_b-solution.md
  - arenas/0004/agent_b-analysis.md

## REPORT

### 1) Model selection (as of 2026-02-10)
**Primary:** Qwen3-VL-32B Instruct (Ollama: `qwen3-vl:32b`)  
**Secondary OCR specialist:** GLM-OCR (Ollama: `glm-ocr`)

**Why Qwen3-VL-32B**
- Newer Qwen3-VL line (2025/2026) targets GUI understanding + OCR and supports long context (~256K).
- Apache-2.0 license is simpler for consulting work.
- 32B is fast and stable on 96GB VRAM while allowing larger visual token budgets.

**What practitioners report (high-level)**
- Qwen3-VL is strong on OCR and GUI tasks when image resizing is controlled, but is sensitive to silent downscaling.
- Zooming or tiling improves fine-text accuracy compared to one-shot full-frame inference.

**Why GLM-OCR**
- OCR-first multimodal model with layout + recognition architecture.
- Ideal for dense text (terminal logs, IDEs, PDFs) where VLMs tend to hallucinate.
- Small, fast, Apache-2.0; can run alongside Qwen3-VL.

**When to use which**
- Qwen3-VL: global layout, window/app identification, UI element understanding, images/graphs.
- GLM-OCR: text-heavy windows where verbatim extraction matters.

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

### 3) Resolution controls (critical)
Most runtimes enforce a pixel budget. You must set one of:
- **min_pixels / max_pixels**, or
- **explicit resized_width/resized_height**.

For Qwen3-VL, resized dimensions should be **multiples of 32**. If you resize manually, disable any further resizing in the processor to avoid double-scaling.
If you use a helper like `qwen-vl-utils` for resizing, ensure the model processor does not apply a second resize.

**Recommended budgets to test**
- **B = 2.1 MP** (about 1920x1088) for speed and good UI text.
- **B = 4.2 MP** (about 2048x2048) for very small text and dense code.

### 4) Screenshot preparation and chunking

#### Step 0 — Native 4K sanity check
Send one full-resolution screenshot and ask for a few known tiny text strings.  
If it reads them correctly, full-image processing might be viable.  
If not, follow the multi-pass workflow below.

#### Phase 1 — Global layout pass (low-res)
- Resize full frame to a modest budget (short side 1024–1536).
- Prompt for layout only (windows, rough positions, app types).

#### Phase 2 — Window-level detail (preferred)
1. Obtain window rectangles (x, y, w, h) and z-order from GNOME.
2. Crop each visible window at native resolution.
3. Skip minimized or fully occluded windows; prioritize active window + top N.
4. If a window crop **exceeds your pixel budget**, tile within that window.

**Maximized window edge case**
- If a maximized window is still too large, split into **two vertical tiles**
  (left/right) with **10–12% overlap**.

#### Phase 2 (fallback) — Grid tiling (no geometry)
Use landscape tiles that align with Qwen3-VL’s multiple-of-32 constraint:
- **Tile size:** 1920x1088 (both divisible by 32)
- **Overlap:** ~10% (rounded to multiples of 32)

**Tile counts**
- 3840x2160 → 2x2 (4 tiles)
- 5120x2880 → 3x3 (9 tiles)
- 7680x4320 → 4x4 (16 tiles)

#### Merging per-tile outputs
1. Normalize text (whitespace, punctuation).
2. Deduplicate overlap using string similarity; keep the longer, cleaner line.
3. Aggregate in reading order (top-to-bottom, left-to-right).
4. Optionally run a text-only summarization pass for a compact description.

### 5) Structured outputs (conservative)
**Qwen3-VL output JSON**
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
- Use Ollama `format: "json"` if available.
- Validate + repair JSON, retry up to 2 times.

**GLM-OCR output**
- Store OCR text separately and use it to verify or replace low-confidence text blocks.
- If Qwen3-VL and GLM-OCR disagree, prefer GLM-OCR for verbatim text but keep Qwen3-VL’s UI/semantic summary.

### 6) Supplementary tools/workflows
- **Capture:** `gnome-screenshot` or GNOME D-Bus screenshot portal (Wayland-safe).
- **Geometry:** GNOME extension or `gdbus` into Mutter (`global.get_window_actors()`).
- **Image processing:** `pyvips` (preferred) or OpenCV.
- **Storage:** SQLite + FTS or JSONL with metadata (active window title, mouse, idle time).
- **Delta hashing:** pHash to skip unchanged frames.

### 7) Expected results
- High-fidelity text for normal UI sizes with window crops + OCR specialist.
- Greatly reduced hallucination risk due to explicit pixel control and conservative prompts.
- Stable, compact text records suitable for downstream classification.

### 8) Architectural considerations for future classification
- **Session segmentation:** group by active window + idle gaps.
- **Hierarchical labels:** client → project → activity.
- **Feature set:** window titles, domains, file paths, OCR text blocks.
- **Human-in-the-loop:** periodic review for drift and label correction.
