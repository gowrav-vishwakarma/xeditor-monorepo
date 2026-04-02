<template>
  <q-layout view="hHh lpR fFf">
    <!-- Header Toolbar -->
    <q-header v-if="projectStore.isOpen" elevated class="bg-primary">
      <q-toolbar class="ve-toolbar">
        <q-btn flat dense round icon="home" text-color="white" @click="$router.push('/')">
          <q-tooltip>Home</q-tooltip>
        </q-btn>
        <q-separator vertical class="q-mx-xs" />

        <q-toolbar-title class="text-subtitle1 ellipsis" style="max-width: 200px">
          {{ projectStore.projectName }}
        </q-toolbar-title>

        <q-separator vertical class="q-mx-xs" />

        <!-- Workspace mode buttons -->
        <q-btn-group flat class="q-mx-sm">
          <q-btn
            v-for="mode in workspaceModes"
            :key="mode.value"
            flat
            dense
            :icon="mode.icon"
            :text-color="workspace.activeMode === mode.value ? 'amber' : 'white'"
            @click="workspace.setMode(mode.value)"
          >
            <q-tooltip>{{ mode.label }}</q-tooltip>
          </q-btn>
        </q-btn-group>

        <q-space />

        <!-- Save status -->
        <q-spinner-dots v-if="projectStore.isSaving" color="white" size="20px" class="q-mr-sm" />
        <q-icon
          v-else-if="projectStore.lastSaveError"
          name="error"
          color="negative"
          size="20px"
          class="q-mr-sm"
        >
          <q-tooltip>Save error: {{ projectStore.lastSaveError }}</q-tooltip>
        </q-icon>
        <q-icon
          v-else-if="!projectStore.isDirty"
          name="cloud_done"
          color="positive"
          size="20px"
          class="q-mr-sm"
        >
          <q-tooltip>All changes saved</q-tooltip>
        </q-icon>

        <q-btn
          v-if="projectStore.isDirty"
          flat
          dense
          icon="save"
          text-color="warning"
          :loading="projectStore.isSaving"
          @click="saveProject"
        >
          <q-tooltip>Save Now</q-tooltip>
        </q-btn>

        <q-separator vertical class="q-mx-xs" />

        <q-btn
          flat
          dense
          round
          icon="view_sidebar"
          text-color="white"
          @click="workspace.toggleRightDrawer()"
        >
          <q-tooltip>Toggle Properties Panel</q-tooltip>
        </q-btn>
        <q-btn
          flat
          dense
          round
          icon="settings"
          text-color="white"
          @click="workspace.showSettings = true"
        >
          <q-tooltip>Project Settings</q-tooltip>
        </q-btn>
      </q-toolbar>
    </q-header>

    <!-- Right Drawer (Properties) -->
    <q-drawer
      v-if="projectStore.isOpen"
      v-model="workspace.rightDrawerOpen"
      side="right"
      :width="360"
      bordered
      class="bg-grey-1"
    >
      <PropertiesPanel />
    </q-drawer>

    <!-- Main Content -->
    <q-page-container>
      <router-view />
    </q-page-container>

    <!-- Footer (Job Status Bar) -->
    <q-footer v-if="projectStore.isOpen" elevated class="bg-grey-3 text-dark ve-footer">
      <GenerationQueuePanel />
    </q-footer>

    <!-- Settings Dialog -->
    <q-dialog v-model="workspace.showSettings" maximized>
      <SettingsDialog @close="workspace.showSettings = false" />
    </q-dialog>
  </q-layout>
</template>

<script setup lang="ts">
import { watch, onMounted, onUnmounted } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';
import type { WorkspaceMode } from '../stores/videoWorkspace';
import PropertiesPanel from '../components/PropertiesPanel.vue';
import GenerationQueuePanel from '../components/GenerationQueuePanel.vue';
import SettingsDialog from '../components/SettingsDialog.vue';

const projectStore = useVideoProjectStore();
const companionStore = useVideoCompanionStore();
const workspace = useVideoWorkspaceStore();

interface ModeConfig {
  value: WorkspaceMode;
  label: string;
  icon: string;
}

const workspaceModes: ModeConfig[] = [
  { value: 'script', label: 'Script / Story', icon: 'auto_fix_high' },
  { value: 'characters', label: 'Characters', icon: 'face' },
  { value: 'voices', label: 'Voices', icon: 'record_voice_over' },
  { value: 'audio', label: 'Dialog Audio', icon: 'mic' },
  { value: 'music', label: 'Music & SFX', icon: 'music_note' },
  { value: 'video', label: 'Video', icon: 'movie' },
  { value: 'export', label: 'Export', icon: 'file_download' },
];

async function saveProject(): Promise<void> {
  try {
    await projectStore.saveProject();
  } catch (e) {
    console.error('Failed to save project:', e);
  }
}

function onBeforeUnload(e: BeforeUnloadEvent): void {
  if (projectStore.isDirty) {
    e.preventDefault();
    void projectStore.saveProject();
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload);
});

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload);
});

let recentProjectsLoaded = false;
let isLoadingRecentProjects = false;

async function loadRecentProjectsWhenReady(): Promise<void> {
  if (recentProjectsLoaded || isLoadingRecentProjects) return;
  isLoadingRecentProjects = true;

  try {
    if (!companionStore.isConnected) {
      let attempts = 0;
      while (!companionStore.isConnected && attempts < 20) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        attempts++;
      }
    }

    if (companionStore.isConnected) {
      await projectStore.loadRecentProjects();
      recentProjectsLoaded = true;

      if (!projectStore.isOpen) {
        await projectStore.restoreLastProject();
      }
    }
  } catch (e) {
    console.error('Failed to load recent projects:', e);
  } finally {
    isLoadingRecentProjects = false;
  }
}

watch(
  () => companionStore.isConnected,
  (isConnected) => {
    if (isConnected) {
      void loadRecentProjectsWhenReady();
    }
  },
  { immediate: true },
);
</script>

<style scoped lang="scss">
.ve-toolbar {
  min-height: 40px;
  padding: 0 4px;
}

.ve-footer {
  height: 80px;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}
</style>
