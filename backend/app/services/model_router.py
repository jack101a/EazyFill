"""Model routing service."""

from __future__ import annotations

from pathlib import Path

from app.ai.base_model import BaseAIModel
from app.ai.onnx_model import OnnxAIModel
from app.core.config import Settings
from app.core.database import Database

# Project root resolved at import time — reliable regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ModelRouter:
    """Select active model from exact CAPTCHA field mappings."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self._settings = settings
        self._db = db

        # Cache for loaded ONNX models keyed by absolute path string
        self._loaded_models: dict[str, OnnxAIModel] = {}

        # Models directory resolved relative to project root, not CWD
        self._models_dir = (_PROJECT_ROOT / "data" / "models").resolve()

    def _get_onnx_model(self, filename: str) -> OnnxAIModel:
        """Get or initialize an ONNX model instance for a specific file."""
        # filename may be an absolute path (from settings) or a bare filename
        path = Path(filename)
        if not path.is_absolute():
            path = self._models_dir / filename
        key = str(path)
        if key not in self._loaded_models:
            model = OnnxAIModel(settings=self._settings, model_path=path)
            self._loaded_models[key] = model
        return self._loaded_models[key]

    def _resolve(
        self,
        model_name: str,
        task_type: str,
        domain: str | None = None,
        field_name: str | None = None,
    ) -> BaseAIModel:
        """Resolve string name to model instance."""
        if model_name == "onnx":
            target_filename = self._settings.model.onnx_path
            field_model = (
                self._db.get_field_mapped_model(domain, field_name, task_type)
                if domain and field_name and hasattr(self._db, "get_field_mapped_model")
                else None
            )
            if field_model:
                target_filename = str(field_model.get("ai_model_filename") or target_filename)
            elif domain or field_name:
                raise ValueError("No CAPTCHA model mapping for requested domain and field")
            return self._get_onnx_model(target_filename)

        raise ValueError(f"Unsupported model runtime: {model_name}")

    def resolve_model_filename(
        self,
        task_type: str,
        domain: str | None = None,
        field_name: str | None = None,
    ) -> str:
        """Resolve the ONNX filename/path on the API side for remote workers."""

        target_filename = self._settings.model.onnx_path
        field_model = (
            self._db.get_field_mapped_model(domain, field_name, task_type)
            if domain and field_name and hasattr(self._db, "get_field_mapped_model")
            else None
        )
        if field_model:
            return str(field_model.get("ai_model_filename") or target_filename)
        if domain or field_name:
            raise ValueError("No CAPTCHA model mapping for requested domain and field")
        return str(target_filename)

    async def solve(
        self,
        task_type: str,
        payload_base64: str,
        domain: str | None = None,
        field_name: str | None = None,
        model_filename: str | None = None,
    ) -> dict:
        """
        Run the selected CAPTCHA model.
        Returns a dictionary with 'result' and 'model_used'.
        """
        primary = self._get_onnx_model(model_filename) if model_filename else self._resolve(
            self._settings.model.default,
            task_type=task_type,
            domain=domain,
            field_name=field_name,
        )

        def _model_name(model: BaseAIModel, default_name: str) -> str:
            model_path = getattr(model, "_model_path", default_name)
            if isinstance(model_path, Path):
                return model_path.name
            return str(model_path)

        result = await primary.solve(task_type, payload_base64)
        return {"result": result, "model_used": _model_name(primary, self._settings.model.default)}
