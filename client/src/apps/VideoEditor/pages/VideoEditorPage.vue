<template>
  <q-page class="video-editor-page">
    <!-- No project open - show wizard -->
    <div v-if="!projectStore.isOpen" class="flex flex-center full-height">
      <ProjectWizard @created="onProjectReady" @opened="onProjectReady" @cancel="goHome" />
    </div>

    <!-- Project open - workspace -->
    <div v-else class="workspace-container">
      <!-- Upper area: workspace panel + player side by side -->
      <div class="upper-area">
        <!-- Workspace Panel (context-sensitive) -->
        <div class="workspace-panel">
          <component :is="activeWorkspaceComponent" />
        </div>

        <!-- Video Player (right side) -->
        <div class="player-area">
          <VideoPlayer />
        </div>
      </div>

      <!-- Timeline collapse toggle -->
      <div
        class="timeline-toggle bg-grey-2 cursor-pointer"
        @click="workspace.timelineCollapsed = !workspace.timelineCollapsed"
      >
        <q-icon
          :name="workspace.timelineCollapsed ? 'expand_less' : 'expand_more'"
          size="16px"
        />
        <span class="text-caption q-ml-xs">Timeline</span>
      </div>

      <!-- Bottom: Multi-track Timeline -->
      <div v-show="!workspace.timelineCollapsed" class="timeline-area">
        <TimelineEditor />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue';
import { useRouter } from 'vue-router';
import { useVideoProjectStore, useVideoWorkspaceStore } from '../stores';
import ProjectWizard from '../components/ProjectWizard.vue';
import VideoPlayer from '../components/VideoPlayer.vue';
import TimelineEditor from '../components/TimelineEditor.vue';
import StoryDesigner from '../components/StoryDesigner.vue';
import CharacterDesigner from '../components/CharacterDesigner.vue';
import VoiceManager from '../components/VoiceManager.vue';
import MusicSfxManager from '../components/MusicSfxManager.vue';
import ExportPanel from '../components/ExportPanel.vue';

const router = useRouter();
const projectStore = useVideoProjectStore();
const workspace = useVideoWorkspaceStore();

const workspaceComponents: Record<string, Component> = {
  script: StoryDesigner,
  characters: CharacterDesigner,
  voices: VoiceManager,
  audio: StoryDesigner,
  music: MusicSfxManager,
  video: VideoPlayer,
  export: ExportPanel,
};

const activeWorkspaceComponent = computed<Component>(() => {
  return workspaceComponents[workspace.activeMode] ?? StoryDesigner;
});

function onProjectReady(): void {
  // Project opened, workspace shows automatically
}

function goHome(): void {
  void router.push('/');
}
</script>

<style scoped lang="scss">
.video-editor-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.full-height {
  min-height: calc(100vh - 120px);
}

.workspace-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
  background: #f5f5f5;
}

.upper-area {
  flex: 1;
  display: flex;
  min-height: 200px;
  overflow: hidden;
}

.workspace-panel {
  flex: 1;
  overflow-y: auto;
  border-right: 1px solid rgba(0, 0, 0, 0.1);
  background: #ffffff;
}

.player-area {
  width: 40%;
  min-width: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e0e0e0;
  overflow: hidden;
}

.timeline-toggle {
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  user-select: none;
}

.timeline-area {
  height: 280px;
  min-height: 200px;
  background: #ffffff;
  overflow: hidden;
}
</style>
