<template>
  <div class="properties-panel q-pa-sm">
    <div class="text-subtitle2 q-mb-sm">
      {{ panelTitle }}
    </div>

    <!-- Video Clip Properties -->
    <div v-if="workspace.activeMode === 'video' && workspace.selectedClip" class="clip-properties">
      <q-list dense>
        <q-item-label header>Clip Settings</q-item-label>

        <q-item>
          <q-item-section>
            <q-item-label caption>Start Time</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.start_time"
              type="number"
              dense
              outlined
              suffix="s"
              @update:model-value="updateClipStartTime"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Duration</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.duration"
              type="number"
              dense
              outlined
              suffix="s"
              @update:model-value="updateClipDuration"
            />
          </q-item-section>
        </q-item>

        <q-separator />
        <q-item-label header>Video Generation</q-item-label>

        <!-- Mode selector -->
        <q-item>
          <q-item-section>
            <q-item-label caption>Mode</q-item-label>
            <q-select
              :model-value="workspace.selectedClip.generation_spec?.mode || 'prompt_only'"
              :options="generationModes"
              dense
              outlined
              emit-value
              map-options
              @update:model-value="updateGenerationMode"
            />
          </q-item-section>
        </q-item>

        <!-- Model selector -->
        <q-item>
          <q-item-section>
            <q-item-label caption>Model</q-item-label>
            <q-select
              :model-value="workspace.selectedClip.generation_spec?.generator_id || ''"
              :options="videoGeneratorOptions"
              dense
              outlined
              emit-value
              map-options
              clearable
              @update:model-value="updateGeneratorId"
            />
          </q-item-section>
        </q-item>

        <!-- Prompt editor -->
        <q-item>
          <q-item-section>
            <q-item-label caption>Visual Prompt</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.generation_spec?.prompt"
              type="textarea"
              dense
              outlined
              rows="3"
              @update:model-value="updatePrompt"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Negative Prompt</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.generation_spec?.negative_prompt"
              type="textarea"
              dense
              outlined
              rows="2"
              @update:model-value="updateNegativePrompt"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Motion Prompt</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.generation_spec?.motion_prompt"
              dense
              outlined
              placeholder="Camera zoom in, slow pan left..."
              @update:model-value="(v) => updateSpecField('motion_prompt', String(v || ''))"
            />
          </q-item-section>
        </q-item>

        <!-- Keyframe section -->
        <q-separator />
        <q-item-label header>Keyframe</q-item-label>

        <q-item>
          <q-item-section>
            <div v-if="workspace.selectedClip.keyframe_path" class="text-center q-mb-sm">
              <img :src="getAssetUrl(workspace.selectedClip.keyframe_path)" class="keyframe-thumb" />
            </div>
            <div class="row q-gutter-sm">
              <q-btn outline size="sm" icon="upload" label="Upload" @click="uploadKeyframe" />
              <q-btn outline size="sm" icon="auto_awesome" label="Generate" @click="generateKeyframe" />
            </div>
            <input ref="keyframeInput" type="file" accept="image/*" class="hidden" @change="onKeyframeSelected" />
          </q-item-section>
        </q-item>

        <!-- Continuity -->
        <q-separator />
        <q-item-label header>Continuity</q-item-label>

        <q-item>
          <q-item-section>
            <q-toggle
              :model-value="!!workspace.selectedClip.generation_spec?.link_first_frame_from"
              label="Link from previous clip"
              @update:model-value="toggleContinuity"
            />
          </q-item-section>
        </q-item>

        <!-- Actions -->
        <q-separator />
        <q-item-label header>Actions</q-item-label>

        <q-item>
          <q-item-section>
            <div class="q-gutter-sm">
              <q-btn
                flat
                icon="image"
                label="Generate Keyframe"
                size="sm"
                color="primary"
                class="full-width"
                @click="generateKeyframe"
              />
              <q-btn
                flat
                icon="videocam"
                label="Generate Video"
                size="sm"
                color="primary"
                class="full-width"
                @click="generateVideoClip"
              />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Audio/Music Clip Properties -->
    <div v-else-if="showAudioClipProps && workspace.selectedClip" class="clip-properties">
      <q-list dense>
        <q-item-label header>Audio Clip</q-item-label>

        <q-item>
          <q-item-section>
            <q-item-label caption>Start Time</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.start_time"
              type="number"
              dense
              outlined
              suffix="s"
              @update:model-value="updateClipStartTime"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Duration</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.duration"
              type="number"
              dense
              outlined
              suffix="s"
              @update:model-value="updateClipDuration"
            />
          </q-item-section>
        </q-item>

        <q-separator />
        <q-item-label header>Audio Mix</q-item-label>

        <q-item>
          <q-item-section>
            <q-item-label caption>Volume</q-item-label>
            <q-slider
              :model-value="(workspace.selectedClip.volume ?? 1) * 100"
              :min="0"
              :max="100"
              label
              :label-value="`${Math.round((workspace.selectedClip.volume ?? 1) * 100)}%`"
              @update:model-value="(v: number | null) => updateClipField('volume', (v ?? 100) / 100)"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Fade In (s)</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.fade_in_seconds ?? 0"
              type="number"
              dense
              outlined
              @update:model-value="(v) => updateClipField('fade_in_seconds', Number(v))"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-item-label caption>Fade Out (s)</q-item-label>
            <q-input
              :model-value="workspace.selectedClip.fade_out_seconds ?? 0"
              type="number"
              dense
              outlined
              @update:model-value="(v) => updateClipField('fade_out_seconds', Number(v))"
            />
          </q-item-section>
        </q-item>

        <q-item>
          <q-item-section>
            <q-toggle
              :model-value="workspace.selectedClip.loop ?? false"
              label="Loop"
              @update:model-value="(v: boolean) => updateClipField('loop', v)"
            />
          </q-item-section>
        </q-item>

        <template v-if="workspace.selectedClip.audio_artifact_path">
          <q-separator />
          <q-item-label header>Generated speech</q-item-label>
          <q-item>
            <q-item-section>
              <div class="row q-gutter-sm items-center">
                <q-btn
                  outline
                  size="sm"
                  color="primary"
                  :icon="clipAudioPlaying ? 'stop' : 'play_arrow'"
                  :label="clipAudioPlaying ? 'Stop' : 'Play'"
                  @click="toggleClipGeneratedAudio"
                />
                <span class="text-caption text-grey">TTS file for this timeline clip</span>
              </div>
            </q-item-section>
          </q-item>
        </template>
      </q-list>
      <audio
        ref="clipPreviewAudio"
        class="hidden"
        @ended="clipAudioPlaying = false"
      />
    </div>

    <!-- Character Properties -->
    <div v-else-if="workspace.activeMode === 'characters' && workspace.selectedCharacter" class="character-properties">
      <q-list dense>
        <q-item-label header>Character</q-item-label>
        <q-item>
          <q-item-section>
            <q-item-label caption>Name</q-item-label>
            <q-input :model-value="workspace.selectedCharacter.name" dense outlined readonly />
          </q-item-section>
        </q-item>
        <q-item>
          <q-item-section>
            <q-item-label caption>Code</q-item-label>
            <q-input :model-value="workspace.selectedCharacter.code" dense outlined readonly />
          </q-item-section>
        </q-item>
        <q-item>
          <q-item-section>
            <q-item-label caption>Role</q-item-label>
            <q-input :model-value="workspace.selectedCharacter.role || ''" dense outlined readonly />
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Voice Properties -->
    <div v-else-if="workspace.activeMode === 'voices' && workspace.selectedVoice" class="voice-properties">
      <q-list dense>
        <q-item-label header>Voice</q-item-label>
        <q-item>
          <q-item-section>
            <q-item-label caption>Name</q-item-label>
            <q-input :model-value="workspace.selectedVoice.name" dense outlined readonly />
          </q-item-section>
        </q-item>
        <q-item>
          <q-item-section>
            <q-item-label caption>Language</q-item-label>
            <q-input :model-value="workspace.selectedVoice.language" dense outlined readonly />
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Scene Properties -->
    <div v-else-if="workspace.activeMode === 'script' && workspace.selectedScene" class="scene-properties">
      <q-list dense>
        <q-item-label header>Scene</q-item-label>
        <q-item>
          <q-item-section>
            <q-item-label caption>Title</q-item-label>
            <q-input :model-value="workspace.selectedScene.title" dense outlined readonly />
          </q-item-section>
        </q-item>
        <q-item>
          <q-item-section>
            <q-item-label caption>Lines</q-item-label>
            <div class="text-body2">{{ workspace.selectedScene.script_lines?.length ?? 0 }} lines</div>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Empty state -->
    <div v-else class="text-center q-pa-lg text-grey">
      <q-icon name="touch_app" size="48px" class="q-mb-md" />
      <div>{{ emptyStateText }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore, useVideoJobsStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';
import type { GenerationMode, TimelineClip, GenerationSpec } from '../types';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();
const jobsStore = useVideoJobsStore();
const companion = useVideoCompanionStore();

const keyframeInput = ref<HTMLInputElement | null>(null);
const clipPreviewAudio = ref<HTMLAudioElement | null>(null);
const clipAudioPlaying = ref(false);

watch(
  () => workspace.selectedClipId,
  () => {
    clipAudioPlaying.value = false;
    const el = clipPreviewAudio.value;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
  },
);

function toggleClipGeneratedAudio(): void {
  const clip = workspace.selectedClip;
  if (!clip?.audio_artifact_path || !projectStore.project || !clipPreviewAudio.value) return;

  if (clipAudioPlaying.value) {
    clipPreviewAudio.value.pause();
    clipPreviewAudio.value.currentTime = 0;
    clipAudioPlaying.value = false;
    return;
  }

  clipPreviewAudio.value.src = getAssetUrl(clip.audio_artifact_path);
  void clipPreviewAudio.value.play().then(
    () => {
      clipAudioPlaying.value = true;
    },
    () => {
      clipAudioPlaying.value = false;
    },
  );
}

const generationModes = [
  { label: 'Prompt Only (Slideshow)', value: 'prompt_only' },
  { label: 'Image to Video (I2V)', value: 'i2v' },
  { label: 'First+Last Frame (FLF)', value: 'flf' },
  { label: 'Text to Video (T2V)', value: 't2v' },
  { label: 'Audio+Video (AV)', value: 'av' },
];

const videoGeneratorOptions = computed(() => {
  return jobsStore.generators
    .filter((g) => ['t2v', 'i2v', 'video', 'av'].includes(g.generator_type))
    .map((g) => ({
      label: g.title,
      value: g.id,
    }));
});

const panelTitle = computed(() => {
  const titles: Record<string, string> = {
    script: 'Scene Properties',
    characters: 'Character Properties',
    voices: 'Voice Properties',
    audio: 'Audio Properties',
    music: 'Music / SFX Properties',
    video: 'Video Clip Properties',
    export: 'Export Settings',
  };
  return titles[workspace.activeMode] ?? 'Properties';
});

const emptyStateText = computed(() => {
  const texts: Record<string, string> = {
    script: 'Select a scene to view properties',
    characters: 'Select a character to view properties',
    voices: 'Select a voice to view properties',
    audio: 'Select a clip to view audio properties',
    music: 'Select a music/sfx clip to view properties',
    video: 'Select a video clip to view properties',
    export: 'Configure export settings',
  };
  return texts[workspace.activeMode] ?? 'Select an item to view properties';
});

const showAudioClipProps = computed(() => {
  if (!workspace.selectedClip) return false;
  return ['audio', 'music'].includes(workspace.activeMode) &&
    workspace.selectedClip.track_id.startsWith('audio_');
});

function getAssetUrl(path: string): string {
  if (!projectStore.project) return '';
  return companion.getAssetUrl(projectStore.project.id, path);
}

function getOrCreateSpec(): GenerationSpec {
  return workspace.selectedClip?.generation_spec || {
    mode: 'prompt_only' as GenerationMode,
    character_refs: [],
    product_refs: [],
    lora_refs: [],
  };
}

function updateClipStartTime(value: string | number | null): void {
  if (!workspace.selectedClipId || value === null) return;
  projectStore.updateClip(workspace.selectedClipId, { start_time: Number(value) });
}

function updateClipDuration(value: string | number | null): void {
  if (!workspace.selectedClipId || value === null) return;
  projectStore.updateClip(workspace.selectedClipId, { duration: Number(value) });
}

function updateGenerationMode(value: string): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  projectStore.updateClip(workspace.selectedClipId, {
    generation_spec: {
      ...spec,
      mode: value as GenerationMode,
      product_refs: spec.product_refs || [],
      lora_refs: spec.lora_refs || [],
    },
  });
}

function updateGeneratorId(value: string | null): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  const updated: GenerationSpec = {
    ...spec,
    product_refs: spec.product_refs || [],
    lora_refs: spec.lora_refs || [],
  };
  if (value) {
    updated.generator_id = value;
  } else {
    delete updated.generator_id;
  }
  projectStore.updateClip(workspace.selectedClipId, { generation_spec: updated });
}

function updatePrompt(value: string | number | null): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  projectStore.updateClip(workspace.selectedClipId, {
    generation_spec: {
      ...spec,
      prompt: String(value || ''),
      product_refs: spec.product_refs || [],
      lora_refs: spec.lora_refs || [],
    },
  });
}

function updateNegativePrompt(value: string | number | null): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  projectStore.updateClip(workspace.selectedClipId, {
    generation_spec: {
      ...spec,
      negative_prompt: String(value || ''),
      product_refs: spec.product_refs || [],
      lora_refs: spec.lora_refs || [],
    },
  });
}

function updateSpecField(field: string, value: unknown): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  projectStore.updateClip(workspace.selectedClipId, {
    generation_spec: {
      ...spec,
      [field]: value,
      product_refs: spec.product_refs || [],
      lora_refs: spec.lora_refs || [],
    },
  });
}

function updateClipField(field: keyof TimelineClip, value: unknown): void {
  if (!workspace.selectedClipId) return;
  projectStore.updateClip(workspace.selectedClipId, {
    [field]: value,
  } as Partial<TimelineClip>);
}

function toggleContinuity(linked: boolean): void {
  if (!workspace.selectedClipId) return;
  const spec = getOrCreateSpec();
  const timeline = projectStore.timeline;
  const currentClip = workspace.selectedClip;
  if (!currentClip) return;

  let prevClipId: string | undefined;
  if (linked) {
    const trackClips = timeline.clips
      .filter((c) => c.track_id === currentClip.track_id && c.id !== currentClip.id)
      .sort((a, b) => a.start_time - b.start_time);
    const prev = trackClips.find((c) => c.start_time + c.duration <= currentClip.start_time + 0.1);
    prevClipId = prev?.id;
  }

  const updated: GenerationSpec = {
    ...spec,
    product_refs: spec.product_refs || [],
    lora_refs: spec.lora_refs || [],
  };
  if (prevClipId) {
    updated.link_first_frame_from = { clip_id: prevClipId, frame: 'last' };
  } else {
    delete updated.link_first_frame_from;
  }
  projectStore.updateClip(workspace.selectedClipId, { generation_spec: updated });
}

function uploadKeyframe(): void {
  keyframeInput.value?.click();
}

async function onKeyframeSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !workspace.selectedClipId || !projectStore.project) return;

  try {
    const result = await companion.uploadAsset(
      projectStore.project.id,
      file,
      { assetType: 'image', subfolder: 'images' },
    );
    if (result?.path) {
      projectStore.updateClip(workspace.selectedClipId, {
        keyframe_path: result.path,
        keyframe_edited_at: Date.now() / 1000,
      });
    }
  } catch (e) {
    console.error('Failed to upload keyframe:', e);
  }
  input.value = '';
}

async function generateKeyframe(): Promise<void> {
  if (!workspace.selectedClip) return;
  try {
    await jobsStore.generateImages({ clipIds: [workspace.selectedClip.id] });
  } catch (e) {
    console.error('Failed to generate keyframe:', e);
  }
}

async function generateVideoClip(): Promise<void> {
  if (!workspace.selectedClip) return;
  try {
    await jobsStore.generateVideo({ clipIds: [workspace.selectedClip.id] });
  } catch (e) {
    console.error('Failed to generate video:', e);
  }
}
</script>

<style scoped lang="scss">
.properties-panel {
  height: 100%;
  overflow-y: auto;
}

.keyframe-thumb {
  max-width: 200px;
  max-height: 120px;
  border-radius: 4px;
  object-fit: cover;
}

.hidden {
  display: none;
}
</style>
