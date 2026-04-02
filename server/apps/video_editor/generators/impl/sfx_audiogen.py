"""
AudioGen Generator — Meta AudioCraft text-to-sound-effects.

Model: facebook/audiogen-medium (1.5B params).
Generates environmental sounds, foley effects from text prompts.
"""

from typing import Optional

from apps.video_editor.generators.base import (
    GenerationResult,
    SFXGenerator,
    ProgressCallback,
)
from apps.video_editor.models import (
    GeneratorCapabilities,
    GeneratorType,
    GeneratorUiSchema,
    UiSection,
    UiField,
    UiFieldType,
    ShapeConstraints,
)


class AudioGenSFXGenerator(SFXGenerator):
    """Meta AudioGen via AudioCraft for sound effects generation."""

    _model = None

    @classmethod
    def capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="sfx_audiogen",
            title="AudioGen (Meta AudioCraft)",
            description="Text-to-sound-effects using Meta's AudioGen model (environmental, foley)",
            version="1.0.0",
            generator_type=GeneratorType.SFX,
            vram_gb_min=6.0,
            vram_gb_recommended=8.0,
            ram_gb_min=8.0,
            supports_sfx=True,
            max_duration_seconds=10.0,
            max_frames=0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="duration", label="Duration (seconds)", field_type=UiFieldType.FLOAT, default=5.0, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._model is not None:
            return
        try:
            from audiocraft.models import AudioGen as _AudioGen
            self._model = _AudioGen.get_pretrained("facebook/audiogen-medium")
        except ImportError:
            raise RuntimeError("audiocraft is not installed. Run: pip install audiocraft")

    async def unload(self) -> None:
        self._model = None

    async def generate(
        self,
        prompt: str,
        output_path: str,
        duration_seconds: float = 5.0,
        seed: Optional[int] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> GenerationResult:
        if self._model is None:
            return GenerationResult(success=False, error="Model not loaded")

        try:
            import torchaudio

            self._model.set_generation_params(duration=duration_seconds)
            wav = self._model.generate([prompt])
            torchaudio.save(output_path, wav[0].cpu(), sample_rate=16000)

            return GenerationResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            return GenerationResult(success=False, error=str(e))
