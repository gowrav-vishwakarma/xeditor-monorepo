<template>
  <div class="asset-library-panel q-pa-sm">
    <div class="text-subtitle2 q-mb-sm">Asset Library</div>

    <q-expansion-item
      v-model="expandedSections.characters"
      icon="person"
      label="Characters"
      :caption="`${library.characters.length} items`"
      header-class="text-primary"
    >
      <q-list dense>
        <q-item
          v-for="char in library.characters"
          :key="char.id"
          clickable
          @click="selectAsset('character', char.id)"
        >
          <q-item-section avatar>
            <q-avatar v-if="char.image_path" size="32px">
              <img :src="char.image_path" />
            </q-avatar>
            <q-avatar v-else size="32px" color="primary" text-color="white">
              {{ char.name.charAt(0).toUpperCase() }}
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ char.name }}</q-item-label>
            <q-item-label caption>{{ char.code }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable @click="addCharacter">
          <q-item-section avatar>
            <q-icon name="add" color="grey" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-grey">Add Character</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-expansion-item>

    <q-expansion-item
      v-model="expandedSections.props"
      icon="category"
      label="Props & Backgrounds"
      :caption="`${library.products.length} items`"
      header-class="text-primary"
    >
      <q-list dense>
        <q-item
          v-for="prop in library.products"
          :key="prop.id"
          clickable
          @click="selectAsset('prop', prop.id)"
        >
          <q-item-section avatar>
            <q-icon name="image" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ prop.name }}</q-item-label>
            <q-item-label caption>{{ prop.category || 'Uncategorized' }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable @click="addProp">
          <q-item-section avatar>
            <q-icon name="add" color="grey" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-grey">Add Prop</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-expansion-item>

    <q-expansion-item
      v-model="expandedSections.voices"
      icon="record_voice_over"
      label="Voices"
      :caption="`${library.voices.length} items`"
      header-class="text-primary"
    >
      <q-list dense>
        <q-item
          v-for="voice in library.voices"
          :key="voice.id"
          clickable
          @click="selectAsset('voice', voice.id)"
        >
          <q-item-section avatar>
            <q-icon name="mic" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ voice.name }}</q-item-label>
            <q-item-label caption>{{ voice.language }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable @click="addVoice">
          <q-item-section avatar>
            <q-icon name="add" color="grey" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-grey">Add Voice</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-expansion-item>

    <q-expansion-item
      v-model="expandedSections.generated"
      icon="auto_awesome"
      label="Generated"
      :caption="`${library.generated.length} items`"
      header-class="text-primary"
    >
      <q-list dense>
        <q-item
          v-for="asset in library.generated"
          :key="asset.id"
          clickable
          @click="selectAsset('generated', asset.id)"
        >
          <q-item-section avatar>
            <q-icon :name="getAssetIcon(asset.asset_type)" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ asset.asset_type }}</q-item-label>
            <q-item-label caption>{{ formatDate(asset.created_at) }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-expansion-item>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore } from '../stores';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();

const library = computed(() => projectStore.library);

const expandedSections = ref({
  characters: true,
  props: false,
  voices: false,
  generated: false,
});

function selectAsset(type: string, id: string): void {
  switch (type) {
    case 'character':
      workspace.selectCharacter(id);
      workspace.setMode('characters');
      break;
    case 'prop':
      workspace.selectProduct(id);
      break;
    case 'voice':
      workspace.selectVoice(id);
      workspace.setMode('voices');
      break;
  }
}

function addCharacter(): void {
  const name = prompt('Character name:');
  if (!name) return;
  const code = prompt('Character code (short identifier):');
  if (!code) return;

  projectStore.addCharacter({ name, code, pose_images: {} });
}

function addProp(): void {
  workspace.setMode('characters');
}

function addVoice(): void {
  const name = prompt('Voice name:');
  if (!name) return;
  const code = prompt('Voice code:');
  if (!code) return;

  projectStore.addVoice({
    name,
    code,
    sample_path: '',
    language: 'en',
  });
}

function getAssetIcon(type: string): string {
  switch (type) {
    case 'image':
      return 'image';
    case 'video':
      return 'videocam';
    case 'audio':
      return 'audiotrack';
    default:
      return 'insert_drive_file';
  }
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleDateString();
}
</script>

<style scoped lang="scss">
.asset-library-panel {
  height: 100%;
  overflow-y: auto;
}
</style>
