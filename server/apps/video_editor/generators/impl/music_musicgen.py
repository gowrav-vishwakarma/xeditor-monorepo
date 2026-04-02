"""
MusicGen Generator — Meta AudioCraft text-to-music.

Model sizes: small (300M), medium (1.5B), large (3.3B).
Supports text-to-music and melody conditioning.
"""

from typing import Optional

from apps.video_editor.generators.base import (
    GenerationResult,
    MusicGenerator,
    ProgressCallback,
)
from apps.video_editor.models import (
    GeneratorCapabilities,
    GeneratorType,
    GeneratorUiSchema,
    UiSection,
    UiField,
    UiFieldType,
    UiFieldOption,
    ShapeConstraints,
)


class MusicGenGenerator(MusicGenerator):
    """Meta MusicGen via AudioCraft for text-to-music generation."""

    _model = None
    _model_size: str = "medium"

    @classmethod
    def capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="music_musicgen",
            title="MusicGen (Meta AudioCraft)",
            description="Text-to-music generation using Meta's MusicGen model",
            version="1.0.0",
            generator_type=GeneratorType.MUSIC,
            vram_gb_min=4.0,
            vram_gb_recommended=8.0,
            ram_gb_min=8.0,
            supports_music=True,
            max_duration_seconds=30.0,
            max_frames=0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="model",
                    label="Model",
                    fields=[
                        UiField(
                            key="model_size",
                            label="Model Size",
                            field_type=UiFieldType.SELECT,
                            default="medium",
                            required=False,
                            options=[
                                UiFieldOption(value="small", label="Small (300M, ~4GB VRAM)"),
                                UiFieldOption(value="medium", label="Medium (1.5B, ~8GB VRAM)"),
                                UiFieldOption(value="large", label="Large (3.3B, ~16GB VRAM)"),
                            ],
                        ),
                    ],
                ),
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="duration", label="Duration (seconds)", field_type=UiFieldType.FLOAT, default=15.0, required=False),
                        UiField(key="temperature", label="Temperature", field_type=UiFieldType.FLOAT, default=1.0, required=False),
                        UiField(key="top_k", label="Top-K", field_type=UiFieldType.INT, default=250, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._model is not None:
            return
        try:
            from audiocraft.models import MusicGen as _MusicGen
            size = (self.config.custom or {}).get("model_size", "medium") if self.config else "medium"
            self._model_size = str(size)
            self._model = _MusicGen.get_pretrained(f"facebook/musicgen-{self._model_size}")
        except ImportError:
            raise RuntimeError("audiocraft is not installed. Run: pip install audiocraft")

    async def unload(self) -> None:
        self._model = None

    async def generate(
        self,
        prompt: str,
        output_path: str,
        duration_seconds: float = 30.0,
        lyrics: Optional[str] = None,
        style: Optional[str] = None,
        seed: Optional[int] = None,
        temperature: float = 1.0,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> GenerationResult:
        if self._model is None:
            return GenerationResult(success=False, error="Model not loaded")

        try:
            import torchaudio

            self._model.set_generation_params(duration=duration_seconds, temperature=temperature)
            wav = self._model.generate([prompt])
            torchaudio.save(output_path, wav[0].cpu(), sample_rate=32000)

            return GenerationResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            return GenerationResult(success=False, error=str(e))
