## RISKS — Known risks, edge cases, trade-offs.

1.  **Latency**: Running dual models is slow.
    *   *Mitigation*: Selective execution (skip GLM-OCR on image-heavy windows), delta hashing, and asynchronous processing.
2.  **OCR Over-Trust**: Specialized OCR models can sometimes misinterpret UI chrome (icons, small labels) as garbage text.
    *   *Mitigation*: Use Qwen3-VL's semantic summary as the "ground truth" for UI structure and GLM-OCR only for the content *inside* the main view.
3.  **Resource Contention**: Loading 32B + 0.9B models.
    *   *Mitigation*: Strict NixOS config (`OLLAMA_MAX_LOADED_MODELS="2"`).

## OPEN QUESTIONS — Uncertainties requiring verification.

1.  **GLM-OCR Artifacts**: Does GLM-OCR hallucinate on pure-image regions? A/B testing on image-heavy windows (without text) is needed to tune the "Selective OCR" heuristic.

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

None. All agents have converged on the **Qwen3-VL-32B + GLM-OCR** architecture with selective execution and specific NixOS configuration.
