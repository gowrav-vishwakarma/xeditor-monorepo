<template>
  <div class="bg-props-manager q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Backgrounds & Props</div>
      <q-space />
      <q-btn outline icon="upload" label="Upload" @click="uploadAsset" />
      <q-btn color="primary" icon="auto_awesome" label="Generate" class="q-ml-sm" @click="showGenerate = true" />
    </div>
    <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFileSelected" />

    <q-tabs v-model="activeTab" dense align="left" class="q-mb-md">
      <q-tab name="backgrounds" label="Backgrounds" icon="landscape" />
      <q-tab name="props" label="Props" icon="category" />
      <q-tab name="objects" label="Objects" icon="view_in_ar" />
    </q-tabs>

    <div v-if="filteredProducts.length === 0" class="text-center q-pa-xl text-grey">
      <q-icon :name="activeTab === 'backgrounds' ? 'landscape' : 'category'" size="64px" class="q-mb-md" />
      <div class="text-h6">No {{ activeTab }} yet</div>
      <div class="q-mb-md">Upload images or generate with AI</div>
    </div>

    <div class="row q-gutter-md">
      <q-card
        v-for="product in filteredProducts"
        :key="product.id"
        flat
        bordered
        class="product-card cursor-pointer"
        :class="{ 'ring-primary': workspace.selectedProductId === product.id }"
        @click="workspace.selectProduct(product.id)"
      >
        <q-img
          v-if="product.image_path"
          :src="getAssetUrl(product.image_path)"
          :ratio="16 / 9"
          class="product-thumb"
        />
        <div v-else class="product-placeholder flex flex-center">
          <q-icon name="image" size="32px" color="grey" />
        </div>
        <q-card-section class="q-pa-sm">
          <div class="text-body2 ellipsis">{{ product.name }}</div>
          <div class="text-caption text-grey">{{ product.category || 'Uncategorized' }}</div>
        </q-card-section>
        <q-card-actions>
          <q-btn flat size="sm" icon="delete" color="negative" @click.stop="removeProduct(product.id)" />
        </q-card-actions>
      </q-card>
    </div>

    <!-- Generate Dialog -->
    <q-dialog v-model="showGenerate">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">Generate {{ activeTab.slice(0, -1) }}</div>
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="generatePrompt"
            label="Description"
            outlined
            type="textarea"
            rows="3"
            :placeholder="activeTab === 'backgrounds' ? 'A serene mountain lake at sunset...' : 'A vintage red sports car...'"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Cancel" v-close-popup />
          <q-btn color="primary" label="Generate" @click="generateAsset" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore, useVideoJobsStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';

const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();
const jobsStore = useVideoJobsStore();
const companion = useVideoCompanionStore();

const fileInput = ref<HTMLInputElement | null>(null);
const activeTab = ref('backgrounds');
const showGenerate = ref(false);
const generatePrompt = ref('');

const categoryMap: Record<string, string> = {
  backgrounds: 'background',
  props: 'prop',
  objects: 'object',
};

const filteredProducts = computed(() => {
  const category = categoryMap[activeTab.value];
  return projectStore.library.products.filter(
    (p) => p.category === category || (!p.category && activeTab.value === 'props'),
  );
});

function getAssetUrl(path: string): string {
  if (!projectStore.project) return '';
  return companion.getAssetUrl(projectStore.project.id, path);
}

function uploadAsset(): void {
  fileInput.value?.click();
}

async function onFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !projectStore.project) return;

  const name = prompt('Name:', file.name.replace(/\.[^.]+$/, ''));
  if (!name) return;
  const code = name.toLowerCase().replace(/\s+/g, '_').slice(0, 16);

  try {
    const result = await companion.uploadAsset(
      projectStore.project.id,
      file,
      { assetType: 'product', subfolder: 'props' },
    );
    if (result?.path) {
      const cat = categoryMap[activeTab.value];
      projectStore.addProduct({
        name,
        code,
        ...(cat ? { category: cat } : {}),
        image_path: result.path,
      });
    }
  } catch (e) {
    console.error('Failed to upload asset:', e);
  }
  input.value = '';
}

async function generateAsset(): Promise<void> {
  if (!generatePrompt.value || !projectStore.project) return;
  try {
    await jobsStore.generateImages({
      clipIds: [],
      generatorConfig: {
        prompt: generatePrompt.value,
        target_category: categoryMap[activeTab.value],
      },
    });
  } catch (e) {
    console.error('Failed to generate asset:', e);
  }
  generatePrompt.value = '';
}

function removeProduct(id: string): void {
  if (!confirm('Remove this item?')) return;
  projectStore.removeProduct(id);
}
</script>

<style scoped lang="scss">
.bg-props-manager {
  max-width: 1200px;
  margin: 0 auto;
}

.product-card {
  width: 200px;

  &.ring-primary {
    outline: 2px solid var(--q-primary);
  }
}

.product-thumb {
  height: 120px;
}

.product-placeholder {
  height: 120px;
  background: #f0f0f0;
}

.hidden {
  display: none;
}
</style>
