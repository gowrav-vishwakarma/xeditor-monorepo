<template>
  <div class="export-panel q-pa-md">
    <div class="text-h5 q-mb-md">Export Project</div>

    <!-- Project Status -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Project Status</div>
        <div class="row q-gutter-md">
          <div class="col">
            <q-linear-progress
              :value="completionProgress"
              color="primary"
              size="24px"
              class="q-mb-sm"
            >
              <div class="absolute-full flex flex-center">
                <q-badge
                  color="white"
                  text-color="primary"
                  :label="`${Math.round(completionProgress * 100)}% Complete`"
                />
              </div>
            </q-linear-progress>
          </div>
        </div>

        <div class="row q-gutter-md q-mt-md">
          <div class="col text-center">
            <div class="text-h4">{{ totalClips }}</div>
            <div class="text-caption">Total Clips</div>
          </div>
          <div class="col text-center">
            <div class="text-h4 text-positive">{{ completedClips }}</div>
            <div class="text-caption">Completed</div>
          </div>
          <div class="col text-center">
            <div class="text-h4 text-warning">{{ pendingClips }}</div>
            <div class="text-caption">Pending</div>
          </div>
          <div class="col text-center">
            <div class="text-h4 text-negative">{{ staleClips }}</div>
            <div class="text-caption">Need Regen</div>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <!-- Full Pipeline -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Full Pipeline</div>
        <div class="text-caption text-grey q-mb-md">
          Run the complete generation pipeline: TTS audio, keyframe images, videos, then final merge.
        </div>
        <q-btn
          color="primary"
          icon="play_circle"
          label="Generate All"
          :loading="isRunningPipeline"
          class="full-width"
          @click="runFullPipeline"
        />
      </q-card-section>
    </q-card>

    <!-- Export Settings -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Export Settings</div>

        <div class="row q-gutter-md">
          <q-select
            v-model="exportFormat"
            :options="formatOptions"
            label="Format"
            outlined
            emit-value
            map-options
            class="col"
          />
          <q-select
            v-model="exportQuality"
            :options="qualityOptions"
            label="Quality"
            outlined
            emit-value
            map-options
            class="col"
          />
        </div>

        <div class="row q-gutter-md q-mt-sm">
          <q-input v-model="outputFilename" label="Output Filename" outlined class="col">
            <template #append>.{{ exportFormat }}</template>
          </q-input>
        </div>
      </q-card-section>
    </q-card>

    <!-- Audio Mixing -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Audio Mix</div>
        <div class="text-caption text-grey q-mb-md">
          Adjust volume levels for each audio track in the final export.
        </div>

        <div v-for="track in audioTracks" :key="track.id" class="row items-center q-mb-sm">
          <q-icon :name="trackIcon(track.type)" size="20px" class="q-mr-sm" />
          <span class="text-body2 col-2">{{ track.name }}</span>
          <q-slider
            v-model="trackVolumes[track.id]"
            :min="0"
            :max="150"
            :step="5"
            label
            :label-value="`${trackVolumes[track.id] ?? 100}%`"
            color="primary"
            class="col"
          />
          <q-toggle v-model="trackEnabled[track.id]" dense class="q-ml-sm" />
        </div>

        <q-separator class="q-my-md" />

        <q-toggle v-model="normalizeAudio" label="Normalize audio (LUFS target)" />
        <q-input
          v-if="normalizeAudio"
          v-model.number="lufsTarget"
          label="LUFS Target"
          type="number"
          outlined
          dense
          class="q-mt-sm"
          style="width: 120px"
        />
      </q-card-section>
    </q-card>

    <!-- Export Actions -->
    <q-card flat bordered>
      <q-card-section>
        <div class="row q-gutter-md">
          <q-btn
            :disable="staleClips > 0"
            color="primary"
            icon="movie"
            label="Export Video"
            size="lg"
            class="col"
            @click="exportVideo"
          />
          <q-btn
            v-if="staleClips > 0"
            color="warning"
            icon="refresh"
            label="Regenerate Stale Clips"
            size="lg"
            class="col"
            @click="regenerateStale"
          />
        </div>

        <q-banner v-if="staleClips > 0" class="bg-warning-1 q-mt-md">
          <template #avatar>
            <q-icon name="warning" color="warning" />
          </template>
          {{ staleClips }} clips need regeneration before export. Changes were made to scripts or
          keyframes since last generation.
        </q-banner>
      </q-card-section>
    </q-card>

    <!-- Export Progress -->
    <q-card v-if="isExporting" flat bordered class="q-mt-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">Exporting...</div>
        <q-linear-progress :value="exportProgress" color="primary" size="24px" />
        <div class="text-caption text-grey q-mt-sm">{{ exportStage }}</div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useVideoProjectStore, useVideoJobsStore } from '../stores';
import { isClipAudioStale, isClipVideoStale } from '../types';
import type { TrackType } from '../types';

const projectStore = useVideoProjectStore();
const jobsStore = useVideoJobsStore();

const timeline = computed(() => projectStore.timeline);

const exportFormat = ref('mp4');
const exportQuality = ref('high');
const outputFilename = ref('my_video');
const normalizeAudio = ref(false);
const lufsTarget = ref(-14);
const isRunningPipeline = ref(false);

const audioTracks = computed(() =>
  timeline.value.tracks.filter(
    (t) => t.type === 'audio' || t.type === 'music' || t.type === 'sfx',
  ),
);

const trackVolumes = ref<Record<string, number>>({});
const trackEnabled = ref<Record<string, boolean>>({});

function initTrackVolumes(): void {
  for (const track of audioTracks.value) {
    if (!(track.id in trackVolumes.value)) {
      trackVolumes.value[track.id] = track.id === 'audio_music' ? 60 : 100;
    }
    if (!(track.id in trackEnabled.value)) {
      trackEnabled.value[track.id] = true;
    }
  }
}

watch(audioTracks, () => initTrackVolumes(), { immediate: true });

function trackIcon(type: TrackType): string {
  switch (type) {
    case 'audio': return 'record_voice_over';
    case 'music': return 'music_note';
    case 'sfx': return 'surround_sound';
    default: return 'volume_up';
  }
}

const formatOptions = [
  { label: 'MP4 (H.264)', value: 'mp4' },
  { label: 'WebM (VP9)', value: 'webm' },
  { label: 'MOV (ProRes)', value: 'mov' },
];

const qualityOptions = [
  { label: 'Preview (Fast)', value: 'preview' },
  { label: 'Standard', value: 'standard' },
  { label: 'High Quality', value: 'high' },
  { label: 'Maximum', value: 'maximum' },
];

const totalClips = computed(() => timeline.value.clips.length);
const completedClips = computed(
  () => timeline.value.clips.filter((c) => c.status === 'done').length,
);
const pendingClips = computed(
  () =>
    timeline.value.clips.filter((c) =>
      ['draft', 'queued', 'generating'].includes(c.status),
    ).length,
);
const staleClips = computed(
  () =>
    timeline.value.clips.filter(
      (c) =>
        c.status === 'done' && (isClipAudioStale(c) || isClipVideoStale(c)),
    ).length,
);

const completionProgress = computed(() => {
  if (totalClips.value === 0) return 0;
  return completedClips.value / totalClips.value;
});

const isExporting = ref(false);
const exportProgress = ref(0);
const exportStage = ref('');

async function runFullPipeline(): Promise<void> {
  isRunningPipeline.value = true;
  try {
    const dialogClips = timeline.value.clips.filter((c) => c.track_id === 'audio_dialog');
    if (dialogClips.length > 0) {
      await jobsStore.generateAudio({ clipIds: dialogClips.map((c) => c.id) });
    }

    const videoClips = timeline.value.clips.filter((c) => c.track_id === 'video_main');
    if (videoClips.length > 0) {
      await jobsStore.generateImages({ clipIds: videoClips.map((c) => c.id) });
      await jobsStore.generateVideo({ clipIds: videoClips.map((c) => c.id) });
    }

    await jobsStore.exportProject();
  } catch (e) {
    console.error('Pipeline failed:', e);
  } finally {
    isRunningPipeline.value = false;
  }
}

async function exportVideo(): Promise<void> {
  try {
    isExporting.value = true;
    exportStage.value = 'Starting export...';
    await jobsStore.exportProject();
  } catch (e) {
    console.error('Export failed:', e);
  } finally {
    isExporting.value = false;
  }
}

async function regenerateStale(): Promise<void> {
  const staleClipIds = timeline.value.clips
    .filter(
      (c) =>
        c.status === 'done' && (isClipAudioStale(c) || isClipVideoStale(c)),
    )
    .map((c) => c.id);

  if (staleClipIds.length > 0) {
    await jobsStore.regenerateClips(staleClipIds, 'regen_all_stale');
  }
}
</script>

<style scoped lang="scss">
.export-panel {
  max-width: 800px;
  margin: 0 auto;
}
</style>
