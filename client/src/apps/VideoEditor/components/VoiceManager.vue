<template>
  <div class="voice-manager q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Voices</div>
      <q-space />
      <q-btn outline icon="upload" label="Upload Voice" @click="uploadVoice" />
      <q-btn color="primary" icon="mic" label="Record Voice" class="q-ml-sm" @click="showRecorder = true" />
    </div>
    <input ref="voiceFileInput" type="file" accept="audio/*" class="hidden" @change="onVoiceFileSelected" />

    <div v-if="voices.length === 0 && !showRecorder" class="text-center q-pa-xl text-grey">
      <q-icon name="record_voice_over" size="64px" class="q-mb-md" />
      <div class="text-h6">No voices yet</div>
      <div class="q-mb-md">Upload or record voice samples for TTS cloning</div>
    </div>

    <div class="row q-gutter-md">
      <!-- Voice List -->
      <div class="col-12 col-md-4">
        <q-list bordered separator class="rounded-borders">
          <q-item
            v-for="voice in voices"
            :key="voice.id"
            clickable
            :active="workspace.selectedVoiceId === voice.id"
            active-class="bg-blue-1"
            @click="workspace.selectVoice(voice.id)"
          >
            <q-item-section avatar>
              <q-icon name="mic" :color="voice.gender === 'female' ? 'pink' : 'blue'" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ voice.name }}</q-item-label>
              <q-item-label caption>{{ voice.language }} &middot; {{ voice.code }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="row q-gutter-xs">
                <q-btn
                  v-if="voice.sample_path"
                  flat
                  round
                  size="sm"
                  :icon="playingVoiceId === voice.id ? 'stop' : 'play_arrow'"
                  color="primary"
                  @click.stop="togglePreview(voice)"
                />
                <q-btn flat round size="sm" icon="delete" color="negative" @click.stop="removeVoice(voice.id)" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </div>

      <!-- Voice Editor / Recorder -->
      <div class="col">
        <!-- Recorder Panel -->
        <q-card v-if="showRecorder" flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 q-mb-md">Record Voice Sample</div>
            <VoiceRecorder @recorded="onRecorded" @cancel="showRecorder = false" />
          </q-card-section>
        </q-card>

        <!-- Voice Editor -->
        <q-card v-if="editingVoice" flat bordered>
          <q-card-section>
            <div class="text-subtitle1 q-mb-md">Edit Voice</div>

            <div class="row q-gutter-md q-mb-md">
              <q-input v-model="editingVoice.name" label="Name" outlined dense class="col" @update:model-value="markDirty" />
              <q-input v-model="editingVoice.code" label="Code" outlined dense style="width: 120px" @update:model-value="markDirty" />
            </div>

            <div class="row q-gutter-md q-mb-md">
              <q-select
                v-model="editingVoice.language"
                :options="languageOptions"
                label="Language"
                outlined
                dense
                emit-value
                map-options
                class="col"
                @update:model-value="markDirty"
              />
              <q-select
                v-model="editingVoice.gender"
                :options="genderOptions"
                label="Gender"
                outlined
                dense
                emit-value
                map-options
                class="col"
                @update:model-value="markDirty"
              />
            </div>

            <q-input
              v-model="editingVoice.description"
              label="Description"
              outlined
              dense
              type="textarea"
              rows="2"
              class="q-mb-md"
              @update:model-value="markDirty"
            />

            <div v-if="editingVoice.sample_path" class="q-mt-md">
              <q-chip icon="audiotrack" color="primary" text-color="white">
                {{ editingVoice.sample_path.split('/').pop() }}
              </q-chip>
            </div>

            <!-- Characters using this voice -->
            <div class="q-mt-md">
              <div class="text-caption text-grey q-mb-xs">Used by characters:</div>
              <div v-if="charactersUsingVoice.length === 0" class="text-caption text-grey-5">
                No characters assigned
              </div>
              <q-chip
                v-for="char in charactersUsingVoice"
                :key="char.id"
                size="sm"
                color="primary"
                text-color="white"
              >
                {{ char.name }}
              </q-chip>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Hidden audio element for preview -->
    <audio ref="previewAudio" @ended="playingVoiceId = null" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';
import VoiceRecorder from './VoiceRecorder.vue';
import type { VoiceAsset } from '../types';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();
const companion = useVideoCompanionStore();

const voiceFileInput = ref<HTMLInputElement | null>(null);
const previewAudio = ref<HTMLAudioElement | null>(null);
const showRecorder = ref(false);
const playingVoiceId = ref<string | null>(null);

const voices = computed(() => projectStore.library.voices);

const editingVoice = computed(() => workspace.selectedVoice);

const charactersUsingVoice = computed(() => {
  if (!editingVoice.value) return [];
  return projectStore.library.characters.filter(
    (c) => c.voice_id === editingVoice.value!.id,
  );
});

const languageOptions = [
  { label: 'English', value: 'en' },
  { label: 'Spanish', value: 'es' },
  { label: 'French', value: 'fr' },
  { label: 'German', value: 'de' },
  { label: 'Italian', value: 'it' },
  { label: 'Portuguese', value: 'pt' },
  { label: 'Chinese', value: 'zh' },
  { label: 'Japanese', value: 'ja' },
  { label: 'Korean', value: 'ko' },
  { label: 'Hindi', value: 'hi' },
];

const genderOptions = [
  { label: 'Male', value: 'male' },
  { label: 'Female', value: 'female' },
  { label: 'Neutral', value: 'neutral' },
];

function markDirty(): void {
  projectStore.markDirty();
}

function uploadVoice(): void {
  voiceFileInput.value?.click();
}

async function onVoiceFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !projectStore.project) return;

  const name = prompt('Voice name:', file.name.replace(/\.[^.]+$/, ''));
  if (!name) return;
  const code = name.toLowerCase().replace(/\s+/g, '_').slice(0, 16);

  try {
    const result = await companion.uploadAsset(
      projectStore.project.id,
      file,
      { assetType: 'voice', subfolder: 'voices' },
    );
    if (result?.path) {
      projectStore.addVoice({
        name,
        code,
        sample_path: result.path,
        language: 'en',
      });
    }
  } catch (e) {
    console.error('Failed to upload voice:', e);
  }
  input.value = '';
}

async function onRecorded(blob: Blob): Promise<void> {
  if (!projectStore.project) return;
  showRecorder.value = false;

  const name = prompt('Voice name:');
  if (!name) return;
  const code = name.toLowerCase().replace(/\s+/g, '_').slice(0, 16);

  const file = new File([blob], `${code}.wav`, { type: 'audio/wav' });
  try {
    const result = await companion.uploadAsset(
      projectStore.project.id,
      file,
      { assetType: 'voice', subfolder: 'voices' },
    );
    if (result?.path) {
      projectStore.addVoice({
        name,
        code,
        sample_path: result.path,
        language: 'en',
      });
    }
  } catch (e) {
    console.error('Failed to upload recorded voice:', e);
  }
}

function togglePreview(voice: VoiceAsset): void {
  if (!previewAudio.value || !projectStore.project) return;

  if (playingVoiceId.value === voice.id) {
    previewAudio.value.pause();
    previewAudio.value.currentTime = 0;
    playingVoiceId.value = null;
    return;
  }

  previewAudio.value.src = companion.getAssetUrl(projectStore.project.id, voice.sample_path);
  void previewAudio.value.play();
  playingVoiceId.value = voice.id;
}

function removeVoice(id: string): void {
  if (!confirm('Remove this voice?')) return;
  const usedBy = projectStore.library.characters.filter((c) => c.voice_id === id);
  if (usedBy.length > 0) {
    if (!confirm(`This voice is used by ${usedBy.map((c) => c.name).join(', ')}. Remove anyway?`)) return;
  }
  projectStore.removeVoice(id);
  if (workspace.selectedVoiceId === id) {
    workspace.selectVoice(null);
  }
}
</script>

<style scoped lang="scss">
.voice-manager {
  max-width: 1200px;
  margin: 0 auto;
}

.hidden {
  display: none;
}
</style>
