## PLAN

1.  **Model Selection & Analysis**:
    *   Selected **Qwen2.5-VL-72B-Instruct** (or the latest Qwen-VL variant available on Ollama).
    *   **Rationale**: This model represents the State-of-the-Art (SOTA) for open-weights vision-language models as of early 2026. Its key advantage is **Naive Dynamic Resolution**, which allows it to process images at their native resolution and aspect ratio by dynamically allocating tokens. This directly addresses the user's primary pain point of "downscaling to illegibility".
    *   **Hardware Compatibility**: The user's **NVIDIA RTX PRO 6000 Blackwell (96GB VRAM)** is exceptionally capable. A 72B parameter model at 4-bit quantization requires ~43GB VRAM, and at 8-bit ~77GB. The user can comfortably run the **Q8_0 (8-bit)** quantization for maximum precision, or **Q4_K_M** for faster inference, entirely within VRAM.

2.  **Screenshot Preparation Strategy**:
    *   **Native Resolution**: Unlike older models (CLIP/SigLIP based) that resize to fixed squares (e.g., 336x336), Qwen2.5-VL can ingest the full 4K (3840x2160) screenshot.
    *   **Chunking**: Manual chunking is largely obsolete with this architecture for 4K screens. The model will tokenize the image into patches (e.g., 14x14 pixels). A 4K screen results in a high token count (thousands of visual tokens), which fits easily within the model's context window (32k+).
    *   **Fallback**: If extremely fine text (e.g., terminal fonts < 8px) is missed, a simple 2x2 grid split (quadrants) with 10% overlap is the recommended fallback.

3.  **Classification Architecture**:
    *   **Data Reduction**: The primary goal is to convert the screenshot $S$ into a semantic text description $D$.
    *   **Workflow**:
        1.  Capture Screenshot ($S$) + Metadata (Window Title, Mouse Pos).
        2.  Pass $S$ to Qwen2.5-VL-72B with a prompt focused on UI element extraction and activity summarization.
        3.  Store $D$ + Metadata.
        4.  (Future) Train a text classifier on $D$.

## CHANGES

No code changes were requested or required for this task. The output consists of this solution file and the accompanying analysis file.

### Findings Report

#### 1. Selected Model: Qwen2.5-VL-72B-Instruct

**Specifications:**
*   **Architecture**: Transformer with slightly modified RoPE for 2D inputs; utilizes a specialized vision encoder (ViT-based but adapted) that supports varying resolutions.
*   **Parameters**: ~72 Billion.
*   **Context Window**: 32k to 128k tokens (depending on exact version/quantization).
*   **Visual Capabilities**: OCR (Optical Character Recognition), Document Understanding, GUI Agent capabilities.
*   **License**: Apache 2.0.

**Why it was chosen:**
*   **Dynamic Resolution**: This is the critical feature. The model processes images as a sequence of patches. A 3840x2160 image is not squashed; it is split into a grid of patches. This ensures text remains legible.
*   **Performance**: Benchmarks (MMMU, MathVista, OCRBench) place it alongside or above proprietary models like GPT-4V/o in many tasks.
*   **Local Inference**: Fully supported by Ollama.
*   **Hardware Fit**: The 96GB VRAM allows running high-precision quants (Q8_0 or FP16 if utilizing system RAM offload, but Q8_0 fits entirely in VRAM).

#### 2. Screenshot Preparation & Workflow

**Step 1: Capture**
Use `gnome-screenshot` or `scrot` to capture the full desktop.
```bash
gnome-screenshot -f /tmp/screen.png
```

**Step 2: Processing (No Chunking Required)**
With Qwen2.5-VL, you generally do **not** need to chunk a 4K image manually.
*   **Input**: The raw 3840x2160 PNG.
*   **Ollama Command**:
    ```bash
    ollama run qwen2.5-vl:72b "Describe this desktop screenshot in detail. Identify the active window, list all visible application names, and summarize the text content of the main work area. Ignore system tray icons unless relevant."
    ```

**Step 3: Handling Ultra-High Resolution (Future Proofing)**
If you upgrade to 8K or find small text is missing:
*   **Strategy**: "Sliding Window" or "Quadrants".
*   **Method**: Split the 3840x2160 image into four 1920x1080 quadrants.
*   **Overlap**: Not strictly necessary for simple text, but 10% overlap helps with elements cut at the boundary.
*   **Synthesis**: Concatenate the descriptions of the 4 quadrants. Since you are doing classification, a structured JSON output from each quadrant is easier to merge than free text.

**Step 4: Storage for Classification**
*   Do not store the image.
*   Store the generated text description + embedding (using a fast text embedder like `nomic-embed-text`).
*   This reduces storage from ~5MB/screenshot to ~2KB/screenshot.

#### 3. Integration with GNOME Metadata

You mentioned using a GNOME extension for window titles. This is excellent data fusion.
*   **Prompt Engineering**: Inject the window title into the prompt to ground the model.
    *   *Prompt*: "The active window is reported as '{active_window_title}'. detailed description of the contents of this specific window..."
*   This prevents the model from guessing which window is active if multiple are visible.
