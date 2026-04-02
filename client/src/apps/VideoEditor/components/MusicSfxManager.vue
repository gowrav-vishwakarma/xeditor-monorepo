<template>
  <div class="music-sfx-manager q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Music & Sound Effects</div>
      <q-space />
      <q-btn outline icon="upload" label="Upload" @click="uploadAudio" />
      <q-btn color="primary" icon="auto_awesome" label="Generate" class="q-ml-sm" @click="showGenerate = true" />
    </div>
    <input ref="audioFileInput" type="file" accept="audio/*" class="hidden" @change="onAudioFileSelected" />

    <q-tabs v-model="activeTab" dense align="left" class="q-mb-md">
      <q-tab name="music" label="Music" icon="music_note" />
      <q-tab name="sfx" label="Sound Effects" icon="surround_sound" />
      <q-tab name="ambient" label="Ambient" icon="nature" />
    </q-tabs>

    <!-- Music Tab -->
    <div v-if="activeTab === 'music'">
      <div v-if="musicAssets.length === 0" class="text-center q-pa-xl text-grey">
        <q-icon name="music_note" size="64px" class="q-mb-md" />
        <div class="text-h6">No music yet</div>
        <div class="q-mb-md">Upload audio files or generate background music with AI</div>
      </div>

      <q-list v-else bordered separator class="rounded-borders">
        <q-item v-for="asset in musicAssets" :key="asset.id" clickable @click="selectMusic(asset.id)">
          <q-item-section avatar>
            <q-icon name="music_note" color="deep-purple" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ asset.name }}</q-item-label>
            <q-item-label caption>
              <span v-if="asset.duration_seconds">{{ formatDuration(asset.duration_seconds) }}</span>
              <span v-if="asset.genre"> &middot; {{ asset.genre }}</span>
              <span v-if="asset.mood"> &middot; {{ asset.mood }}</span>
              <span v-if="asset.tempo_bpm"> &middot; {{ asset.tempo_bpm }} BPM</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row q-gutter-xs">
              <q-btn
                flat
                round
                size="sm"
                :icon="playingAssetId === asset.id ? 'stop' : 'play_arrow'"
                color="primary"
                @click.stop="togglePreview(asset.id, asset.path)"
              />
              <q-btn flat round size="sm" icon="add_to_queue" color="secondary" @click.stop="addToTimeline(asset, 'audio_music')">
                <q-tooltip>Add to Music track</q-tooltip>
              </q-btn>
              <q-btn flat round size="sm" icon="delete" color="negative" @click.stop="removeMusic(asset.id)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- SFX Tab -->
    <div v-if="activeTab === 'sfx'">
      <div v-if="sfxAssets.length === 0" class="text-center q-pa-xl text-grey">
        <q-icon name="surround_sound" size="64px" class="q-mb-md" />
        <div class="text-h6">No sound effects yet</div>
        <div class="q-mb-md">Upload audio files or generate sound effects with AI</div>
      </div>

      <q-list v-else bordered separator class="rounded-borders">
        <q-item v-for="asset in sfxAssets" :key="asset.id" clickable>
          <q-item-section avatar>
            <q-icon name="surround_sound" color="teal" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ asset.name }}</q-item-label>
            <q-item-label caption>
              <span v-if="asset.duration_seconds">{{ formatDuration(asset.duration_seconds) }}</span>
              <span v-if="asset.category"> &middot; {{ asset.category }}</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row q-gutter-xs">
              <q-btn
                flat
                round
                size="sm"
                :icon="playingAssetId === asset.id ? 'stop' : 'play_arrow'"
                color="primary"
                @click.stop="togglePreview(asset.id, asset.path)"
              />
              <q-btn flat round size="sm" icon="add_to_queue" color="secondary" @click.stop="addToTimeline(asset, 'audio_sfx')">
                <q-tooltip>Add to SFX track</q-tooltip>
              </q-btn>
              <q-btn flat round size="sm" icon="delete" color="negative" @click.stop="removeSfx(asset.id)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Ambient Tab -->
    <div v-if="activeTab === 'ambient'">
      <div v-if="ambientAssets.length === 0" class="text-center q-pa-xl text-grey">
        <q-icon name="nature" size="64px" class="q-mb-md" />
        <div class="text-h6">No ambient audio yet</div>
        <div class="q-mb-md">Add looping ambient sounds (rain, crowd, forest...)</div>
      </div>

      <q-list v-else bordered separator class="rounded-borders">
        <q-item v-for="asset in ambientAssets" :key="asset.id" clickable>
          <q-item-section avatar>
            <q-icon name="nature" color="green" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ asset.name }}</q-item-label>
            <q-item-label caption>
              <q-badge color="green" label="Loop" class="q-mr-xs" />
              <span v-if="asset.duration_seconds">{{ formatDuration(asset.duration_seconds) }}</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row q-gutter-xs">
              <q-btn
                flat
                round
                size="sm"
                :icon="playingAssetId === asset.id ? 'stop' : 'play_arrow'"
                color="primary"
                @click.stop="togglePreview(asset.id, asset.path)"
              />
              <q-btn flat round size="sm" icon="add_to_queue" color="secondary" @click.stop="addToTimeline(asset, 'audio_sfx')">
                <q-tooltip>Add to timeline</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </div>

    <!-- Hidden audio for preview -->
    <audio ref="previewAudio" @ended="playingAssetId = null" />

    <!-- Generate Dialog -->
    <q-dialog v-model="showGenerate">
      <q-card style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">Generate {{ activeTab === 'sfx' ? 'Sound Effect' : 'Music' }}</div>
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="genPrompt"
            label="Description"
            outlined
            type="textarea"
            rows="3"
            :placeholder="genPlaceholder"
          />
          <div class="row q-gutter-md q-mt-md">
            <q-input
              v-model.number="genDuration"
              label="Duration (seconds)"
              type="number"
              outlined
              dense
              :min="1"
              :max="activeTab === 'sfx' ? 10 : 300"
              style="width: 160px"
            />
            <q-select
              v-if="activeTab === 'music'"
              v-model="genGenre"
              :options="genreOptions"
              label="Genre"
              outlined
              dense
              emit-value
              map-options
              clearable
              class="col"
            />
          </div>
          <q-toggle
            v-if="activeTab === 'ambient' || activeTab === 'music'"
            v-model="genLoop"
            label="Loop-compatible"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Generate" @click="generateAudio" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore, useVideoJobsStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';
import type { MusicAsset, SfxAsset } from '../types';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();
const jobsStore = useVideoJobsStore();
const companion = useVideoCompanionStore();

const audioFileInput = ref<HTMLInputElement | null>(null);
const previewAudio = ref<HTMLAudioElement | null>(null);
const activeTab = ref('music');
const showGenerate = ref(false);
const playingAssetId = ref<string | null>(null);

const genPrompt = ref('');
const genDuration = ref(30);
const genGenre = ref('');
const genLoop = ref(false);

const musicAssets = computed(() => projectStore.library.music ?? []);
const sfxAssets = computed(() => (projectStore.library.sfx ?? []).filter((s) => !s.category?.includes('ambient')));
const ambientAssets = computed(() => (projectStore.library.sfx ?? []).filter((s) => s.category?.includes('ambient')));

const genPlaceholder = computed(() => {
  if (activeTab.value === 'sfx') return 'Door creaking open, glass breaking, footsteps on gravel...';
  if (activeTab.value === 'ambient') return 'Rain on a rooftop, busy cafe, forest birds chirping...';
  return 'Upbeat corporate background music, 120 BPM, modern feel...';
});

const genreOptions = [
  { label: 'Ambient', value: 'ambient' },
  { label: 'Corporate', value: 'corporate' },
  { label: 'Cinematic', value: 'cinematic' },
  { label: 'Electronic', value: 'electronic' },
  { label: 'Jazz', value: 'jazz' },
  { label: 'Classical', value: 'classical' },
  { label: 'Pop', value: 'pop' },
  { label: 'Rock', value: 'rock' },
  { label: 'Hip Hop', value: 'hip_hop' },
  { label: 'Lo-fi', value: 'lofi' },
];

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function uploadAudio(): void {
  audioFileInput.value?.click();
}

async function onAudioFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !projectStore.project) return;

  const name = prompt('Name:', file.name.replace(/\.[^.]+$/, ''));
  if (!name) return;

  const subfolder = activeTab.value === 'music' ? 'music' : 'sfx';
  const assetType = activeTab.value === 'music' ? 'audio' : 'audio';

  try {
    const result = await companion.uploadAsset(
      projectStore.project.id,
      file,
      { assetType, subfolder },
    );
    if (result?.path) {
      if (activeTab.value === 'music') {
        addMusicAsset(name, result.path);
      } else {
        addSfxAsset(name, result.path, activeTab.value === 'ambient');
      }
    }
  } catch (e) {
    console.error('Failed to upload audio:', e);
  }
  input.value = '';
}

function addMusicAsset(name: string, path: string): void {
  const lib = projectStore.library;
  if (!lib.music) lib.music = [];
  lib.music.push({
    id: crypto.randomUUID(),
    name,
    path,
    loop_compatible: genLoop.value,
    created_at: Date.now() / 1000,
  });
  projectStore.markDirty();
}

function addSfxAsset(name: string, path: string, isAmbient: boolean): void {
  const lib = projectStore.library;
  if (!lib.sfx) lib.sfx = [];
  const asset: SfxAsset = {
    id: crypto.randomUUID(),
    name,
    path,
    created_at: Date.now() / 1000,
  };
  if (isAmbient) asset.category = 'ambient';
  lib.sfx.push(asset);
  projectStore.markDirty();
}

function selectMusic(id: string): void {
  workspace.selectMusicClip(id);
}

function togglePreview(assetId: string, path: string): void {
  if (!previewAudio.value || !projectStore.project) return;

  if (playingAssetId.value === assetId) {
    previewAudio.value.pause();
    previewAudio.value.currentTime = 0;
    playingAssetId.value = null;
    return;
  }

  previewAudio.value.src = companion.getAssetUrl(projectStore.project.id, path);
  void previewAudio.value.play();
  playingAssetId.value = assetId;
}

function addToTimeline(asset: MusicAsset | SfxAsset, trackId: string): void {
  const timeline = projectStore.timeline;
  const startTime = timeline.total_duration || 0;
  const duration = ('duration_seconds' in asset && asset.duration_seconds) ? asset.duration_seconds : 10;

  projectStore.addClip({
    track_id: trackId,
    start_time: startTime,
    duration,
    source_type: 'imported',
    status: 'done',
    audio_artifact_path: asset.path,
    script_line_ids: [],
    volume: 1.0,
    fade_in_seconds: 0,
    fade_out_seconds: 0,
    loop: 'loop_compatible' in asset ? asset.loop_compatible : false,
  });
}

function removeMusic(id: string): void {
  if (!confirm('Remove this music?')) return;
  const lib = projectStore.library;
  if (lib.music) {
    lib.music = lib.music.filter((m) => m.id !== id);
    projectStore.markDirty();
  }
}

function removeSfx(id: string): void {
  if (!confirm('Remove this sound effect?')) return;
  const lib = projectStore.library;
  if (lib.sfx) {
    lib.sfx = lib.sfx.filter((s) => s.id !== id);
    projectStore.markDirty();
  }
}

async function generateAudio(): Promise<void> {
  if (!genPrompt.value || !projectStore.project) return;
  const jobType = activeTab.value === 'sfx' || activeTab.value === 'ambient'
    ? 'sfx_generate'
    : 'music_generate';

  try {
    await jobsStore.startJob(jobType, {
      generatorConfig: {
        prompt: genPrompt.value,
        duration: genDuration.value,
        genre: genGenre.value || undefined,
        loop_compatible: genLoop.value,
      },
    });
  } catch (e) {
    console.error('Failed to generate audio:', e);
  }
  genPrompt.value = '';
}
</script>

<style scoped lang="scss">
.music-sfx-manager {
  max-width: 1200px;
  margin: 0 auto;
}

.hidden {
  display: none;
}
</style>
