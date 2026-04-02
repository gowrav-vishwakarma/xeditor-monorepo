"""
MuseTalk 1.5 Lip Sync Generator.

Real-time lip sync at 30fps+. Takes audio + face image/video,
outputs synced video. Training code available.
"""

from typing import Optional, Tuple

from apps.video_editor.generators.base import (
    LipSyncGenerator,
    LipSyncResult,
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


class MuseTalkLipSyncGenerator(LipSyncGenerator):
    """MuseTalk 1.5 for real-time audio-driven lip sync."""

    _model = None

    @classmethod
    def get_id(cls) -> str:
        return "lipsync_musetalk"

    @classmethod
    def get_capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="lipsync_musetalk",
            title="MuseTalk 1.5",
            description="Real-time lip sync at 30fps+. Audio-driven face animation.",
            version="1.0.0",
            generator_type=GeneratorType.LIPSYNC,
            vram_gb_min=4.0,
            vram_gb_recommended=8.0,
            ram_gb_min=8.0,
            supports_lipsync=True,
            max_frames=0,
            max_duration_seconds=300.0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="generation",
                    label="Settings",
                    fields=[
                        UiField(key="fps", label="Output FPS", field_type=UiFieldType.INT, default=30, required=False),
                        UiField(
                            key="quality",
                            label="Quality",
                            field_type=UiFieldType.SELECT,
                            default="high",
                            required=False,
                            options=[
                                UiFieldOption(value="fast", label="Fast (lower quality)"),
                                UiFieldOption(value="high", label="High quality"),
                            ],
                        ),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._model is not None:
            return
        # MuseTalk model loading placeholder
        # from musetalk import MuseTalkModel
        # self._model = MuseTalkModel.from_pretrained("TMElyralab/MuseTalk")
        pass

    async def unload(self) -> None:
        self._model = None

    async def generate(
        self,
        video_input_path: str,
        audio_input_path: str,
        output_path: str,
        face_ref_path: Optional[str] = None,
        mask_roi: Optional[Tuple[int, int, int, int]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> LipSyncResult:
        if self._model is None:
            return LipSyncResult(
                success=False,
                error="MuseTalk model not loaded. Install musetalk package.",
            )

        try:
            result = self._model.inference(
                video_path=video_input_path,
                audio_path=audio_input_path,
                output_path=output_path,
                face_ref=face_ref_path,
            )
            return LipSyncResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=result.get("duration", 0),
                fps=result.get("fps", 30),
            )
        except Exception as e:
            return LipSyncResult(success=False, error=str(e))
