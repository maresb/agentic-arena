## PLAN — Numbered key decisions with rationale.

1.  **Model Selection: Qwen2.5-VL-72B-Instruct**
    *   **Rationale**: Unanimous consensus across all agents. This model currently offers the best balance of open-weights availability, OCR capability, and dynamic resolution handling.
    *   **Quantization**: I recommend starting with **Q4_K_M** (approx. 43GB weights) as the safe baseline. While my initial proposal for Q8_0 (77GB) is theoretically possible on a 96GB card, Agent A's critique regarding the visual token KV cache overhead (~20-26GB for 4K) is valid and makes Q8_0 risky or impossible for full-resolution tasks. Q4_K_M leaves ample headroom for the KV cache and concurrent system processes.

2.  **Screenshot Preparation: Window-Aware Cropping (Primary) + Global Context**
    *   **Adopted from Agent A**: Instead of feeding the full 4K image (risking internal downscaling) or using arbitrary grid tiles (Agent B), we will leverage the user's existing GNOME extension data to crop individual windows.
    *   **Rationale**: Windows are the semantic units of a desktop. Cropping ensures:
        *   **Native Resolution**: Each window is processed at its exact pixel dimensions (e.g., 1920x1080), which fits comfortably within the model's patch limits without downscaling.
        *   **Efficiency**: We avoid processing empty wallpaper space.
        *   **Context**: We explicitly know which application belongs to which image crop.
    *   **Global Pass**: We will perform a single low-res "Global Layout" pass (Agent A's suggestion) to capture the overall arrangement, but rely on the high-res crops for the actual text extraction.

3.  **Data Structure & Classification Readiness**
    *   **Adopted from Agent B**: We will strictly enforce a JSON schema for the output. Free-text descriptions are too difficult to merge.
    *   **Schema**:
        ```json
        {
          "window_title": "string",
          "app_name": "string",
          "visible_text": ["string"],
          "ui_elements": [{"type": "button", "label": "Save", "location": "bottom-right"}],
          "activity_summary": "string"
        }
        ```
    *   **Storage**: Store the structured JSON + embeddings. Do not store the raw screenshots.

4.  **Hardware & Implementation Specifics**
    *   **Ollama Configuration**: We must verify and potentially increase `num_ctx` (context window) to support the visual tokens of multiple window crops if processed in a single conversation context (though stateless processing per window is preferred).
    *   **Platform**: Linux/NixOS. We will assume `gnome-screenshot` or `scrot` for capture, and `gdbus` or the existing extension for window geometry.

## CHANGES — Unified diff or precise change descriptions.

No code changes are required for this research task. The solution involves a new architectural approach:

### revised_architecture.md

1.  **Input**:
    *   `screenshot.png` (3840x2160)
    *   `metadata.json` (from GNOME extension: list of windows with `{id, title, x, y, width, height}`)

2.  **Process**:
    *   **Step 1: Global Context**
        *   Resize `screenshot.png` to max 1024px dimension.
        *   Prompt: "Describe the visible applications and their layout."
    *   **Step 2: Smart Cropping**
        *   For each window in `metadata.json`:
            *   Crop `screenshot.png` using `x,y,w,h`.
            *   **Skip** if window is minimized or fully occluded (calculated via Z-order if available, otherwise process top 3 largest).
            *   Prompt (Qwen2.5-VL-72B-Q4_K_M): "Extract all text and describe the UI state of this window: '{title}'."
    *   **Step 3: Synthesis**
        *   Combine Global Description + List of Window Descriptions into a single JSON record.

3.  **Output**:
    *   Store in `sqlite` or `vector_db`:
        *   Timestamp
        *   Global Summary
        *   List of Window Records (Schema defined above)
        *   Embedding of the consolidated text.
