<template>
  <div class="character-designer q-pa-md">
    <q-tabs v-model="activeTab" dense align="left" class="q-mb-md">
      <q-tab name="characters" label="Characters" icon="face" />
      <q-tab name="backgrounds" label="Backgrounds & Props" icon="landscape" />
    </q-tabs>

    <!-- Characters Tab -->
    <div v-if="activeTab === 'characters'">
      <div class="row items-center q-mb-md">
        <div class="text-h6">Characters</div>
        <q-space />
        <q-btn color="primary" size="sm" icon="add" label="Add Character" @click="addCharacter" />
        <q-btn flat size="sm" icon="person_add" label="Add Narrator" class="q-ml-sm" @click="addNarrator" />
      </div>

      <div v-if="characters.length === 0" class="text-center q-pa-xl text-grey">
        <q-icon name="face" size="64px" class="q-mb-md" />
        <div class="text-h6">No characters yet</div>
        <div class="q-mb-md">Add characters to use in your story</div>
      </div>

      <div class="row q-gutter-md">
        <!-- Character List -->
        <div class="col-12 col-md-4">
          <q-list bordered separator class="rounded-borders">
            <q-item
              v-for="char in characters"
              :key="char.id"
              clickable
              :active="workspace.selectedCharacterId === char.id"
              active-class="bg-blue-1"
              @click="workspace.selectCharacter(char.id)"
            >
              <q-item-section avatar>
                <q-avatar v-if="charThumbUrl(char)" size="40px">
                  <img :src="charThumbUrl(char)!" />
                </q-avatar>
                <q-avatar v-else size="40px" :color="char.role === 'narrator' ? 'deep-purple' : 'primary'" text-color="white">
                  {{ char.name.charAt(0).toUpperCase() }}
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ char.name }}</q-item-label>
                <q-item-label caption>
                  <q-badge v-if="char.role === 'narrator'" color="deep-purple" label="Narrator" class="q-mr-xs" />
                  <span>{{ char.code }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn flat round size="sm" icon="delete" color="negative" @click.stop="removeChar(char.id)" />
              </q-item-section>
            </q-item>
          </q-list>
        </div>

        <!-- Character Editor -->
        <div v-if="editingChar" class="col">
          <q-card flat bordered>
            <q-card-section>
              <div class="text-subtitle1 q-mb-md">Edit Character</div>

              <div class="row q-gutter-md q-mb-md">
                <q-input v-model="editingChar.name" label="Name" outlined dense class="col" @update:model-value="markDirty" />
                <q-input v-model="editingChar.code" label="Code" outlined dense style="width: 120px" @update:model-value="markDirty" />
              </div>

              <q-select
                v-model="editingChar.role"
                :options="roleOptions"
                label="Role"
                outlined
                dense
                emit-value
                map-options
                class="q-mb-md"
                @update:model-value="markDirty"
              />

              <q-input
                v-model="editingChar.description"
                label="Description"
                outlined
                dense
                type="textarea"
                rows="2"
                class="q-mb-md"
                @update:model-value="markDirty"
              />

              <q-input
                v-model="editingChar.style_hints"
                label="Style Hints (for image generation)"
                outlined
                dense
                type="textarea"
                rows="2"
                class="q-mb-md"
                @update:model-value="markDirty"
              />
            </q-card-section>

            <!-- Image Section -->
            <q-separator />
            <q-card-section>
              <div class="text-subtitle2 q-mb-sm">Character Image</div>

              <div v-if="charThumbUrl(editingChar)" class="q-mb-md text-center">
                <img :src="charThumbUrl(editingChar)!" class="character-image" />
              </div>

              <div class="row q-gutter-sm">
                <q-btn outline size="sm" icon="upload" label="Upload Image" @click="uploadCharImage" />
                <q-btn outline size="sm" icon="auto_awesome" label="Generate Image" @click="generateCharImage" />
              </div>
              <input ref="charImageInput" type="file" accept="image/*" class="hidden" @change="onCharImageSelected" />

              <q-input
                v-model="genPrompt"
                label="Generation prompt"
                outlined
                dense
                type="textarea"
                rows="2"
                class="q-mt-md"
                placeholder="A portrait of the character, detailed, high quality..."
              />
            </q-card-section>

            <!-- Pose Gallery -->
            <q-separator />
            <q-card-section>
              <div class="text-subtitle2 q-mb-sm">Pose Gallery</div>
              <div class="row q-gutter-sm">
                <div v-for="(posePath, poseName) in editingChar.pose_images" :key="poseName" class="pose-thumb">
                  <img v-if="posePath" :src="getAssetUrl(posePath)" class="pose-image" />
                  <div class="text-caption text-center">{{ poseName }}</div>
                </div>
                <q-btn outline size="sm" icon="add_photo_alternate" label="Add Pose" @click="addPose" />
              </div>
            </q-card-section>

            <!-- Voice Assignment -->
            <q-separator />
            <q-card-section>
              <div class="text-subtitle2 q-mb-sm">Voice</div>
              <q-select
                v-model="editingChar.voice_id"
                :options="voiceOptions"
                label="Assigned Voice"
                outlined
                dense
                emit-value
                map-options
                clearable
                @update:model-value="markDirty"
              />
              <q-btn flat size="sm" icon="mic" label="Go to Voices" class="q-mt-sm" @click="workspace.setMode('voices')" />
            </q-card-section>
          </q-card>
        </div>
      </div>
    </div>

    <!-- Backgrounds & Props Tab -->
    <div v-if="activeTab === 'backgrounds'">
      <BackgroundPropsManager />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore, useVideoJobsStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';
import BackgroundPropsManager from './BackgroundPropsManager.vue';
import type { CharacterAsset } from '../types';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();
const jobsStore = useVideoJobsStore();
const companion = useVideoCompanionStore();

const charImageInput = ref<HTMLInputElement | null>(null);
const genPrompt = ref('');
const activeTab = ref('characters');

const characters = computed(() => projectStore.library.characters);
const editingChar = computed(() => workspace.selectedCharacter);

const roleOptions = [
  { label: 'Character', value: 'character' },
  { label: 'Narrator', value: 'narrator' },
  { label: 'Extra', value: 'extra' },
];

const voiceOptions = computed(() =>
  projectStore.library.voices.map((v) => ({
    label: `${v.name} (${v.language})`,
    value: v.id,
  })),
);

function charThumbUrl(char: CharacterAsset): string | null {
  if (!char.image_path || !projectStore.project) return null;
  return companion.getAssetUrl(projectStore.project.id, char.image_path);
}

function getAssetUrl(path: string): string {
  if (!projectStore.project) return '';
  return companion.getAssetUrl(projectStore.project.id, path);
}

function markDirty(): void {
  projectStore.markDirty();
}

function addCharacter(): void {
  const name = prompt('Character name:');
  if (!name) return;
  const code = name.toLowerCase().replace(/\s+/g, '_').slice(0, 16);
  projectStore.addCharacter({ name, code, role: 'character', pose_images: {} });
}

function addNarrator(): void {
  const name = prompt('Narrator name:', 'Narrator');
  if (!name) return;
  const code = name.toLowerCase().replace(/\s+/g, '_').slice(0, 16);
  projectStore.addCharacter({ name, code, role: 'narrator', pose_images: {} });
}

function removeChar(id: string): void {
  if (!confirm('Remove this character?')) return;
  projectStore.removeCharacter(id);
  if (workspace.selectedCharacterId === id) workspace.selectCharacter(null);
}

function uploadCharImage(): void {
  charImageInput.value?.click();
}

async function onCharImageSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !editingChar.value || !projectStore.project) return;
  try {
    const result = await companion.uploadAsset(projectStore.project.id, file, { assetType: 'character', subfolder: `characters/${editingChar.value.code}` });
    if (result?.path) {
      projectStore.updateCharacter(editingChar.value.id, { image_path: result.path });
    }
  } catch (e) {
    console.error('Failed to upload character image:', e);
  }
  input.value = '';
}

async function generateCharImage(): Promise<void> {
  if (!editingChar.value || !projectStore.project) return;
  const finalPrompt = genPrompt.value || `A portrait of ${editingChar.value.name}, ${editingChar.value.style_hints || 'detailed, high quality'}`;
  try {
    await jobsStore.generateImages({
      clipIds: [],
      generatorConfig: { prompt: finalPrompt, targetCharacterId: editingChar.value.id },
    });
  } catch (e) {
    console.error('Failed to generate character image:', e);
  }
}

function addPose(): void {
  if (!editingChar.value) return;
  const poseName = prompt('Pose name (e.g., "side_view", "happy"):');
  if (!poseName) return;
  editingChar.value.pose_images[poseName] = '';
  markDirty();
}
</script>

<style scoped lang="scss">
.character-designer {
  max-width: 1200px;
  margin: 0 auto;
}

.character-image {
  max-width: 200px;
  max-height: 200px;
  border-radius: 8px;
  object-fit: cover;
}

.pose-thumb {
  width: 80px;
  text-align: center;
}

.pose-image {
  width: 80px;
  height: 80px;
  border-radius: 4px;
  object-fit: cover;
}

.hidden {
  display: none;
}
</style>
