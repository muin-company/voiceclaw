"""Silero VAD — Voice Activity Detection."""

import numpy as np

SAMPLE_RATE = 16000


class SileroVAD:
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self.model = None
        self.enabled = False

        try:
            import torch
            self.model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
            )
            self.enabled = True
        except Exception as e:
            print(f"[vad] Silero VAD load failed: {e} — using energy-based VAD", flush=True)
            self.enabled = False

    def is_speech(self, audio_chunk: np.ndarray) -> float:
        """Return speech probability (0.0 - 1.0)."""
        if not self.enabled or self.model is None:
            energy = np.sqrt(np.mean(audio_chunk ** 2))
            return min(energy / 0.15, 1.0)
        try:
            import torch
            audio_tensor = torch.from_numpy(audio_chunk).float()
            return self.model(audio_tensor, SAMPLE_RATE).item()
        except Exception:
            energy = np.sqrt(np.mean(audio_chunk ** 2))
            return min(energy / 0.15, 1.0)
