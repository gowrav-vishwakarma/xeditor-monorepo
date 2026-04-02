"""
Wan 2.1 Image-to-Video Generator.

Works on 6GB+ VRAM with quantization. High-quality I2V mode.
T2V mode already exists as t2v_wan; this provides the I2V variant.
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


class WanI2VGenerator(VideoGenerator):
    """Wan 2.1 Image-to-Video mode for keyframe-driven video generation."""

    _pipeline = None

    @classmethod
    def get_id(cls) -> str:
        return "i2v_wan"

    @classmethod
    def get_capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="i2v_wan",
            title="Wan 2.1 I2V",
            description="Image-to-video using Wan 2.1. Works on 6GB+ VRAM with quantization.",
            version="1.0.0",
            generator_type=GeneratorType.I2V,
            vram_gb_min=6.0,
            vram_gb_recommended=12.0,
            ram_gb_min=16.0,
            supports_i2v=True,
            supports_lora=True,
            shape_constraints=ShapeConstraints(
                resolutions=[(480, 832), (832, 480), (624, 832), (832, 624)],
                frame_count_rules=[
                    FrameCountRule(min_frames=16, max_frames=81, step=4),
                ],
            ),
            max_frames=81,
            max_duration_seconds=5.0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="model",
                    label="Model",
                    fields=[
                        UiField(
                            key="model_variant",
                            label="Variant",
                            field_type=UiFieldType.SELECT,
                            default="Wan-AI/Wan2.1-I2V-14B-480P",
                            required=False,
                            options=[
                                UiFieldOption(value="Wan-AI/Wan2.1-I2V-14B-480P", label="14B 480P"),
                                UiFieldOption(value="Wan-AI/Wan2.1-I2V-14B-720P", label="14B 720P"),
                            ],
                        ),
                    ],
                ),
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="num_frames", label="Frames", field_type=UiFieldType.INT, default=49, required=False),
                        UiField(key="guidance_scale", label="Guidance Scale", field_type=UiFieldType.FLOAT, default=5.0, required=False),
                        UiField(key="num_inference_steps", label="Steps", field_type=UiFieldType.INT, default=30, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import WanImageToVideoPipeline
            model_id = (self.config.custom or {}).get("model_variant", "Wan-AI/Wan2.1-I2V-14B-480P") if self.config else "Wan-AI/Wan2.1-I2V-14B-480P"
            self._pipeline = WanImageToVideoPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
            ).to("cuda")
        except ImportError:
            raise RuntimeError("diffusers with Wan support is not installed")

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
        width: int = 832,
        height: int = 480,
        num_frames: int = 49,
        fps: int = 16,
        guidance_scale: float = 5.0,
        num_inference_steps: int = 30,
        seed: Optional[int] = None,
        image_path: Optional[str] = None,
        character_refs: Optional[List[AssetRef]] = None,
        product_refs: Optional[List[AssetRef]] = None,
        lora_refs: Optional[List[AssetRef]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> VideoResult:
        if self._pipeline is None:
            return VideoResult(success=False, error="Model not loaded")

        if not image_path:
            return VideoResult(success=False, error="Image path required for I2V mode")

        try:
            import torch
            from PIL import Image
            from diffusers.utils import export_to_video

            input_image = Image.open(image_path).convert("RGB").resize((width, height))

            generator = torch.Generator(device="cuda")
            if seed is not None:
                generator.manual_seed(seed)

            video_frames = self._pipeline(
                image=input_image,
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
