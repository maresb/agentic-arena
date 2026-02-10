## RISKS — Known risks, edge cases, trade-offs.

1.  **Hallucination with Dense Text**: While Qwen2.5-VL-72B is excellent, extremely dense information (e.g., small terminal fonts, large spreadsheets) can still lead to hallucinations or skipped content. The model might summarize "a terminal with code" rather than reading every line.
    *   *Mitigation*: Use prompting strategies that request verbatim extraction of specific areas (e.g., "Read the last 10 lines of the terminal") rather than full screen OCR if not needed.
2.  **Latency vs. Real-Time Needs**: A 72B model on a single GPU (even a powerful one like the Blackwell RTX 6000) will have noticeable inference latency (estimated 2-10 seconds per image depending on token output length).
    *   *Mitigation*: Run the classification asynchronously. Do not block the UI. Use a smaller model (e.g., Qwen2.5-VL-7B or Pixtral-12B) for rapid pre-filtering if needed, and reserve the 72B model for detailed analysis or complex cases.
3.  **Context Window Limits**: Storing the full conversation history of screen descriptions will rapidly exhaust the context window.
    *   *Mitigation*: Treat each screenshot analysis as a stateless "one-shot" or "few-shot" interaction. Do not maintain a chat history of thousands of previous screenshots in the context. Store the results in a database instead.
4.  **Privacy Concerns**: Although local, logs might inadvertently capture sensitive data (passwords, private chats) visible on screen.
    *   *Mitigation*: Implement a redaction step or simply avoid running the tool during sensitive work. Since it's local, data leakage is minimized, but local logs should be secured.

## OPEN QUESTIONS — Uncertainties requiring verification.

1.  **Ollama Implementation Specifics**: Does the current installed version of Ollama fully support the dynamic resolution features of Qwen2.5-VL without hidden resizing?
    *   *Verification Needed*: Check the `ollama` logs or model configuration to confirm that the input resolution is not being silently capped (e.g., at 1024x1024 or similar defaults in some backends).
2.  **Token Usage for 4K Screenshots**: Exactly how many visual tokens does a 3840x2160 image consume with Qwen2.5-VL's patching strategy?
    *   *Verification Needed*: Run a test with `--verbose` to see the token count. This impacts VRAM usage and inference speed directly.
3.  **Heat/Power Consumption**: Running a 72B model continuously on a workstation GPU might generate significant heat and noise.
    *   *Verification Needed*: Monitor GPU thermals during extended screenshot analysis sessions.
4.  **Optimal Quantization Level**: Will Q4_K_M (4-bit) be sufficient for fine-grained text recognition, or is Q8_0 (8-bit) strictly required?
    *   *Verification Needed*: A/B test a difficult screenshot with both quantization levels. The 96GB VRAM allows Q8_0, so prefer that if speed permits.
