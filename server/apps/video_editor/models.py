"""
Video Editor Pydantic Models - Single Source of Truth (v2)

Complete redesign for the generator-driven AI video editor.
All data models for:
- Generator capabilities, UI schemas, shape constraints
- Project settings and state
- Asset library (characters, props/products, voices, control videos)
- Story and scenes
- Timeline (multi-track, scene instances, clips)
- Jobs and generation state
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class Orientation(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class TrackType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    MUSIC = "music"
    SFX = "sfx"
    OVERLAY = "overlay"


class ClipSourceType(str, Enum):
    GENERATED_VIDEO = "generated_video"
    GENERATED_IMAGE = "generated_image"
    GENERATED_AUDIO = "generated_audio"
    GENERATED_AV = "generated_av"  # Joint audio+video
    IMPORTED = "imported"
    PLACEHOLDER = "placeholder"


class ClipStatus(str, Enum):
    DRAFT = "draft"
    KEYFRAME_READY = "keyframe_ready"
    QUEUED = "queued"
    GENERATING = "generating"
    DONE = "done"
    ERROR = "error"
    STALE = "stale"  # Upstream changed, needs regeneration


class GenerationMode(str, Enum):
    PROMPT_ONLY = "prompt_only"
    I2V = "i2v"   # Image to Video
    FLF = "flf"   # First + Last Frame interpolation
    T2V = "t2v"   # Text to Video
    AV = "av"     # Joint Audio+Video


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    SCRIPT_GENERATE = "script_generate"
    TTS_GENERATE = "tts_generate"
    IMAGE_GENERATE = "image_generate"
    VIDEO_GENERATE = "video_generate"
    AV_GENERATE = "av_generate"       # Joint audio+video
    MUSIC_GENERATE = "music_generate"
    SFX_GENERATE = "sfx_generate"
    LIPSYNC = "lipsync"
    SCENE_PLAN = "scene_plan"         # Audio-first clip splitting
    FINAL_MERGE = "final_merge"
    MODEL_DOWNLOAD = "model_download"


class RegenerationMode(str, Enum):
    PREVIEW_AUDIO = "preview_audio"
    REGEN_AUDIO = "regen_audio"
    REGEN_VIDEO = "regen_video"
    REGEN_AV = "regen_av"
    REGEN_AUDIO_VIDEO = "regen_audio_video"
    REGEN_CHAIN = "regen_chain"
    REGEN_ALL_STALE = "regen_all_stale"


class GeneratorType(str, Enum):
    LLM = "llm"
    TTS = "tts"
    T2I = "t2i"
    I2V = "i2v"
    T2V = "t2v"
    AV = "av"           # Joint audio+video (e.g. LTX-2)
    MUSIC = "music"
    SFX = "sfx"
    LIPSYNC = "lipsync"
    UPSCALER = "upscaler"


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CHARACTER = "character"
    PRODUCT = "product"
    VOICE = "voice"
    CONTROL_VIDEO = "control_video"
    LORA = "lora"


# ─────────────────────────────────────────────────────────────────────────────
# Generator UI Schema (auto-rendered parameter panels)
# ─────────────────────────────────────────────────────────────────────────────

class UiFieldType(str, Enum):
    STRING = "string"
    TEXT = "text"           # Multi-line text
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    SELECT = "select"
    MULTISELECT = "multiselect"
    ASSET_REF = "asset_ref"       # Single asset reference (image/video/audio)
    ASSET_REFS = "asset_refs"     # Multiple asset references (characters/products)
    COLOR = "color"
    JSON = "json"


class UiFieldOption(BaseModel):
    """A selectable option for select/multiselect fields."""
    value: str
    label: str
    description: Optional[str] = None


class UiFieldConstraints(BaseModel):
    """Constraints for a UI field value."""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    step: Optional[float] = None
    pattern: Optional[str] = None          # Regex for string fields
    allowed_asset_types: Optional[List[str]] = None  # For asset_ref fields


class UiField(BaseModel):
    """A single user-configurable parameter exposed by a generator."""
    key: str                    # Programmatic key (maps to generator_config.custom)
    label: str                  # Display label
    field_type: UiFieldType
    default: Optional[Any] = None
    required: bool = False
    description: Optional[str] = None
    placeholder: Optional[str] = None
    options: Optional[List[UiFieldOption]] = None   # For select/multiselect
    constraints: Optional[UiFieldConstraints] = None
    depends_on: Optional[str] = None  # Show only when another field has a truthy value
    group: Optional[str] = None       # Group within a section


class UiSection(BaseModel):
    """A labeled section in the generator's parameter panel."""
    key: str
    label: str
    description: Optional[str] = None
    collapsible: bool = True
    default_collapsed: bool = False
    fields: List[UiField] = Field(default_factory=list)


class GeneratorUiSchema(BaseModel):
    """Complete UI schema for a generator's parameter panel."""
    sections: List[UiSection] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Generator Shape Constraints
# ─────────────────────────────────────────────────────────────────────────────

class FrameCountRule(BaseModel):
    """
    Describes how num_frames must be computed.
    E.g. LTX-2: num_frames must be (k * 8) + 1 for some integer k.
    """
    divisor: int = 1                   # num_frames must be divisible by this...
    offset: int = 0                    # ...plus this offset
    # Convenience: valid if (num_frames - offset) % divisor == 0
    min_frames: Optional[int] = None
    max_frames: Optional[int] = None


class ShapeConstraints(BaseModel):
    """Hard constraints on resolution, frames, FPS for a generator."""
    width_divisible_by: int = 8
    height_divisible_by: int = 8
    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    frame_count_rule: Optional[FrameCountRule] = None
    min_fps: Optional[int] = None
    max_fps: Optional[int] = None
    supported_fps: Optional[List[int]] = None  # If only specific FPS values work


# ─────────────────────────────────────────────────────────────────────────────
# Generator Installable (model download descriptors)
# ─────────────────────────────────────────────────────────────────────────────

class ModelInstallable(BaseModel):
    """A model file that can be downloaded for a generator."""
    name: str
    url: str                       # HuggingFace, Civitai, or direct URL
    filename: Optional[str] = None
    size_gb: Optional[float] = None
    checksum_sha256: Optional[str] = None
    license: Optional[str] = None
    license_url: Optional[str] = None
    required: bool = True          # False = optional (e.g. upscaler LoRA)
    variant: Optional[str] = None  # e.g. "fp8", "fp4", "distilled"


# ─────────────────────────────────────────────────────────────────────────────
# Generator Capabilities (for plugin system)
# ─────────────────────────────────────────────────────────────────────────────

class GeneratorCapabilities(BaseModel):
    """Capabilities declared by a generator plugin."""
    # Identity
    id: str
    title: str
    description: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None
    is_builtin: bool = True          # False = user-uploaded custom generator

    # Generator type
    generator_type: GeneratorType

    # Resource requirements
    vram_gb_min: float = 0.0
    vram_gb_recommended: float = 0.0
    ram_gb_min: float = 0.0

    # Model family & LoRA
    model_family: Optional[str] = None       # e.g. "sdxl", "wan2.1", "ltx-2"
    base_model_family: Optional[str] = None  # For LoRA compatibility
    supports_lora: bool = False
    max_loras: int = 0
    allowed_lora_families: List[str] = Field(default_factory=list)

    # Subjects policy
    accepts_characters_count: int = 0   # 0 = does not accept character refs
    accepts_products_count: int = 0     # 0 = does not accept product refs

    # Format support
    supported_formats: List[str] = Field(default_factory=list)

    # Prompt support
    accepts_text_prompt: bool = True
    accepts_negative_prompt: bool = False
    accepts_motion_prompt: bool = False
    accepts_camera_control: bool = False

    # Video capabilities
    supports_i2v: bool = False
    supports_t2v: bool = False
    supports_flf: bool = False              # First+last frame interpolation
    supports_preview_mode: bool = False
    supports_control_video: bool = False
    supported_control_types: List[str] = Field(default_factory=list)  # pose/depth/canny

    # Audio output capabilities (for AV generators)
    produces_audio: bool = False           # True if generator outputs audio too
    produces_video: bool = True            # True for video/AV generators
    supports_audio_input: bool = False     # Can take audio as conditioning input

    # Resolution & shape constraints
    best_resolutions: List[Tuple[int, int]] = Field(default_factory=list)
    valid_resolutions: List[Tuple[int, int]] = Field(default_factory=list)
    shape_constraints: ShapeConstraints = Field(default_factory=ShapeConstraints)

    # Duration limits
    max_duration_seconds: float = 5.0
    max_frames: int = 120

    # TTS-specific
    supports_voice_cloning: bool = False
    supported_languages: List[str] = Field(default_factory=lambda: ["en"])
    max_audio_seconds: Optional[float] = None

    # Audio generation
    supports_music: bool = False
    supports_sfx: bool = False
    supports_effects: bool = False

    # LipSync
    supports_lipsync: bool = False
    supports_talking_head: bool = False

    # IP-Adapter / style
    supports_ip_adapter: bool = False
    max_subjects: int = 1

    # LLM-specific
    max_context_tokens: int = 0
    supports_streaming: bool = False

    # Upscaler
    supported_scale_factors: List[float] = Field(default_factory=list)

    # UI schema (auto-rendered parameters)
    ui_schema: GeneratorUiSchema = Field(default_factory=GeneratorUiSchema)

    # Model downloads
    installables: List[ModelInstallable] = Field(default_factory=list)

    # Environment / license
    license: Optional[str] = None
    license_url: Optional[str] = None
    requires_acknowledgement: bool = False  # Must user accept license before download?
    python_version_min: Optional[str] = None
    cuda_version_min: Optional[str] = None
    isolated_runtime: bool = False  # Run in separate uv env / subprocess?


class GeneratorConfig(BaseModel):
    """User-configurable settings for a generator instance."""
    generator_id: str
    model_path: Optional[str] = None   # Local model path
    api_key: Optional[str] = None      # For API-based generators
    api_base_url: Optional[str] = None

    # Common settings
    seed: Optional[int] = None
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None

    # Generator-specific settings (from UI schema)
    custom: Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Canvas / Project Settings
# ─────────────────────────────────────────────────────────────────────────────

class CanvasPreset(BaseModel):
    """Predefined canvas size preset."""
    name: str
    width: int
    height: int
    fps: int = 30
    orientation: Orientation


# Common presets
CANVAS_PRESETS: Dict[str, CanvasPreset] = {
    "1080p_landscape": CanvasPreset(name="1080p Landscape", width=1920, height=1080, fps=30, orientation=Orientation.LANDSCAPE),
    "1080p_portrait": CanvasPreset(name="1080p Portrait", width=1080, height=1920, fps=30, orientation=Orientation.PORTRAIT),
    "720p_landscape": CanvasPreset(name="720p Landscape", width=1280, height=720, fps=30, orientation=Orientation.LANDSCAPE),
    "720p_portrait": CanvasPreset(name="720p Portrait", width=720, height=1280, fps=30, orientation=Orientation.PORTRAIT),
    "4k_landscape": CanvasPreset(name="4K Landscape", width=3840, height=2160, fps=30, orientation=Orientation.LANDSCAPE),
    "square_1080": CanvasPreset(name="Square 1080", width=1080, height=1080, fps=30, orientation=Orientation.SQUARE),
    "youtube_shorts": CanvasPreset(name="YouTube Shorts", width=1080, height=1920, fps=30, orientation=Orientation.PORTRAIT),
    "tiktok": CanvasPreset(name="TikTok", width=1080, height=1920, fps=30, orientation=Orientation.PORTRAIT),
    "instagram_reel": CanvasPreset(name="Instagram Reel", width=1080, height=1920, fps=30, orientation=Orientation.PORTRAIT),
}


class CanvasSettings(BaseModel):
    """Canvas/video settings for the project."""
    preset: Optional[str] = None
    width: int = 1920
    height: int = 1080
    fps: int = 30
    orientation: Orientation = Orientation.LANDSCAPE


class DefaultGeneratorSelections(BaseModel):
    """Default model/generator selections for the project."""
    story_llm: Optional[str] = None
    tts: Optional[str] = None
    t2i: Optional[str] = None
    i2v: Optional[str] = None
    t2v: Optional[str] = None
    av: Optional[str] = None       # Joint audio+video
    music: Optional[str] = None
    sfx: Optional[str] = None
    lipsync: Optional[str] = None
    upscaler: Optional[str] = None


class ProjectSettings(BaseModel):
    """Project-level settings."""
    vram_target_gb: float = 24.0
    canvas: CanvasSettings = Field(default_factory=CanvasSettings)
    default_generators: DefaultGeneratorSelections = Field(default_factory=DefaultGeneratorSelections)
    # Per-generator saved configs (generator_id -> custom settings dict)
    # e.g. {"story_llm": {"backend": "local", "model_repo_id": "Qwen/Qwen2.5-3B-Instruct", ...}}
    generator_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    description: Optional[str] = None
    genre: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Asset Library
# ─────────────────────────────────────────────────────────────────────────────

class AssetRef(BaseModel):
    """Reference to an asset by ID and type."""
    asset_id: str
    asset_type: AssetType


class CharacterAsset(BaseModel):
    """Character definition in the asset library."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    code: str                           # Short code for referencing in scripts
    description: Optional[str] = None
    role: Optional[str] = None          # e.g. "protagonist", "narrator"
    image_path: Optional[str] = None    # Primary/default image (relative)
    pose_images: Dict[str, str] = Field(default_factory=dict)  # pose_name -> relative path
    voice_sample_path: Optional[str] = None
    voice_id: Optional[str] = None      # Reference to VoiceAsset
    lora_path: Optional[str] = None
    lora_trigger_word: Optional[str] = None
    style_hints: Optional[str] = None
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class ProductAsset(BaseModel):
    """Product/prop asset in the library."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    code: str
    description: Optional[str] = None
    image_path: Optional[str] = None
    category: Optional[str] = None  # "background", "object", "prop", "effect"
    lora_path: Optional[str] = None
    lora_trigger_word: Optional[str] = None
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class VoiceAsset(BaseModel):
    """Voice profile for TTS."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    code: str
    sample_path: str               # Path to voice sample
    description: Optional[str] = None
    language: str = "en"
    gender: Optional[str] = None   # "male", "female", "neutral"
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class GeneratedAsset(BaseModel):
    """A generated image/video/audio asset."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    asset_type: AssetType
    path: str                            # Relative path within project
    source_prompt: Optional[str] = None
    generator_id: Optional[str] = None
    generator_config: Optional[Dict[str, Any]] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    fps: Optional[float] = None
    sample_rate: Optional[int] = None
    seed: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class AssetFolder(BaseModel):
    """User-created folder for organizing assets."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    parent_id: Optional[str] = None     # None = root
    asset_type: Optional[AssetType] = None  # Filter type, or None for mixed


class MusicAsset(BaseModel):
    """Music asset in the library."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    path: str
    duration_seconds: Optional[float] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    tempo_bpm: Optional[int] = None
    source_prompt: Optional[str] = None
    generator_id: Optional[str] = None
    loop_compatible: bool = False
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class SfxAsset(BaseModel):
    """Sound effect asset in the library."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    path: str
    duration_seconds: Optional[float] = None
    category: Optional[str] = None
    source_prompt: Optional[str] = None
    generator_id: Optional[str] = None
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class AssetLibrary(BaseModel):
    """Complete asset library for a project."""
    characters: List[CharacterAsset] = Field(default_factory=list)
    products: List[ProductAsset] = Field(default_factory=list)
    voices: List[VoiceAsset] = Field(default_factory=list)
    music: List[MusicAsset] = Field(default_factory=list)
    sfx: List[SfxAsset] = Field(default_factory=list)
    generated: List[GeneratedAsset] = Field(default_factory=list)
    folders: List[AssetFolder] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Story / Script
# ─────────────────────────────────────────────────────────────────────────────

class ScriptLine(BaseModel):
    """A single line of dialog/narration in a script."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    character_id: Optional[str] = None    # None = narrator
    text: str
    emotion_hint: Optional[str] = None    # "happy", "angry", "whisper", etc.
    voice_override: Optional[str] = None  # Override voice for this line
    duration_hint: Optional[float] = None # Suggested duration in seconds


class SceneDescription(BaseModel):
    """Visual description and generation parameters for a scene."""
    visual_prompt: str = ""
    negative_prompt: Optional[str] = None
    motion_prompt: Optional[str] = None
    camera_notes: Optional[str] = None
    style_ref: Optional[AssetRef] = None
    control_video_ref: Optional[AssetRef] = None  # For pose/motion control


class SceneGenerationOverrides(BaseModel):
    """Per-scene overrides for generator selections and LoRA."""
    video_generator_id: Optional[str] = None
    audio_generator_id: Optional[str] = None
    av_generator_id: Optional[str] = None
    lora_refs: List[AssetRef] = Field(default_factory=list)
    seed: Optional[int] = None


class StoryScene(BaseModel):
    """A scene in the story."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: Optional[str] = None
    order: int = 0
    script_lines: List[ScriptLine] = Field(default_factory=list)
    description: SceneDescription = Field(default_factory=SceneDescription)
    character_ids: List[str] = Field(default_factory=list)
    product_ids: List[str] = Field(default_factory=list)
    duration_estimate: Optional[float] = None
    notes: Optional[str] = None
    generation_overrides: SceneGenerationOverrides = Field(
        default_factory=SceneGenerationOverrides
    )


class Story(BaseModel):
    """The complete story structure."""
    title: Optional[str] = None
    genre: Optional[str] = None
    synopsis: Optional[str] = None
    scenes: List[StoryScene] = Field(default_factory=list)
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())


# ─────────────────────────────────────────────────────────────────────────────
# Timeline / Clips
# ─────────────────────────────────────────────────────────────────────────────

class ClipRef(BaseModel):
    """Reference to another clip (for linking/continuity)."""
    clip_id: str
    frame: str = "last"  # "first", "last", or frame number


class GenerationSpec(BaseModel):
    """Specification for generating content for a clip."""
    mode: GenerationMode = GenerationMode.PROMPT_ONLY
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    motion_prompt: Optional[str] = None
    camera_notes: Optional[str] = None

    # Keyframe references
    first_frame: Optional[AssetRef] = None
    last_frame: Optional[AssetRef] = None

    # Continuity linking (resolved at job time)
    link_first_frame_from: Optional[ClipRef] = None
    link_last_frame_to: Optional[ClipRef] = None

    # Style/character/product injection
    style_ref: Optional[AssetRef] = None
    character_refs: List[AssetRef] = Field(default_factory=list)
    product_refs: List[AssetRef] = Field(default_factory=list)
    control_video_ref: Optional[AssetRef] = None

    # LoRA overrides
    lora_refs: List[AssetRef] = Field(default_factory=list)

    # Model override
    generator_id: Optional[str] = None
    generator_config: Optional[Dict[str, Any]] = None

    # Audio usage policy (for AV generators)
    audio_usage: Optional[str] = None  # "use_generated" | "use_tts" | "mix"


class TimelineClip(BaseModel):
    """A clip on the timeline."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    track_id: str = "video_main"
    start_time: float = 0.0        # Start time in seconds
    duration: float = 0.0          # Duration in seconds

    # Content source
    source_type: ClipSourceType = ClipSourceType.PLACEHOLDER
    scene_id: Optional[str] = None   # Link to story scene

    # Scene instance grouping
    group_id: Optional[str] = None   # SceneInstance id

    # Generation spec (for video/image/av clips)
    generation_spec: Optional[GenerationSpec] = None

    # Script content (for audio clips)
    script_line_ids: List[str] = Field(default_factory=list)

    # State
    status: ClipStatus = ClipStatus.DRAFT
    keyframe_path: Optional[str] = None     # Generated/uploaded keyframe image
    video_artifact_path: Optional[str] = None
    audio_artifact_path: Optional[str] = None  # For AV or TTS clips
    preview_path: Optional[str] = None

    # Staleness tracking
    script_edited_at: Optional[float] = None
    keyframe_edited_at: Optional[float] = None
    style_edited_at: Optional[float] = None
    prompt_edited_at: Optional[float] = None
    audio_generated_at: Optional[float] = None
    video_generated_at: Optional[float] = None
    av_generated_at: Optional[float] = None    # For joint A/V

    # Metadata from generation
    generation_metadata: Optional[Dict[str, Any]] = None

    # Audio mix
    volume: float = 1.0
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    loop: bool = False

    @property
    def is_audio_stale(self) -> bool:
        if self.audio_generated_at is None and self.av_generated_at is None:
            return True
        gen_at = max(self.audio_generated_at or 0, self.av_generated_at or 0)
        return (self.script_edited_at or 0) > gen_at

    @property
    def is_video_stale(self) -> bool:
        if self.video_generated_at is None and self.av_generated_at is None:
            return True
        gen_at = max(self.video_generated_at or 0, self.av_generated_at or 0)
        if self.is_audio_stale:
            return True
        return max(
            self.keyframe_edited_at or 0,
            self.style_edited_at or 0,
            self.prompt_edited_at or 0,
        ) > gen_at

    @property
    def end_time(self) -> float:
        return self.start_time + self.duration


class TimelineTrack(BaseModel):
    """A track on the timeline."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Main"
    type: TrackType = TrackType.VIDEO
    order: int = 0
    muted: bool = False
    locked: bool = False
    height: int = 60  # UI track height in pixels


class SceneInstance(BaseModel):
    """
    Groups video+audio clips that belong to a single scene on the timeline.
    Moving one moves all. Trimming one asks about ripple.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scene_id: str
    start_time: float = 0.0
    duration: float = 0.0
    video_clip_ids: List[str] = Field(default_factory=list)
    audio_clip_ids: List[str] = Field(default_factory=list)
    locked_move: bool = True   # Move all clips together


class Timeline(BaseModel):
    """The complete timeline."""
    tracks: List[TimelineTrack] = Field(default_factory=lambda: [
        TimelineTrack(id="video_main", name="Video 1", type=TrackType.VIDEO, order=0),
        TimelineTrack(id="audio_dialog", name="Dialog", type=TrackType.AUDIO, order=1),
        TimelineTrack(id="audio_music", name="Music", type=TrackType.MUSIC, order=2),
        TimelineTrack(id="audio_sfx", name="SFX", type=TrackType.SFX, order=3),
    ])
    clips: List[TimelineClip] = Field(default_factory=list)
    scene_instances: List[SceneInstance] = Field(default_factory=list)
    total_duration: float = 0.0

    def recompute_duration(self) -> None:
        """Recompute total duration from clips."""
        if not self.clips:
            self.total_duration = 0.0
        else:
            self.total_duration = max(c.end_time for c in self.clips)


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────

class JobProgressEvent(BaseModel):
    """Progress event for a running job."""
    job_id: str
    seq: int
    stage: str
    stage_progress: float = 0.0
    overall_progress: float = 0.0
    current_frame: Optional[int] = None
    total_frames: Optional[int] = None
    preview_url: Optional[str] = None
    eta_seconds: Optional[float] = None
    message: Optional[str] = None


class Job(BaseModel):
    """A generation job."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: JobType
    status: JobStatus = JobStatus.PENDING

    # What this job operates on
    clip_ids: List[str] = Field(default_factory=list)
    scene_ids: List[str] = Field(default_factory=list)

    # Dependencies (jobs that must complete before this one)
    depends_on: List[str] = Field(default_factory=list)

    # Generator to use
    generator_id: Optional[str] = None
    generator_config: Optional[Dict[str, Any]] = None

    # Story/script generation spec
    story_spec: Optional[Dict[str, Any]] = None

    # VRAM requirement (for queue scheduling)
    vram_gb_required: float = 0.0

    # Timing
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Results
    artifact_paths: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None

    # Progress tracking
    last_seq: int = 0
    last_progress: float = 0.0


class JobQueue(BaseModel):
    """Queue of jobs for a project."""
    jobs: List[Job] = Field(default_factory=list)
    active_job_id: Optional[str] = None
    vram_in_use_gb: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Project State (Complete)
# ─────────────────────────────────────────────────────────────────────────────

class VideoProject(BaseModel):
    """Complete video project state."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str = "2.0.0"  # Schema version

    # Settings
    settings: ProjectSettings = Field(default_factory=ProjectSettings)

    # Content
    library: AssetLibrary = Field(default_factory=AssetLibrary)
    story: Story = Field(default_factory=Story)
    timeline: Timeline = Field(default_factory=Timeline)

    # Jobs
    job_queue: JobQueue = Field(default_factory=JobQueue)

    # Metadata
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())

    # Paths (set when project is opened)
    root_path: Optional[str] = None

    def update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now().timestamp()


# ─────────────────────────────────────────────────────────────────────────────
# RPC Request/Response Types
# ─────────────────────────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    folder_path: str
    name: str
    settings: Optional[ProjectSettings] = None


class CreateProjectResponse(BaseModel):
    success: bool
    project: Optional[VideoProject] = None
    error: Optional[str] = None


class OpenProjectRequest(BaseModel):
    folder_path: str


class OpenProjectResponse(BaseModel):
    success: bool
    project: Optional[VideoProject] = None
    error: Optional[str] = None


class SaveProjectRequest(BaseModel):
    project_id: str


class SaveProjectResponse(BaseModel):
    success: bool
    error: Optional[str] = None


class StartJobRequest(BaseModel):
    project_id: str
    job_type: JobType
    clip_ids: List[str] = Field(default_factory=list)
    scene_ids: List[str] = Field(default_factory=list)
    generator_id: Optional[str] = None
    generator_config: Optional[Dict[str, Any]] = None
    regeneration_mode: Optional[RegenerationMode] = None
    story_spec: Optional[Dict[str, Any]] = None


class StartJobResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    error: Optional[str] = None


class CancelJobRequest(BaseModel):
    project_id: str
    job_id: str


class CancelJobResponse(BaseModel):
    success: bool
    error: Optional[str] = None
