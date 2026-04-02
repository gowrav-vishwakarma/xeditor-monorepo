"""
CogVideoX Generator — Best I2V quality, strong LoRA ecosystem.

Supports both text-to-video and image-to-video modes.
Integrates with Diffusers pipeline.
"""

from typing import Any, Dict, List, Optional, Tuple

from apps.video_editor.generators.base import (
    VideoGenerator,
    VideoResult,
    ProgressCallback,
)
from apps.video_editor.models import (
    AssetRef,
    GeneratorCapabilities,
    GeneratorType,
    GeneratorUiSchema,
    UiSection,
    UiField,
    UiFieldType,
    UiFieldOption,
    ShapeConstraints,
    FrameCountRule,
)


class CogVideoXT2VGenerator(VideoGenerator):
    """CogVideoX for high-quality text-to-video and image-to-video generation."""

    _pipeline = None

    @classmethod
    def capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="t2v_cogvideox",
            title="CogVideoX",
            description="High-quality text/image-to-video via CogVideoX. Strong I2V + LoRA support.",
            version="1.0.0",
            generator_type=GeneratorType.T2V,
            vram_gb_min=8.0,
            vram_gb_recommended=16.0,
            ram_gb_min=16.0,
            supports_t2v=True,
            supports_i2v=True,
            supports_lora=True,
            shape_constraints=ShapeConstraints(
                resolutions=[(480, 720), (720, 480), (720, 1280), (1280, 720)],
                frame_count_rules=[
                    FrameCountRule(fixed_values=[49, 81]),
                ],
            ),
            max_frames=81,
            max_duration_seconds=10.0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="model",
                    label="Model",
                    fields=[
                        UiField(
                            key="model_variant",
                            label="Variant",
                            field_type=UiFieldType.SELECT,
                            default="THUDM/CogVideoX-5b",
                            required=False,
                            options=[
                                UiFieldOption(value="THUDM/CogVideoX-2b", label="CogVideoX-2B (light)"),
                                UiFieldOption(value="THUDM/CogVideoX-5b", label="CogVideoX-5B (recommended)"),
                                UiFieldOption(value="THUDM/CogVideoX-5b-I2V", label="CogVideoX-5B I2V"),
                            ],
                        ),
                    ],
                ),
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="num_frames", label="Frames", field_type=UiFieldType.INT, default=49, required=False),
                        UiField(key="guidance_scale", label="Guidance Scale", field_type=UiFieldType.FLOAT, default=6.0, required=False),
                        UiField(key="num_inference_steps", label="Steps", field_type=UiFieldType.INT, default=50, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import CogVideoXPipeline
            model_id = (self.config.custom or {}).get("model_variant", "THUDM/CogVideoX-5b") if self.config else "THUDM/CogVideoX-5b"
            self._pipeline = CogVideoXPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
            ).to("cuda")
        except ImportError:
            raise RuntimeError("diffusers with CogVideoX support is not installed")

    async def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    async def generate(
        self,
        prompt: str,
        output_path: str,
        negative_prompt: Optional[str] = None,
        width: int = 720,
        height: int = 480,
        num_frames: int = 49,
        fps: int = 8,
        guidance_scale: float = 6.0,
        num_inference_steps: int = 50,
        seed: Optional[int] = None,
        image_path: Optional[str] = None,
        character_refs: Optional[List[AssetRef]] = None,
        product_refs: Optional[List[AssetRef]] = None,
        lora_refs: Optional[List[AssetRef]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> VideoResult:
        if self._pipeline is None:
            return VideoResult(success=False, error="Model not loaded")

        try:
            import torch
            from diffusers.utils import export_to_video

            generator = torch.Generator(device="cuda")
            if seed is not None:
                generator.manual_seed(seed)

            video_frames = self._pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_frames=num_frames,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps,
                generator=generator,
            ).frames[0]

            export_to_video(video_frames, output_path, fps=fps)

            duration = num_frames / fps
            return VideoResult(
                success=True,
                artifact_path=output_path,
                duration_seconds=duration,
                frame_count=num_frames,
                fps=fps,
                width=width,
                height=height,
            )
        except Exception as e:
            return VideoResult(success=False, error=str(e))
