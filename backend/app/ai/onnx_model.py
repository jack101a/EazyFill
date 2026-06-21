"""ONNX model adapter for OCR-like inference."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from app.ai.base_model import BaseAIModel
from app.core.config import Settings

logger = logging.getLogger(__name__)


class OnnxAIModel(BaseAIModel):
    """ONNX inference model with CTC decoding, loaded from a specific path."""

    def __init__(self, settings: Settings, model_path: Path) -> None:
        self._settings = settings
        self._model_path = model_path
        self._session: ort.InferenceSession | None = None
        self._input_name: str | None = None
        self._output_name: str | None = None

    # ── Derived config helpers — always read from settings, never hardcoded ───

    @property
    def _vocab(self) -> str:
        return self._settings.model.onnx_vocab

    @property
    def _target_height(self) -> int:
        return self._settings.model.onnx_height

    @property
    def _target_width(self) -> int:
        return self._settings.model.onnx_width

    def _ensure_loaded(self) -> None:
        """Lazily load ONNX session and tensor names."""

        if self._session is not None:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(f"ONNX model missing at {self._model_path}")
        started = time.perf_counter()
        self._session = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.info(
            "onnx_model_loaded",
            extra={"context": {"model_path": str(self._model_path), "load_ms": elapsed}},
        )

    def _decode_payload_image(self, payload_base64: str) -> Image.Image:
        """Decode base64 payload into PIL image (mode handled in preprocess)."""

        raw = payload_base64
        if "," in payload_base64 and payload_base64.startswith("data:"):
            raw = payload_base64.split(",", 1)[1]
        binary = base64.b64decode(raw)
        return Image.open(io.BytesIO(binary))

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        """Apply training-equivalent preprocess and return [1, 3, H, W] float32."""

        target_h = self._target_height
        target_w = self._target_width

        # Normalize transparency onto a white background before RGB conversion.
        has_alpha = image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        )
        if has_alpha:
            rgba = image.convert("RGBA")
            white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(white_bg, rgba).convert("RGB")
        else:
            image = image.convert("RGB")

        original_w, original_h = image.size
        if original_h <= 0:
            raise ValueError("Invalid image height for preprocessing.")

        ratio = target_h / float(original_h)
        new_w = max(1, int(original_w * ratio))
        resized = image.resize((new_w, target_h), Image.Resampling.BILINEAR)

        if new_w < target_w:
            padded = Image.new("RGB", (target_w, target_h), (255, 255, 255))
            padded.paste(resized, (0, 0))
            processed = padded
        elif new_w > target_w:
            processed = resized.crop((0, 0, target_w, target_h))
        else:
            processed = resized

        array = np.asarray(processed, dtype=np.float32) / 255.0
        chw = np.transpose(array, (2, 0, 1))
        return np.expand_dims(chw, axis=0)

    def _decode_ctc(self, raw: np.ndarray) -> str:
        """
        Decode CTC logits into text.

        The ONNX model outputs shape [T, B, C] (time-first).
        Reference: argmax over class dim (axis=2) -> [T, B], then take [:, 0] for batch 0.
        Handles [B, T, C] (batch-first) layout as fallback if shape[0] == 1 (batch size).
        """
        vocab = self._vocab

        if raw.ndim == 3:
            if raw.shape[1] == 1 and raw.shape[0] != 1:
                # [T, B, C] layout — time-first export (our model: shape (63, 1, 63))
                best_path = np.argmax(raw, axis=2)[:, 0]  # [T]
            elif raw.shape[0] == 1:
                # [B=1, T, C] layout — batch-first with single batch
                best_path = np.argmax(raw[0], axis=1)  # [T]
            else:
                # [B, T, C] layout — batch-first export (B > 1)
                best_path = np.argmax(raw[0], axis=1)  # [T]
        elif raw.ndim == 2:
            # [T, C] — already squeezed single-batch export
            best_path = np.argmax(raw, axis=1)
        else:
            raise ValueError(f"Unexpected CTC output shape: {raw.shape}")

        prev = None
        chars: list[str] = []
        for idx in best_path:
            if idx != 0 and idx != prev:
                char_index = int(idx) - 1
                if 0 <= char_index < len(vocab):
                    chars.append(vocab[char_index])
            prev = idx
        return "".join(chars)


    async def solve(self, task_type: str, payload_base64: str) -> str:
        """Run ONNX solve for image tasks; raise ValueError for unsupported types."""

        self._ensure_loaded()
        if task_type != "image":
            # Raise so the caller logs and surfaces a meaningful error, not
            # a silent wrong answer stored in the cache.
            raise ValueError(f"task_type '{task_type}' is not supported by the ONNX model")

        image = self._decode_payload_image(payload_base64)
        tensor = self._preprocess(image)
        started = time.perf_counter()
        raw = await asyncio.to_thread(
            self._session.run, [self._output_name], {self._input_name: tensor}
        )
        raw = raw[0]
        infer_ms = int((time.perf_counter() - started) * 1000)
        logger.info("onnx_inference_done", extra={"context": {"inference_ms": infer_ms}})
        return self._decode_ctc(raw)
