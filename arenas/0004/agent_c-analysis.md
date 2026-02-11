## RISKS — Known risks, edge cases, trade-offs.

1.  **Latency**: Processing multiple window crops sequentially will add significant time (5-10s per window).
    *   *Mitigation*: Asynchronous processing. Only update the description when the window focus changes or on a slow timer (e.g., every 30s).
2.  **Ollama Downscaling**: Even with window crops, if a window spans the full 4K screen (e.g., maximized IDE), Ollama might still resize it.
    *   *Mitigation*: Step 0 Sanity Check. If it fails, split maximized windows into 2 vertical tiles (1920x2160) to fit pixel budgets.
3.  **VRAM Pressure**: Running Qwen2.5-VL-72B alongside a heavy desktop environment might cause OOM if not careful with context length.
    *   *Mitigation*: Use Q4_K_M (43GB) instead of Q8_0 (77GB). This leaves ~50GB free for system + KV cache.
4.  **Wayland Compatibility**: GNOME extensions on Wayland have restricted access to global window geometry.
    *   *Mitigation*: If geometry is unavailable, fallback to **Landscape Grid Tiling** (2x2 or 3x2).

## OPEN QUESTIONS — Uncertainties requiring verification.

1.  **Ollama Max Pixels**: What is the default `max_pixels` for Qwen2.5-VL in Ollama? Does it respect overrides?
2.  **GNOME Extension Capability**: Can the user's existing extension provide bounding box coordinates (`x, y, w, h`) reliable enough for cropping? If not, `wmctrl` or `xdotool` might be needed as a fallback.

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

None. All agents have converged on:
1.  **Qwen2.5-VL-72B-Instruct** as the SOTA model.
2.  **Q4_K_M** quantization as the safe baseline.
3.  **Window-Aware Cropping** as the primary strategy.
4.  **Delta Storage (Hashing)** as a core optimization.
5.  **Structured JSON** as the output format.
