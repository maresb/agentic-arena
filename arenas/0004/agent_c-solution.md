# Final Solution: Desktop Vision Model for Screenshot Classification

## PLAN — Numbered key decisions with rationale.

1.  **Model Selection: The 2026 Stack (Qwen3-VL + GLM-OCR)**
    *   **Primary VLM**: **Qwen3-VL-32B-Instruct**. Direct successor to Qwen2.5, optimized for GUI/OCR with 256K context.
    *   **Secondary OCR**: **GLM-OCR**. Specialized ~0.9B model for faithful document text extraction.
    *   **Quantization**: **Q8_0** for Qwen3-VL-32B. Fits comfortably in 96GB VRAM alongside the secondary model.

2.  **Preparation Strategy: Window-Aware Cropping with Selective Dual-Model Inference**
    *   **Step 0 (Verification)**: Run a "sanity check" with a single native 4K screenshot sent to Qwen3-VL. If it fails to read small text, proceed to the cropping pipeline.
    *   **Step 1 (Delta Check)**: Compute pHash of the screenshot. If unchanged, skip processing.
    *   **Step 2 (Global Layout)**: Resize full screenshot to ~1024px and ask Qwen3-VL for a high-level layout JSON.
    *   **Step 3 (Smart Cropping)**:
        *   Crop individual windows at **native resolution**.
        *   **Rounding**: Ensure dimensions are **multiples of 32**.
        *   **Edge Case**: If a window > ~2MP (e.g. maximized), split into tiles of **1920x1088** (32-aligned) with overlap.
    *   **Step 4 (Selective Dual Inference)**:
        *   **Qwen3-VL**: Always run for semantic understanding.
        *   **GLM-OCR**: Run *only* on **text-heavy windows** (Code, Terminal, Browser, PDF) to save compute. Skip on image-heavy windows.
        *   **Merge**: Use GLM-OCR's text as the authoritative transcript when available, but validate against VLM context.

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
            OLLAMA_MAX_LOADED_MODELS = "2"; # Critical for dual-model setup
            OLLAMA_NUM_PARALLEL = "1";
          };
        };
        ```
    *   **Platform**: Linux/NixOS. Use `pyvips` for efficient cropping.

## CHANGES — Unified diff or precise change descriptions.

Final consolidation of the architecture.

### revised_architecture_final_v3.md

1.  **Refined Selective OCR**: Explicitly defined the policy to run GLM-OCR only on specific window types (text-heavy) to optimize latency.
2.  **Risk Mitigation**: Added "OCR Over-Trust" checks (don't let OCR override semantic UI labels blindly).
3.  **Final Config**: Confirmed `OLLAMA_MAX_LOADED_MODELS="2"` is the required setting (correcting Agent B's error).
