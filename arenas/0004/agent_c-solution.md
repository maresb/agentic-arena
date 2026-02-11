# Final Solution: Desktop Vision Model for Screenshot Classification

## PLAN — Numbered key decisions with rationale.

1.  **Model Selection: The 2026 Stack (Qwen3-VL + GLM-OCR)**
    *   **Primary VLM**: **Qwen3-VL-32B-Instruct**. This is the direct successor to the Qwen2.5 line, explicitly optimized for GUI understanding and OCR, with a 256K context window.
    *   **Secondary OCR**: **GLM-OCR**. A specialized ~0.9B model for faithful document text extraction. We will run this in parallel on text-heavy windows to cross-validate the VLM's output and prevent hallucination.
    *   **Quantization**: **Q8_0** (~34GB) for Qwen3-VL. With a 32B model on a 96GB card, we have abundant VRAM to run at near-lossless precision, leaving ~60GB for the KV cache and the secondary model.

2.  **Preparation Strategy: Window-Aware Cropping with Dual-Model Inference**
    *   **Step 0 (Verification)**: Run a "sanity check" with a single native 4K screenshot sent to Qwen3-VL. If it fails to read small text, proceed to the cropping pipeline.
    *   **Step 1 (Delta Check)**: Compute pHash of the screenshot. If unchanged, skip processing.
    *   **Step 2 (Global Layout)**: Resize full screenshot to ~1024px and ask Qwen3-VL for a high-level layout JSON.
    *   **Step 3 (Smart Cropping)**:
        *   Crop individual windows at **native resolution** using GNOME metadata.
        *   **Rounding**: Ensure all crop dimensions are multiples of 32 (e.g., resize slightly if needed) to match Qwen3-VL's patch requirement.
        *   **Edge Case**: If a window > ~2MP (e.g. maximized), split into tiles of **1920x1088** (32-aligned) with overlap.
    *   **Step 4 (Dual Inference)**:
        *   Send crop to **Qwen3-VL** for semantic understanding ("What is this app? What is the user doing?").
        *   Send crop to **GLM-OCR** for verbatim text extraction.
        *   Merge results: Use GLM-OCR's text as the authoritative transcript.

3.  **Data Structure**
    *   **Schema**:
        ```json
        {
          "timestamp": "ISO8601",
          "delta": "full|partial|none",
          "layout": "string",
          "windows": [
            {
              "title": "VS Code - Project",
              "app": "code",
              "region": "top-left",
              "semantic_summary": "Editing Python script",
              "extracted_text": "def main(): ...", // sourced from GLM-OCR
              "ui_elements": ["sidebar", "terminal"]
            }
          ]
        }
        ```

4.  **Hardware & Implementation Specifics**
    *   **NixOS Config**:
        ```nix
        services.ollama = {
          enable = true;
          acceleration = "cuda";
          environmentVariables = {
            OLLAMA_MAX_LOADED_MODELS = "2"; # Allow Qwen3 + GLM-OCR
            OLLAMA_NUM_PARALLEL = "1";
          };
        };
        ```
    *   **Platform**: Linux/NixOS (GNOME). Use `pyvips` for efficient cropping.

## CHANGES — Unified diff or precise change descriptions.

The architecture has been completely updated from the previous Qwen2.5-VL single-model approach.

### revised_architecture_final_v2.md

1.  **Models**:
    *   Replaced `qwen2.5-vl:72b` with `qwen3-vl:32b`.
    *   Added `glm-ocr` as a secondary model.
2.  **Pipeline**:
    *   **Dual-Path**: Added logic to query both models for each window crop.
    *   **Tiling**: Updated default tile size to **1920x1088** (multiples of 32) instead of 1920x1080.
3.  **Config**:
    *   Updated `OLLAMA_MAX_LOADED_MODELS` to 2.
    *   Updated quantization recommendation to Q8_0.
4.  **Storage**:
    *   Added specific fields for `semantic_summary` (VLM) vs `extracted_text` (OCR).
