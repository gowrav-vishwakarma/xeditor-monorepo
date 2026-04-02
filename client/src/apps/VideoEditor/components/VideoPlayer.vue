<template>
  <div class="video-player-container">
    <div class="player-viewport" :style="viewportStyle">
      <video
        v-if="currentVideoUrl"
        ref="videoEl"
        class="player-video"
        :src="currentVideoUrl"
        @timeupdate="onTimeUpdate"
        @ended="onEnded"
        @loadedmetadata="onLoaded"
      />

      <div v-else class="player-placeholder">
        <q-icon name="movie" size="64px" color="grey-7" />
        <div class="text-grey-7 q-mt-md text-body1">Select a clip to preview</div>
        <div class="text-grey-8 text-caption q-mt-sm">
          Generate videos from the timeline to see previews here
        </div>
      </div>
    </div>

    <!-- Transport controls -->
    <div class="player-controls">
      <q-btn flat dense round icon="skip_previous" color="primary" size="sm" @click="seekToStart" />
      <q-btn flat dense round icon="fast_rewind" color="primary" size="sm" @click="seekBackward" />
      <q-btn
        flat
        dense
        round
        :icon="isPlaying ? 'pause' : 'play_arrow'"
        color="primary"
        size="md"
        @click="togglePlay"
      />
      <q-btn flat dense round icon="fast_forward" color="primary" size="sm" @click="seekForward" />
      <q-btn flat dense round icon="skip_next" color="primary" size="sm" @click="seekToEnd" />

      <q-separator vertical class="q-mx-sm" />

      <span class="text-dark text-caption time-display">
        {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
      </span>

      <q-space />

      <q-btn
        flat
        dense
        round
        icon="fullscreen"
        color="primary"
        size="sm"
        @click="toggleFullscreen"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { useVideoProjectStore, useVideoWorkspaceStore } from '../stores';
import { useVideoCompanionStore } from '../stores/videoCompanion';

const projectStore = useVideoProjectStore();
const companion = useVideoCompanionStore();
const workspace = useVideoWorkspaceStore();

const videoEl = ref<HTMLVideoElement | null>(null);
const isPlaying = ref(false);
const currentTime = ref(0);
const duration = ref(0);

const viewportStyle = computed(() => {
  if (!projectStore.project) return {};
  const canvas = projectStore.project.settings.canvas;
  const aspect = canvas.width / canvas.height;
  return {
    aspectRatio: `${aspect}`,
  };
});

const currentVideoUrl = computed(() => {
  if (!projectStore.project || !workspace.selectedClipId) return null;

  const clip = projectStore.project.timeline.clips.find(
    (c) => c.id === workspace.selectedClipId,
  );
  if (!clip?.video_artifact_path) return null;

  return companion.getAssetUrl(projectStore.project.id, clip.video_artifact_path);
});

watch(
  () => projectStore.project?.timeline.clips,
  () => {
    if (workspace.selectedClipId && projectStore.project) {
      const exists = projectStore.project.timeline.clips.some(
        (c) => c.id === workspace.selectedClipId,
      );
      if (!exists) workspace.selectClip(null);
    }
  },
);

function togglePlay(): void {
  if (!videoEl.value) return;
  if (isPlaying.value) {
    videoEl.value.pause();
  } else {
    void videoEl.value.play();
  }
  isPlaying.value = !isPlaying.value;
}

function seekToStart(): void {
  if (videoEl.value) videoEl.value.currentTime = 0;
}

function seekToEnd(): void {
  if (videoEl.value) videoEl.value.currentTime = videoEl.value.duration;
}

function seekForward(): void {
  if (videoEl.value)
    videoEl.value.currentTime = Math.min(videoEl.value.duration, videoEl.value.currentTime + 5);
}

function seekBackward(): void {
  if (videoEl.value) videoEl.value.currentTime = Math.max(0, videoEl.value.currentTime - 5);
}

function onTimeUpdate(): void {
  if (videoEl.value) currentTime.value = videoEl.value.currentTime;
}

function onLoaded(): void {
  if (videoEl.value) duration.value = videoEl.value.duration;
}

function onEnded(): void {
  isPlaying.value = false;
}

function toggleFullscreen(): void {
  const container = videoEl.value?.parentElement;
  if (!container) return;
  if (document.fullscreenElement) {
    void document.exitFullscreen();
  } else {
    void container.requestFullscreen();
  }
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

onBeforeUnmount(() => {
  if (videoEl.value) {
    videoEl.value.pause();
  }
});
</script>

<style scoped lang="scss">
.video-player-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.player-viewport {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  max-height: calc(100% - 40px);
  overflow: hidden;
}

.player-video {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.player-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  opacity: 0.6;
}

.player-controls {
  height: 40px;
  display: flex;
  align-items: center;
  padding: 0 8px;
  background: #ffffff;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.time-display {
  font-family: 'Roboto Mono', monospace;
  font-size: 12px;
}
</style>
