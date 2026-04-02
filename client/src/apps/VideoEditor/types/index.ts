/**
 * Video Editor TypeScript Types (v2)
 *
 * These types mirror the Pydantic models on the server.
 * Single source of truth for client-side type definitions.
 *
 * Covers: generators, UI schemas, shape constraints, assets,
 * story/scenes, timeline (multi-track, scene instances), jobs.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

export type Orientation = 'landscape' | 'portrait' | 'square';

export type TrackType = 'video' | 'audio' | 'music' | 'sfx' | 'overlay';

export type ClipSourceType =
  | 'generated_video'
  | 'generated_image'
  | 'generated_audio'
  | 'generated_av'
  | 'imported'
  | 'placeholder';

export type ClipStatus =
  | 'draft'
  | 'keyframe_ready'
  | 'queued'
  | 'generating'
  | 'done'
  | 'error'
  | 'stale';

export type GenerationMode = 'prompt_only' | 'i2v' | 'flf' | 't2v' | 'av';

export type JobStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type JobType =
  | 'script_generate'
  | 'tts_generate'
  | 'image_generate'
  | 'video_generate'
  | 'av_generate'
  | 'music_generate'
  | 'sfx_generate'
  | 'lipsync'
  | 'scene_plan'
  | 'final_merge'
  | 'model_download';

export type RegenerationMode =
  | 'preview_audio'
  | 'regen_audio'
  | 'regen_video'
  | 'regen_av'
  | 'regen_audio_video'
  | 'regen_chain'
  | 'regen_all_stale';

export type GeneratorType =
  | 'llm'
  | 'tts'
  | 't2i'
  | 'i2v'
  | 't2v'
  | 'av'
  | 'music'
  | 'sfx'
  | 'lipsync'
  | 'upscaler';

export type AssetType =
  | 'image'
  | 'video'
  | 'audio'
  | 'character'
  | 'product'
  | 'voice'
  | 'control_video'
  | 'lora';

// ─────────────────────────────────────────────────────────────────────────────
// Generator UI Schema (auto-rendered parameter panels)
// ─────────────────────────────────────────────────────────────────────────────

export type UiFieldType =
  | 'string'
  | 'text'
  | 'int'
  | 'float'
  | 'bool'
  | 'select'
  | 'multiselect'
  | 'asset_ref'
  | 'asset_refs'
  | 'color'
  | 'json';

export interface UiFieldOption {
  value: string;
  label: string;
  description?: string;
}

export interface UiFieldConstraints {
  min_value?: number;
  max_value?: number;
  min_length?: number;
  max_length?: number;
  step?: number;
  pattern?: string;
  allowed_asset_types?: string[];
}

export interface UiField {
  key: string;
  label: string;
  field_type: UiFieldType;
  default?: unknown;
  required: boolean;
  description?: string;
  placeholder?: string;
  options?: UiFieldOption[];
  constraints?: UiFieldConstraints;
  depends_on?: string;
  group?: string;
}

export interface UiSection {
  key: string;
  label: string;
  description?: string;
  collapsible: boolean;
  default_collapsed: boolean;
  fields: UiField[];
}

export interface GeneratorUiSchema {
  sections: UiSection[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Generator Shape Constraints
// ─────────────────────────────────────────────────────────────────────────────

export interface FrameCountRule {
  divisor: number;
  offset: number;
  min_frames?: number;
  max_frames?: number;
}

export interface ShapeConstraints {
  width_divisible_by: number;
  height_divisible_by: number;
  min_width?: number;
  max_width?: number;
  min_height?: number;
  max_height?: number;
  frame_count_rule?: FrameCountRule;
  min_fps?: number;
  max_fps?: number;
  supported_fps?: number[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Generator Model Installable
// ─────────────────────────────────────────────────────────────────────────────

export interface ModelInstallable {
  name: string;
  url: string;
  filename?: string;
  size_gb?: number;
  checksum_sha256?: string;
  license?: string;
  license_url?: string;
  required: boolean;
  variant?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Generator Capabilities
// ─────────────────────────────────────────────────────────────────────────────

export interface GeneratorCapabilities {
  // Identity
  id: string;
  title: string;
  description?: string;
  version: string;
  author?: string;
  is_builtin: boolean;

  // Type
  generator_type: GeneratorType;

  // Resources
  vram_gb_min: number;
  vram_gb_recommended: number;
  ram_gb_min: number;

  // Model family & LoRA
  model_family?: string;
  base_model_family?: string;
  supports_lora: boolean;
  max_loras: number;
  allowed_lora_families: string[];

  // Subjects
  accepts_characters_count: number;
  accepts_products_count: number;

  // Format
  supported_formats: string[];

  // Prompts
  accepts_text_prompt: boolean;
  accepts_negative_prompt: boolean;
  accepts_motion_prompt: boolean;
  accepts_camera_control: boolean;

  // Video
  supports_i2v: boolean;
  supports_t2v: boolean;
  supports_flf: boolean;
  supports_preview_mode: boolean;
  supports_control_video: boolean;
  supported_control_types: string[];

  // Audio output (AV generators)
  produces_audio: boolean;
  produces_video: boolean;
  supports_audio_input: boolean;

  // Resolution & shape
  best_resolutions: [number, number][];
  valid_resolutions: [number, number][];
  shape_constraints: ShapeConstraints;

  // Duration
  max_duration_seconds: number;
  max_frames: number;

  // TTS
  supports_voice_cloning: boolean;
  supported_languages: string[];
  max_audio_seconds?: number;

  // Audio gen
  supports_music: boolean;
  supports_sfx: boolean;
  supports_effects: boolean;

  // LipSync
  supports_lipsync: boolean;
  supports_talking_head: boolean;

  // IP-Adapter
  supports_ip_adapter: boolean;
  max_subjects: number;

  // LLM
  max_context_tokens: number;
  supports_streaming: boolean;

  // Upscaler
  supported_scale_factors: number[];

  // UI schema
  ui_schema: GeneratorUiSchema;

  // Installables
  installables: ModelInstallable[];

  // Environment / license
  license?: string;
  license_url?: string;
  requires_acknowledgement: boolean;
  python_version_min?: string;
  cuda_version_min?: string;
  isolated_runtime: boolean;
}

export interface GeneratorConfig {
  generator_id: string;
  model_path?: string;
  api_key?: string;
  api_base_url?: string;
  seed?: number;
  steps?: number;
  cfg_scale?: number;
  custom: Record<string, unknown>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Canvas / Project Settings
// ─────────────────────────────────────────────────────────────────────────────

export interface CanvasPreset {
  name: string;
  width: number;
  height: number;
  fps: number;
  orientation: Orientation;
}

export const CANVAS_PRESETS: Record<string, CanvasPreset> = {
  '1080p_landscape': {
    name: '1080p Landscape',
    width: 1920,
    height: 1080,
    fps: 30,
    orientation: 'landscape',
  },
  '1080p_portrait': {
    name: '1080p Portrait',
    width: 1080,
    height: 1920,
    fps: 30,
    orientation: 'portrait',
  },
  '720p_landscape': {
    name: '720p Landscape',
    width: 1280,
    height: 720,
    fps: 30,
    orientation: 'landscape',
  },
  '720p_portrait': {
    name: '720p Portrait',
    width: 720,
    height: 1280,
    fps: 30,
    orientation: 'portrait',
  },
  '4k_landscape': {
    name: '4K Landscape',
    width: 3840,
    height: 2160,
    fps: 30,
    orientation: 'landscape',
  },
  square_1080: { name: 'Square 1080', width: 1080, height: 1080, fps: 30, orientation: 'square' },
  youtube_shorts: {
    name: 'YouTube Shorts',
    width: 1080,
    height: 1920,
    fps: 30,
    orientation: 'portrait',
  },
  tiktok: { name: 'TikTok', width: 1080, height: 1920, fps: 30, orientation: 'portrait' },
  instagram_reel: {
    name: 'Instagram Reel',
    width: 1080,
    height: 1920,
    fps: 30,
    orientation: 'portrait',
  },
};

export interface CanvasSettings {
  preset?: string;
  width: number;
  height: number;
  fps: number;
  orientation: Orientation;
}

export interface DefaultGeneratorSelections {
  story_llm?: string;
  tts?: string;
  t2i?: string;
  i2v?: string;
  t2v?: string;
  av?: string;
  music?: string;
  sfx?: string;
  lipsync?: string;
  upscaler?: string;
}

export interface ProjectSettings {
  vram_target_gb: number;
  canvas: CanvasSettings;
  default_generators: DefaultGeneratorSelections;
  /** Per-generator saved configs (generator_id -> custom settings dict) */
  generator_configs: Record<string, Record<string, unknown>>;
  description?: string;
  genre?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Asset Library
// ─────────────────────────────────────────────────────────────────────────────

export interface AssetRef {
  asset_id: string;
  asset_type: AssetType;
}

export interface CharacterAsset {
  id: string;
  name: string;
  code: string;
  description?: string;
  role?: string;
  image_path?: string;
  pose_images: Record<string, string>;
  voice_sample_path?: string;
  voice_id?: string;
  lora_path?: string;
  lora_trigger_word?: string;
  style_hints?: string;
  created_at: number;
  updated_at: number;
}

export interface ProductAsset {
  id: string;
  name: string;
  code: string;
  description?: string;
  image_path?: string;
  category?: string;
  lora_path?: string;
  lora_trigger_word?: string;
  created_at: number;
  updated_at: number;
}

export interface VoiceAsset {
  id: string;
  name: string;
  code: string;
  sample_path: string;
  description?: string;
  language: string;
  gender?: string;
  created_at: number;
  updated_at: number;
}

export interface GeneratedAsset {
  id: string;
  asset_type: AssetType;
  path: string;
  source_prompt?: string;
  generator_id?: string;
  generator_config?: Record<string, unknown>;
  width?: number;
  height?: number;
  duration_seconds?: number;
  fps?: number;
  sample_rate?: number;
  seed?: number;
  metadata?: Record<string, unknown>;
  created_at: number;
}

export interface AssetFolder {
  id: string;
  name: string;
  parent_id?: string;
  asset_type?: AssetType;
}

export interface MusicAsset {
  id: string;
  name: string;
  path: string;
  duration_seconds?: number;
  genre?: string;
  mood?: string;
  tempo_bpm?: number;
  source_prompt?: string;
  generator_id?: string;
  loop_compatible: boolean;
  created_at: number;
}

export interface SfxAsset {
  id: string;
  name: string;
  path: string;
  duration_seconds?: number;
  category?: string;
  source_prompt?: string;
  generator_id?: string;
  created_at: number;
}

export interface AssetLibrary {
  characters: CharacterAsset[];
  products: ProductAsset[];
  voices: VoiceAsset[];
  music: MusicAsset[];
  sfx: SfxAsset[];
  generated: GeneratedAsset[];
  folders: AssetFolder[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Story / Script
// ─────────────────────────────────────────────────────────────────────────────

export interface ScriptLine {
  id: string;
  character_id?: string;
  text: string;
  emotion_hint?: string;
  voice_override?: string;
  duration_hint?: number;
}

export interface SceneDescription {
  visual_prompt: string;
  negative_prompt?: string;
  motion_prompt?: string;
  camera_notes?: string;
  style_ref?: AssetRef;
  control_video_ref?: AssetRef;
}

export interface SceneGenerationOverrides {
  video_generator_id?: string;
  audio_generator_id?: string;
  av_generator_id?: string;
  lora_refs: AssetRef[];
  seed?: number;
}

export interface StoryScene {
  id: string;
  title?: string;
  order: number;
  script_lines: ScriptLine[];
  description: SceneDescription;
  character_ids: string[];
  product_ids: string[];
  duration_estimate?: number;
  notes?: string;
  generation_overrides: SceneGenerationOverrides;
}

export interface Story {
  title?: string;
  genre?: string;
  synopsis?: string;
  scenes: StoryScene[];
  created_at: number;
  updated_at: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Timeline / Clips
// ─────────────────────────────────────────────────────────────────────────────

export interface ClipRef {
  clip_id: string;
  frame: string;
}

export interface GenerationSpec {
  mode: GenerationMode;
  prompt?: string;
  negative_prompt?: string;
  motion_prompt?: string;
  camera_notes?: string;
  first_frame?: AssetRef;
  last_frame?: AssetRef;
  link_first_frame_from?: ClipRef;
  link_last_frame_to?: ClipRef;
  style_ref?: AssetRef;
  character_refs: AssetRef[];
  product_refs: AssetRef[];
  control_video_ref?: AssetRef;
  lora_refs: AssetRef[];
  generator_id?: string;
  generator_config?: Record<string, unknown>;
  audio_usage?: 'use_generated' | 'use_tts' | 'mix';
}

export interface TimelineClip {
  id: string;
  track_id: string;
  start_time: number;
  duration: number;
  source_type: ClipSourceType;
  scene_id?: string;
  group_id?: string;
  generation_spec?: GenerationSpec;
  script_line_ids: string[];
  status: ClipStatus;
  keyframe_path?: string;
  video_artifact_path?: string;
  audio_artifact_path?: string;
  preview_path?: string;
  script_edited_at?: number;
  keyframe_edited_at?: number;
  style_edited_at?: number;
  prompt_edited_at?: number;
  audio_generated_at?: number;
  video_generated_at?: number;
  av_generated_at?: number;
  generation_metadata?: Record<string, unknown>;
  volume?: number;
  fade_in_seconds?: number;
  fade_out_seconds?: number;
  loop?: boolean;
}

export interface TimelineTrack {
  id: string;
  name: string;
  type: TrackType;
  order: number;
  muted: boolean;
  locked: boolean;
  height: number;
}

export interface SceneInstance {
  id: string;
  scene_id: string;
  start_time: number;
  duration: number;
  video_clip_ids: string[];
  audio_clip_ids: string[];
  locked_move: boolean;
}

export interface Timeline {
  tracks: TimelineTrack[];
  clips: TimelineClip[];
  scene_instances: SceneInstance[];
  total_duration: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Jobs
// ─────────────────────────────────────────────────────────────────────────────

export interface JobProgressEvent {
  job_id: string;
  seq: number;
  stage: string;
  stage_progress: number;
  overall_progress: number;
  current_frame?: number;
  total_frames?: number;
  preview_url?: string;
  eta_seconds?: number;
  message?: string;
}

export interface Job {
  id: string;
  type: JobType;
  status: JobStatus;
  clip_ids: string[];
  scene_ids: string[];
  depends_on: string[];
  generator_id?: string;
  generator_config?: Record<string, unknown>;
  story_spec?: Record<string, unknown>;
  vram_gb_required: number;
  created_at: number;
  started_at?: number;
  completed_at?: number;
  artifact_paths: string[];
  error_message?: string;
  last_seq: number;
  last_progress: number;
}

export interface JobQueue {
  jobs: Job[];
  active_job_id?: string;
  vram_in_use_gb: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Project State
// ─────────────────────────────────────────────────────────────────────────────

export interface VideoProject {
  id: string;
  name: string;
  version: string;
  settings: ProjectSettings;
  library: AssetLibrary;
  story: Story;
  timeline: Timeline;
  job_queue: JobQueue;
  created_at: number;
  updated_at: number;
  root_path?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Recent Projects
// ─────────────────────────────────────────────────────────────────────────────

export interface RecentProject {
  id: string;
  name: string;
  path: string;
  opened_at: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper Functions
// ─────────────────────────────────────────────────────────────────────────────

export function createDefaultProjectSettings(): ProjectSettings {
  return {
    vram_target_gb: 24.0,
    canvas: {
      preset: '1080p_landscape',
      width: 1920,
      height: 1080,
      fps: 30,
      orientation: 'landscape',
    },
    default_generators: {},
    generator_configs: {},
  };
}

export function createDefaultAssetLibrary(): AssetLibrary {
  return {
    characters: [],
    products: [],
    voices: [],
    music: [],
    sfx: [],
    generated: [],
    folders: [],
  };
}

export function createDefaultStory(): Story {
  return {
    scenes: [],
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
  };
}

export function createDefaultTimeline(): Timeline {
  return {
    tracks: [
      {
        id: 'video_main',
        name: 'Video 1',
        type: 'video',
        order: 0,
        muted: false,
        locked: false,
        height: 60,
      },
      {
        id: 'audio_dialog',
        name: 'Dialog',
        type: 'audio',
        order: 1,
        muted: false,
        locked: false,
        height: 40,
      },
      {
        id: 'audio_music',
        name: 'Music',
        type: 'music',
        order: 2,
        muted: false,
        locked: false,
        height: 40,
      },
      {
        id: 'audio_sfx',
        name: 'SFX',
        type: 'sfx',
        order: 3,
        muted: false,
        locked: false,
        height: 40,
      },
    ],
    clips: [],
    scene_instances: [],
    total_duration: 0,
  };
}

export function isClipAudioStale(clip: TimelineClip): boolean {
  const genAt = Math.max(clip.audio_generated_at ?? 0, clip.av_generated_at ?? 0);
  if (genAt === 0) return true;
  return (clip.script_edited_at ?? 0) > genAt;
}

export function isClipVideoStale(clip: TimelineClip): boolean {
  const genAt = Math.max(clip.video_generated_at ?? 0, clip.av_generated_at ?? 0);
  if (genAt === 0) return true;
  const clipCarriesGeneratedAudio =
    Boolean(clip.audio_artifact_path?.trim()) || (clip.av_generated_at ?? 0) > 0;
  if (clipCarriesGeneratedAudio && isClipAudioStale(clip)) return true;
  return (
    Math.max(clip.keyframe_edited_at ?? 0, clip.style_edited_at ?? 0, clip.prompt_edited_at ?? 0) >
    genAt
  );
}

/**
 * Timeline warning badge: dialog/music/sfx clips only use audio staleness.
 * Video clips use video staleness (without treating "no video on audio track" as stale).
 */
export function isTimelineClipStaleWarning(clip: TimelineClip): boolean {
  if (
    clip.track_id === 'audio_dialog' ||
    clip.track_id === 'audio_music' ||
    clip.track_id === 'audio_sfx'
  ) {
    return isClipAudioStale(clip);
  }
  if (clip.track_id === 'video_main' || clip.track_id.startsWith('video')) {
    return isClipVideoStale(clip);
  }
  return isClipAudioStale(clip) || isClipVideoStale(clip);
}

/**
 * Validate resolution/frames/fps against generator shape constraints.
 * Returns error messages (empty array = valid).
 */
export function validateShapeConstraints(
  width: number,
  height: number,
  numFrames: number | undefined,
  fps: number | undefined,
  constraints: ShapeConstraints,
): string[] {
  const errors: string[] = [];

  if (width % constraints.width_divisible_by !== 0) {
    errors.push(`Width ${width} must be divisible by ${constraints.width_divisible_by}`);
  }
  if (height % constraints.height_divisible_by !== 0) {
    errors.push(`Height ${height} must be divisible by ${constraints.height_divisible_by}`);
  }
  if (constraints.min_width !== undefined && width < constraints.min_width) {
    errors.push(`Width ${width} is below minimum ${constraints.min_width}`);
  }
  if (constraints.max_width !== undefined && width > constraints.max_width) {
    errors.push(`Width ${width} exceeds maximum ${constraints.max_width}`);
  }
  if (constraints.min_height !== undefined && height < constraints.min_height) {
    errors.push(`Height ${height} is below minimum ${constraints.min_height}`);
  }
  if (constraints.max_height !== undefined && height > constraints.max_height) {
    errors.push(`Height ${height} exceeds maximum ${constraints.max_height}`);
  }

  if (numFrames !== undefined && constraints.frame_count_rule) {
    const rule = constraints.frame_count_rule;
    if ((numFrames - rule.offset) % rule.divisor !== 0) {
      errors.push(
        `Frame count ${numFrames} must satisfy (n - ${rule.offset}) % ${rule.divisor} === 0`,
      );
    }
    if (rule.min_frames !== undefined && numFrames < rule.min_frames) {
      errors.push(`Frame count ${numFrames} is below minimum ${rule.min_frames}`);
    }
    if (rule.max_frames !== undefined && numFrames > rule.max_frames) {
      errors.push(`Frame count ${numFrames} exceeds maximum ${rule.max_frames}`);
    }
  }

  if (fps !== undefined) {
    if (constraints.supported_fps && !constraints.supported_fps.includes(fps)) {
      errors.push(`FPS ${fps} not in supported values [${constraints.supported_fps.join(', ')}]`);
    }
    if (constraints.min_fps !== undefined && fps < constraints.min_fps) {
      errors.push(`FPS ${fps} is below minimum ${constraints.min_fps}`);
    }
    if (constraints.max_fps !== undefined && fps > constraints.max_fps) {
      errors.push(`FPS ${fps} exceeds maximum ${constraints.max_fps}`);
    }
  }

  return errors;
}
