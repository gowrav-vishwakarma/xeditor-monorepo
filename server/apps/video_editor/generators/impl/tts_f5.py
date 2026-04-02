"""
F5-TTS Generator — Flow-matching based text-to-speech.

Higher quality than Coqui XTTS, actively maintained.
Supports zero-shot voice cloning from reference audio.
"""

from typing import Optional

from apps.video_editor.generators.base import (
    TTSGenerator,
    TTSResult,
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


class F5TTSGenerator(TTSGenerator):
    """F5-TTS for high-quality voice cloning and speech synthesis."""

    _model = None

    @classmethod
    def get_id(cls) -> str:
        return "tts_f5"

    @classmethod
    def get_capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="tts_f5",
            title="F5-TTS",
            description="Flow-matching TTS with zero-shot voice cloning. Higher quality than XTTS.",
            version="1.0.0",
            generator_type=GeneratorType.TTS,
            vram_gb_min=4.0,
            vram_gb_recommended=6.0,
            ram_gb_min=8.0,
            supports_tts=True,
            max_duration_seconds=60.0,
            max_frames=0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="model",
                    label="Model",
                    fields=[
                        UiField(
                            key="model_variant",
                            label="Model",
                            field_type=UiFieldType.SELECT,
                            default="F5-TTS",
                            required=False,
                            options=[
                                UiFieldOption(value="F5-TTS", label="F5-TTS (recommended)"),
                                UiFieldOption(value="E2-TTS", label="E2-TTS (experimental)"),
                            ],
                        ),
                    ],
                ),
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="speed", label="Speed", field_type=UiFieldType.FLOAT, default=1.0, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._model is not None:
            return
        try:
            from f5_tts.api import F5TTS
            self._model = F5TTS()
        except ImportError:
            raise RuntimeError("f5-tts is not installed. Run: pip install f5-tts")

    async def unload(self) -> None:
        self._model = None

    async def generate(
        self,
        text: str,
        output_path: str,
        voice_sample_path: Optional[str] = None,
        language: str = "en",
        speed: float = 1.0,
        emotion: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TTSResult:
        if self._model is None:
            return TTSResult(success=False, error="Model not loaded")

        try:
            wav, sr, _ = self._model.infer(
                ref_file=voice_sample_path or "",
                ref_text="",
                gen_text=text,
                speed=speed,
            )

            import soundfile as sf
            sf.write(output_path, wav, sr)

            duration = len(wav) / sr if sr > 0 else 0
            return TTSResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=duration,
                sample_rate=sr,
            )
        except Exception as e:
            return TTSResult(success=False, error=str(e))
