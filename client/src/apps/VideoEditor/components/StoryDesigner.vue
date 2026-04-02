<template>
  <div class="story-designer q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Story Designer</div>
      <q-space />
      <q-btn color="primary" icon="add" label="Add Scene" @click="addScene" />
    </div>

    <!-- Story Meta -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="row q-gutter-md">
          <q-input
            v-model="story.title"
            label="Story Title"
            outlined
            dense
            class="col"
            @update:model-value="markDirty"
          />
          <q-select
            v-model="story.genre"
            :options="genreOptions"
            label="Genre"
            outlined
            dense
            emit-value
            map-options
            class="col-3"
            @update:model-value="markDirty"
          />
        </div>
        <q-input
          v-model="story.synopsis"
          label="Synopsis"
          outlined
          dense
          type="textarea"
          rows="2"
          class="q-mt-sm"
          @update:model-value="markDirty"
        />
      </q-card-section>
    </q-card>

    <!-- AI Generation Settings -->
    <q-expansion-item
      icon="auto_awesome"
      label="AI Story Generation"
      caption="Configure model, provider, and script parameters"
      class="q-mb-md"
    >
      <q-card flat bordered>
        <q-card-section>
          <template v-if="storyLLMCapabilities">
            <GeneratorUiRenderer
              :schema="storyLLMCapabilities.ui_schema"
              :model-value="generatorConfig"
              @update:model-value="onGeneratorConfigChange"
            />
          </template>
          <div v-else class="text-grey-7 text-caption">Loading generator settings...</div>

          <q-separator class="q-my-md" />

          <div class="text-subtitle2 q-mb-sm">Script Parameters</div>
          <div class="row q-gutter-md">
            <q-input
              v-model.number="scriptParams.numScenes"
              label="Number of Scenes"
              type="number"
              outlined
              dense
              :min="1"
              :max="20"
              style="width: 150px"
            />
            <q-select
              v-model="scriptParams.targetDuration"
              :options="durationOptions"
              label="Target Duration"
              outlined
              dense
              emit-value
              map-options
              style="width: 180px"
            />
          </div>

          <q-separator class="q-my-md" />

          <div class="row q-gutter-sm">
            <q-btn
              v-if="generatorConfig.backend === 'local'"
              outline
              color="secondary"
              icon="download"
              label="Download Model"
              :loading="isDownloading"
              @click="downloadModel"
            >
              <q-tooltip>Download the selected HuggingFace model to local cache</q-tooltip>
            </q-btn>
            <q-btn
              color="primary"
              icon="auto_awesome"
              label="Generate Story with AI"
              :loading="isGenerating"
              @click="generateWithAI"
            />
          </div>

          <div v-if="activeProgress" class="q-mt-md">
            <q-linear-progress
              :value="activeProgress.overall_progress"
              color="primary"
              class="q-mb-xs"
            />
            <div class="text-caption text-grey-7">
              {{ activeProgress.message || activeProgress.stage }}
            </div>
          </div>
        </q-card-section>
      </q-card>
    </q-expansion-item>

    <!-- Scenes List -->
    <div class="scenes-container">
      <q-card
        v-for="(scene, index) in story.scenes"
        :key="scene.id"
        flat
        bordered
        class="scene-card q-mb-md"
        :class="{ 'ring-primary': workspace.selectedSceneId === scene.id }"
        @click="workspace.selectScene(scene.id)"
      >
        <q-card-section>
          <div class="row items-center q-mb-sm">
            <q-badge :label="`Scene ${index + 1}`" color="primary" class="q-mr-sm" />
            <q-input
              v-model="scene.title"
              placeholder="Scene title"
              dense
              borderless
              class="col text-h6"
              @update:model-value="markDirty"
            />
            <q-btn
              flat
              round
              size="sm"
              icon="arrow_upward"
              :disable="index === 0"
              @click.stop="moveScene(index, -1)"
            />
            <q-btn
              flat
              round
              size="sm"
              icon="arrow_downward"
              :disable="index === story.scenes.length - 1"
              @click.stop="moveScene(index, 1)"
            />
            <q-btn
              flat
              round
              size="sm"
              icon="delete"
              color="negative"
              @click.stop="removeScene(scene.id)"
            />
          </div>

          <div class="row q-gutter-md">
            <!-- Visual Description -->
            <div class="col-12">
              <div class="text-caption text-grey-7 q-mb-xs">Visual Description</div>
              <q-input
                v-model="scene.description.visual_prompt"
                outlined
                dense
                type="textarea"
                rows="2"
                placeholder="Describe the visual scene..."
                @update:model-value="markDirty"
              />
              <div class="row q-gutter-sm q-mt-xs">
                <q-input
                  v-model="scene.description.camera_notes"
                  outlined
                  dense
                  class="col"
                  placeholder="Camera notes (angle, movement)"
                  @update:model-value="markDirty"
                >
                  <template #prepend>
                    <q-icon name="videocam" size="xs" />
                  </template>
                </q-input>

                <!-- Background assignment -->
                <q-select
                  :model-value="getSceneBackground(scene)"
                  :options="backgroundOptions"
                  label="Background"
                  outlined
                  dense
                  emit-value
                  map-options
                  clearable
                  style="width: 200px"
                  @update:model-value="(v: string | null) => setSceneBackground(scene, v)"
                >
                  <template #prepend>
                    <q-icon name="landscape" size="xs" />
                  </template>
                </q-select>
              </div>
            </div>

            <!-- Script/Dialog Lines -->
            <div class="col-12">
              <div class="text-caption text-grey-7 q-mb-xs">Script / Dialog</div>
              <div
                v-for="(line, lineIndex) in scene.script_lines"
                :key="line.id || lineIndex"
                class="script-line row items-center q-gutter-sm q-mb-xs"
              >
                <!-- Character avatar + selector -->
                <q-select
                  v-model="line.character_id"
                  :options="characterOptionsWithNarrators"
                  dense
                  outlined
                  emit-value
                  map-options
                  style="width: 150px"
                  placeholder="Speaker"
                  @update:model-value="markDirty"
                >
                  <template #prepend>
                    <q-avatar v-if="getCharacterForLine(line)" size="20px" :color="getCharacterForLine(line)?.role === 'narrator' ? 'deep-purple' : 'primary'" text-color="white">
                      {{ (getCharacterForLine(line)?.name || 'N').charAt(0) }}
                    </q-avatar>
                    <q-icon v-else name="record_voice_over" size="16px" color="grey" />
                  </template>
                </q-select>

                <!-- Voice indicator -->
                <q-icon
                  :name="getLineVoiceIcon(line)"
                  :color="getLineVoiceColor(line)"
                  size="16px"
                >
                  <q-tooltip>{{ getLineVoiceTooltip(line) }}</q-tooltip>
                </q-icon>

                <!-- Dialog text -->
                <q-input
                  v-model="line.text"
                  dense
                  outlined
                  class="col"
                  placeholder="Dialog or narration..."
                  @update:model-value="markDirty"
                />

                <!-- Emotion hint -->
                <q-select
                  v-model="line.emotion_hint"
                  :options="emotionOptions"
                  dense
                  outlined
                  emit-value
                  map-options
                  clearable
                  style="width: 100px"
                  placeholder="Emotion"
                  @update:model-value="markDirty"
                />

                <!-- Voice preview -->
                <q-btn
                  flat
                  round
                  size="sm"
                  icon="play_circle"
                  color="primary"
                  :disable="!line.text"
                  @click.stop="previewLineVoice(scene, line)"
                >
                  <q-tooltip>Preview voice</q-tooltip>
                </q-btn>

                <q-btn flat round size="sm" icon="close" @click.stop="removeLine(scene, lineIndex)" />
              </div>
              <q-btn flat size="sm" icon="add" label="Add Line" @click="addLine(scene)" />
            </div>
          </div>

          <!-- Characters in Scene -->
          <div class="q-mt-sm">
            <div class="text-caption text-grey-7 q-mb-xs">Characters in scene</div>
            <q-chip
              v-for="charId in scene.character_ids"
              :key="charId"
              removable
              :color="getCharacterById(charId)?.role === 'narrator' ? 'deep-purple' : 'primary'"
              text-color="white"
              size="sm"
              @remove="removeCharacterFromScene(scene, charId)"
            >
              {{ getCharacterName(charId) }}
            </q-chip>
            <q-btn-dropdown flat size="sm" icon="person_add" label="Add" class="q-ml-xs">
              <q-list>
                <q-item
                  v-for="char in availableCharactersForScene(scene)"
                  :key="char.id"
                  clickable
                  v-close-popup
                  @click="addCharToScene(scene, char.id)"
                >
                  <q-item-section avatar>
                    <q-avatar size="24px" :color="char.role === 'narrator' ? 'deep-purple' : 'primary'" text-color="white">
                      {{ char.name.charAt(0) }}
                    </q-avatar>
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ char.name }}</q-item-label>
                    <q-item-label v-if="char.role === 'narrator'" caption>Narrator</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-if="library.characters.length === 0" class="text-grey">
                  <q-item-section>No characters. Create some first.</q-item-section>
                </q-item>
              </q-list>
            </q-btn-dropdown>
          </div>
        </q-card-section>
      </q-card>

      <div v-if="story.scenes.length === 0" class="text-center q-pa-xl text-grey">
        <q-icon name="movie" size="64px" class="q-mb-md" />
        <div class="text-h6">No scenes yet</div>
        <div class="q-mb-md">Add your first scene or generate a story with AI</div>
        <q-btn color="primary" icon="add" label="Add First Scene" @click="addScene" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, watch, onMounted } from 'vue';
import { useVideoProjectStore, useVideoJobsStore, useVideoWorkspaceStore } from '../stores';
import GeneratorUiRenderer from './GeneratorUiRenderer.vue';
import type { StoryScene, ScriptLine, CharacterAsset } from '../types';

const projectStore = useVideoProjectStore();
const jobsStore = useVideoJobsStore();
const workspace = useVideoWorkspaceStore();

const story = computed(() => projectStore.story);
const library = computed(() => projectStore.library);

const genreOptions = [
  { label: 'Advertising', value: 'advertising' },
  { label: 'Movie', value: 'movie' },
  { label: 'Documentary', value: 'documentary' },
  { label: 'Music Video', value: 'music_video' },
  { label: 'Educational', value: 'educational' },
  { label: 'Other', value: 'other' },
];

const emotionOptions = [
  { label: 'Neutral', value: 'neutral' },
  { label: 'Happy', value: 'happy' },
  { label: 'Sad', value: 'sad' },
  { label: 'Angry', value: 'angry' },
  { label: 'Excited', value: 'excited' },
  { label: 'Whisper', value: 'whisper' },
  { label: 'Dramatic', value: 'dramatic' },
  { label: 'Sarcastic', value: 'sarcastic' },
];

const characterOptionsWithNarrators = computed(() => [
  { label: '(Narrator - default)', value: null },
  ...library.value.characters.map((c) => ({
    label: `${c.name}${c.role === 'narrator' ? ' [N]' : ''}`,
    value: c.id,
  })),
]);

const backgroundOptions = computed(() => [
  ...library.value.products
    .filter((p) => p.category === 'background')
    .map((p) => ({
      label: p.name,
      value: p.id,
    })),
]);

// AI Generation Settings
const storyLLMCapabilities = computed(
  () => jobsStore.generators.find((g) => g.id === 'story_llm') ?? null,
);

const generatorConfig = reactive<Record<string, unknown>>({
  backend: 'local',
  model_repo_id: 'Qwen/Qwen2.5-3B-Instruct',
  custom_model_repo_id: '',
  torch_dtype: 'auto',
  provider_type: 'ollama',
  provider_base_url: 'http://localhost:11434',
  provider_model_id: 'llama3.1',
  provider_api_key: '',
  temperature: 0.7,
  max_new_tokens: 4096,
  top_p: 0.9,
});

const scriptParams = reactive({
  numScenes: 5,
  targetDuration: 60,
});

const durationOptions = [
  { label: '15 seconds', value: 15 },
  { label: '30 seconds', value: 30 },
  { label: '1 minute', value: 60 },
  { label: '2 minutes', value: 120 },
  { label: '3 minutes', value: 180 },
  { label: '5 minutes', value: 300 },
];

const isGenerating = ref(false);
const isDownloading = ref(false);

const activeProgress = computed(() => {
  const progress = jobsStore.activeJobProgress;
  if (!progress) return null;
  const activeJob = jobsStore.activeJob;
  if (activeJob && (activeJob.type === 'script_generate' || activeJob.type === 'model_download')) {
    return progress;
  }
  return null;
});

onMounted(() => {
  loadSavedConfig();
});

watch(
  () => projectStore.projectId,
  () => loadSavedConfig(),
);

function loadSavedConfig(): void {
  const saved = projectStore.settings?.generator_configs?.story_llm;
  if (saved && typeof saved === 'object') {
    Object.assign(generatorConfig, saved);
  }
}

function onGeneratorConfigChange(newValues: Record<string, unknown>): void {
  Object.assign(generatorConfig, newValues);
  saveConfigToProject();
}

function saveConfigToProject(): void {
  if (!projectStore.settings) return;
  const currentSettings = { ...projectStore.settings };
  const configs = { ...(currentSettings.generator_configs || {}) };
  configs.story_llm = { ...generatorConfig };
  currentSettings.generator_configs = configs;
  void projectStore.updateSettings(currentSettings);
}

// Character helpers
function getCharacterById(id: string): CharacterAsset | undefined {
  return library.value.characters.find((c) => c.id === id);
}

function getCharacterName(id: string): string {
  return getCharacterById(id)?.name || 'Unknown';
}

function getCharacterForLine(line: ScriptLine): CharacterAsset | null {
  if (!line.character_id) return null;
  return getCharacterById(line.character_id) ?? null;
}

function getLineVoiceIcon(line: ScriptLine): string {
  const char = getCharacterForLine(line);
  if (!char) return 'record_voice_over';
  if (char.voice_id) {
    const voice = library.value.voices.find((v) => v.id === char.voice_id);
    return voice ? 'mic' : 'mic_off';
  }
  return 'mic_off';
}

function getLineVoiceColor(line: ScriptLine): string {
  const char = getCharacterForLine(line);
  if (!char) return 'grey';
  return char.voice_id ? 'positive' : 'warning';
}

function getLineVoiceTooltip(line: ScriptLine): string {
  const char = getCharacterForLine(line);
  if (!char) return 'Default narrator voice';
  if (char.voice_id) {
    const voice = library.value.voices.find((v) => v.id === char.voice_id);
    return voice ? `Voice: ${voice.name}` : 'Voice not found';
  }
  return 'No voice assigned';
}

function getSceneBackground(scene: StoryScene): string | null {
  return scene.description.style_ref?.asset_id ?? null;
}

function setSceneBackground(scene: StoryScene, productId: string | null): void {
  if (productId) {
    scene.description.style_ref = { asset_id: productId, asset_type: 'product' };
  } else {
    delete scene.description.style_ref;
  }
  markDirty();
}

function availableCharactersForScene(scene: StoryScene): CharacterAsset[] {
  return library.value.characters.filter((c) => !scene.character_ids.includes(c.id));
}

// Scene Management
function markDirty(): void {
  projectStore.markDirty();
}

function addScene(): void {
  projectStore.addScene({
    order: story.value.scenes.length,
    title: `Scene ${story.value.scenes.length + 1}`,
    script_lines: [],
    description: { visual_prompt: '' },
    character_ids: [],
    product_ids: [],
    generation_overrides: {
      lora_refs: [],
    },
  });
}

function removeScene(id: string): void {
  if (confirm('Remove this scene?')) {
    projectStore.removeScene(id);
    if (workspace.selectedSceneId === id) {
      workspace.selectScene(null);
    }
  }
}

function moveScene(index: number, direction: number): void {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= story.value.scenes.length) return;
  const sceneIds = story.value.scenes.map((s) => s.id).filter((id): id is string => !!id);
  if (sceneIds[index] && sceneIds[newIndex]) {
    [sceneIds[index], sceneIds[newIndex]] = [sceneIds[newIndex], sceneIds[index]];
    projectStore.reorderScenes(sceneIds);
  }
}

function addLine(scene: StoryScene): void {
  scene.script_lines.push({
    id: crypto.randomUUID(),
    text: '',
  });
  markDirty();
}

function removeLine(scene: StoryScene, index: number): void {
  scene.script_lines.splice(index, 1);
  markDirty();
}

function addCharToScene(scene: StoryScene, charId: string): void {
  if (!scene.character_ids.includes(charId)) {
    scene.character_ids.push(charId);
    markDirty();
  }
}

function removeCharacterFromScene(scene: StoryScene, charId: string): void {
  scene.character_ids = scene.character_ids.filter((id) => id !== charId);
  markDirty();
}

async function previewLineVoice(scene: StoryScene, line: ScriptLine): Promise<void> {
  if (!line.text) return;
  try {
    await jobsStore.generateAudio({
      clipIds: [],
      generatorConfig: {
        text: line.text,
        character_id: line.character_id,
        preview: true,
      },
    });
  } catch (e) {
    console.error('Failed to preview voice:', e);
  }
}

// AI Actions
async function downloadModel(): Promise<void> {
  isDownloading.value = true;
  try {
    await jobsStore.startJob('model_download', {
      generatorId: 'story_llm',
      generatorConfig: { ...generatorConfig },
    });
  } catch (e) {
    console.error('Failed to start model download:', e);
  } finally {
    isDownloading.value = false;
  }
}

async function generateWithAI(): Promise<void> {
  isGenerating.value = true;
  try {
    await jobsStore.generateStory({
      topic: story.value.title || 'A compelling video story',
      ...(story.value.genre && { genre: story.value.genre }),
      numScenes: scriptParams.numScenes,
      targetDurationSeconds: scriptParams.targetDuration,
      generatorConfig: { ...generatorConfig },
    });
  } catch (e) {
    console.error('Failed to start story generation:', e);
  } finally {
    isGenerating.value = false;
  }
}
</script>

<style scoped lang="scss">
.story-designer {
  max-width: 1200px;
  margin: 0 auto;
}

.scenes-container {
  .scene-card {
    transition: box-shadow 0.2s;

    &:hover {
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    &.ring-primary {
      outline: 2px solid var(--q-primary);
    }
  }
}

.script-line {
  background: rgba(0, 0, 0, 0.02);
  padding: 4px;
  border-radius: 4px;
}
</style>
