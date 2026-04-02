"""
ACE-Step 1.5 Generator — Up to 10-minute music compositions.

Supports 50+ languages for lyrics-conditioned generation.
Runs on CUDA, ROCm, Metal (8GB+ VRAM).
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


class ACEStepMusicGenerator(MusicGenerator):
    """ACE-Step 1.5 for long-form music generation with lyrics support."""

    _pipeline = None

    @classmethod
    def capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="music_acestep",
            title="ACE-Step 1.5",
            description="Up to 10-minute music compositions with lyrics support (50+ languages)",
            version="1.0.0",
            generator_type=GeneratorType.MUSIC,
            vram_gb_min=8.0,
            vram_gb_recommended=12.0,
            ram_gb_min=16.0,
            supports_music=True,
            max_duration_seconds=600.0,
            max_frames=0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="duration", label="Duration (seconds)", field_type=UiFieldType.FLOAT, default=60.0, required=False),
                        UiField(
                            key="genre",
                            label="Genre",
                            field_type=UiFieldType.SELECT,
                            default="",
                            required=False,
                            options=[
                                UiFieldOption(value="", label="Auto"),
                                UiFieldOption(value="pop", label="Pop"),
                                UiFieldOption(value="rock", label="Rock"),
                                UiFieldOption(value="jazz", label="Jazz"),
                                UiFieldOption(value="classical", label="Classical"),
                                UiFieldOption(value="electronic", label="Electronic"),
                                UiFieldOption(value="ambient", label="Ambient"),
                                UiFieldOption(value="hip_hop", label="Hip Hop"),
                                UiFieldOption(value="folk", label="Folk"),
                            ],
                        ),
                        UiField(key="tempo_bpm", label="Tempo (BPM)", field_type=UiFieldType.INT, default=120, required=False),
                        UiField(key="lyrics", label="Lyrics (optional)", field_type=UiFieldType.TEXT, default="", required=False),
                        UiField(key="vocal", label="Include Vocals", field_type=UiFieldType.BOOL, default=False, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._pipeline is not None:
            return
        # ACE-Step uses a custom pipeline; placeholder for actual loading
        # from acestep import ACEStepPipeline
        # self._pipeline = ACEStepPipeline.from_pretrained("acestep/ace-step-1.5")
        pass

    async def unload(self) -> None:
        self._pipeline = None

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
        if self._pipeline is None:
            return GenerationResult(
                success=False,
                error="ACE-Step model not loaded. Install acestep package and ensure model is downloaded.",
            )

        try:
            result = self._pipeline(
                prompt=prompt,
                lyrics=lyrics or "",
                duration=duration_seconds,
                output_path=output_path,
            )
            return GenerationResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            return GenerationResult(success=False, error=str(e))
