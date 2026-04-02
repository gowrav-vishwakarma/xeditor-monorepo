"""
IP-Adapter + SDXL Generator — Character-consistent variations.

Generates character variations from a reference image + text prompt.
Supports pose, outfit, and expression changes while preserving identity.
"""

from typing import Optional

from apps.video_editor.generators.base import (
    ImageGenerator,
    ImageResult,
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


class IPAdapterSDXLGenerator(ImageGenerator):
    """IP-Adapter + SDXL for character-consistent image generation."""

    _pipeline = None

    @classmethod
    def capabilities(cls) -> GeneratorCapabilities:
        return GeneratorCapabilities(
            id="t2i_ipadapter",
            title="IP-Adapter + SDXL",
            description="Character-consistent variations using IP-Adapter. Preserves identity across poses/outfits.",
            version="1.0.0",
            generator_type=GeneratorType.T2I,
            vram_gb_min=8.0,
            vram_gb_recommended=12.0,
            ram_gb_min=16.0,
            supports_character_ref=True,
            shape_constraints=ShapeConstraints(
                resolutions=[(1024, 1024), (1024, 768), (768, 1024), (1152, 896), (896, 1152)],
            ),
            max_frames=0,
            max_duration_seconds=0.0,
            ui_schema=GeneratorUiSchema(sections=[
                UiSection(
                    key="generation",
                    label="Generation",
                    fields=[
                        UiField(key="ip_adapter_scale", label="IP-Adapter Scale", field_type=UiFieldType.FLOAT, default=0.6, required=False),
                        UiField(key="num_inference_steps", label="Steps", field_type=UiFieldType.INT, default=30, required=False),
                        UiField(key="guidance_scale", label="Guidance Scale", field_type=UiFieldType.FLOAT, default=7.5, required=False),
                    ],
                ),
            ]),
        )

    async def load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import StableDiffusionXLPipeline
            self._pipeline = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")
            self._pipeline.load_ip_adapter(
                "h94/IP-Adapter",
                subfolder="sdxl_models",
                weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
            )
        except ImportError:
            raise RuntimeError("diffusers with IP-Adapter support is not installed")

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
        width: int = 1024,
        height: int = 1024,
        seed: Optional[int] = None,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        character_ref_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ImageResult:
        if self._pipeline is None:
            return ImageResult(success=False, error="Model not loaded")

        try:
            import torch
            from PIL import Image

            generator = torch.Generator(device="cuda")
            if seed is not None:
                generator.manual_seed(seed)

            kwargs = dict(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
            )

            if character_ref_path:
                ref_image = Image.open(character_ref_path).convert("RGB")
                kwargs["ip_adapter_image"] = ref_image
                ip_scale = (self.config.custom or {}).get("ip_adapter_scale", 0.6) if self.config else 0.6
                self._pipeline.set_ip_adapter_scale(float(ip_scale))

            result = self._pipeline(**kwargs)
            image = result.images[0]
            image.save(output_path)

            return ImageResult(
                success=True,
                artifact_path=output_path,
                width=width,
                height=height,
            )
        except Exception as e:
            return ImageResult(success=False, error=str(e))
