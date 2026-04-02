<template>
  <div class="timeline-editor">
    <div class="row items-center q-px-sm q-py-xs">
      <div class="text-subtitle1">Timeline</div>
      <q-space />
      <q-btn-toggle
        v-model="viewMode"
        :options="[
          { label: 'Script', value: 'script' },
          { label: 'Video', value: 'video' },
        ]"
        dense
        no-caps
        size="sm"
        color="primary"
        toggle-color="primary"
      />
      <q-btn flat dense icon="zoom_out" size="sm" class="q-ml-sm" @click="zoomOut" />
      <q-btn flat dense icon="zoom_in" size="sm" @click="zoomIn" />
    </div>

    <!-- Timeline Header -->
    <div class="timeline-header bg-grey-3 q-pa-xs">
      <div class="row items-center">
        <div class="track-label">Tracks</div>
        <div class="timeline-ruler">
          <div
            v-for="marker in timeMarkers"
            :key="marker.time"
            class="time-marker"
            :style="{ left: `${marker.position}%` }"
          >
            {{ formatTime(marker.time) }}
          </div>
        </div>
      </div>
    </div>

    <!-- Timeline Tracks -->
    <div class="timeline-tracks">
      <div v-for="track in timeline.tracks" :key="track.id" class="timeline-track" :style="{ minHeight: `${track.height}px` }">
        <div class="track-header bg-grey-2">
          <q-icon :name="trackIcon(track.type)" size="16px" class="q-mr-xs" />
          <span class="text-caption">{{ track.name }}</span>
          <q-space />
          <q-btn
            flat
            round
            size="xs"
            :icon="track.muted ? 'volume_off' : 'volume_up'"
            @click="toggleMute(track)"
          />
          <q-btn
            flat
            round
            size="xs"
            :icon="track.locked ? 'lock' : 'lock_open'"
            @click="toggleLock(track)"
          />
        </div>
        <div class="track-content" @click="handleTrackClick($event, track)">
          <div
            v-for="clip in getTrackClips(track.id)"
            :key="clip.id"
            class="timeline-clip"
            :class="[
              `status-${clip.status}`,
              `track-${track.type}`,
              { selected: selectedClipId === clip.id },
            ]"
            :style="getClipStyle(clip)"
            @click.stop="selectClip(clip.id)"
          >
            <div class="clip-content">
              <q-icon v-if="clip.status === 'generating'" name="sync" class="rotating" size="12px" />
              <q-icon v-else-if="clip.status === 'done'" name="check" color="positive" size="12px" />
              <q-icon v-else-if="clip.status === 'error'" name="error" color="negative" size="12px" />
              <span class="clip-label">
                <template v-if="viewMode === 'script' && clip.script_line_ids.length > 0">
                  {{ getScriptTextForClip(clip) }}
                </template>
                <template v-else>
                  {{ getClipLabel(clip) }}
                </template>
              </span>
            </div>
            <div v-if="isClipStale(clip)" class="stale-indicator">
              <q-icon name="warning" color="warning" size="xs" />
            </div>
            <!-- Volume indicator for audio clips -->
            <div v-if="clip.volume !== undefined && clip.volume < 1" class="volume-indicator">
              <q-icon name="volume_down" size="10px" />
              {{ Math.round((clip.volume ?? 1) * 100) }}%
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Timeline Controls -->
    <div class="timeline-controls bg-grey-2 q-pa-xs">
      <div class="row items-center">
        <q-btn flat round size="sm" icon="skip_previous" />
        <q-btn flat round size="sm" icon="play_arrow" />
        <q-btn flat round size="sm" icon="skip_next" />
        <q-separator vertical class="q-mx-xs" />
        <span class="text-caption">{{ formatTime(currentTime) }} / {{ formatTime(timeline.total_duration) }}</span>
        <q-space />
        <q-btn
          flat
          dense
          size="sm"
          icon="delete_sweep"
          label="Clear"
          color="negative"
          :disable="timeline.clips.length === 0"
          @click="clearAllClips"
        />
        <q-btn flat dense size="sm" icon="add" label="Add from Scenes" @click="addClipFromScene" />
        <q-btn-dropdown flat dense size="sm" icon="auto_awesome" label="Generate" color="primary">
          <q-list dense>
            <q-item clickable v-close-popup @click="generateAllAudio">
              <q-item-section avatar><q-icon name="record_voice_over" /></q-item-section>
              <q-item-section>
                <q-item-label>Generate Audio (TTS)</q-item-label>
                <q-item-label caption>Create speech from dialog</q-item-label>
              </q-item-section>
            </q-item>
            <q-item clickable v-close-popup @click="generateImages">
              <q-item-section avatar><q-icon name="image" /></q-item-section>
              <q-item-section>
                <q-item-label>Generate Images</q-item-label>
                <q-item-label caption>Create keyframes from prompts</q-item-label>
              </q-item-section>
            </q-item>
            <q-item clickable v-close-popup @click="generateVideos">
              <q-item-section avatar><q-icon name="movie" /></q-item-section>
              <q-item-section>
                <q-item-label>Generate Videos</q-item-label>
                <q-item-label caption>Create video clips</q-item-label>
              </q-item-section>
            </q-item>
            <q-separator />
            <q-item clickable v-close-popup @click="exportVideo">
              <q-item-section avatar><q-icon name="file_download" /></q-item-section>
              <q-item-section>
                <q-item-label>Export Final Video</q-item-label>
                <q-item-label caption>Merge all clips to MP4</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useVideoProjectStore, useVideoJobsStore, useVideoWorkspaceStore } from '../stores';
import type { TimelineClip, TimelineTrack, TrackType } from '../types';
import { isClipAudioStale, isClipVideoStale } from '../types';

const projectStore = useVideoProjectStore();
const jobsStore = useVideoJobsStore();
const workspace = useVideoWorkspaceStore();

const timeline = computed(() => projectStore.timeline);
const story = computed(() => projectStore.story);

const viewMode = ref<'script' | 'video'>('script');
const zoom = ref(1);
const currentTime = ref(0);

const selectedClipId = computed({
  get: () => workspace.selectedClipId,
  set: (val: string | null) => workspace.selectClip(val),
});

function trackIcon(type: TrackType): string {
  switch (type) {
    case 'video': return 'videocam';
    case 'audio': return 'record_voice_over';
    case 'music': return 'music_note';
    case 'sfx': return 'surround_sound';
    case 'overlay': return 'layers';
    default: return 'audiotrack';
  }
}

const timeMarkers = computed(() => {
  const duration = timeline.value.total_duration || 60;
  const markers = [];
  const step = duration > 300 ? 60 : duration > 60 ? 10 : 5;
  for (let t = 0; t <= duration; t += step) {
    markers.push({ time: t, position: (t / duration) * 100 });
  }
  return markers;
});

function getTrackClips(trackId: string): TimelineClip[] {
  return timeline.value.clips.filter((c) => c.track_id === trackId);
}

function getClipStyle(clip: TimelineClip): Record<string, string> {
  const duration = timeline.value.total_duration || 60;
  const left = (clip.start_time / duration) * 100;
  const width = (clip.duration / duration) * 100;
  return {
    left: `${left}%`,
    width: `${Math.max(width, 2)}%`,
  };
}

function getClipLabel(clip: TimelineClip): string {
  if (clip.scene_id) {
    const scene = story.value.scenes.find((s) => s.id === clip.scene_id);
    return scene?.title || 'Scene';
  }
  return 'Clip';
}

function getScriptTextForClip(clip: TimelineClip): string {
  if (!clip.script_line_ids.length || !clip.scene_id) return getClipLabel(clip);

  const scene = story.value.scenes.find((s) => s.id === clip.scene_id);
  if (!scene) return getClipLabel(clip);

  const lines = scene.script_lines
    .filter((l) => clip.script_line_ids.includes(l.id))
    .map((l) => l.text)
    .join(' ');

  return lines || getClipLabel(clip);
}

function isClipStale(clip: TimelineClip): boolean {
  return isClipAudioStale(clip) || isClipVideoStale(clip);
}

function selectClip(clipId: string): void {
  selectedClipId.value = clipId;
}

function handleTrackClick(_event: MouseEvent, track: TimelineTrack): void {
  if (track.locked) return;
}

function toggleMute(track: TimelineTrack): void {
  track.muted = !track.muted;
}

function toggleLock(track: TimelineTrack): void {
  track.locked = !track.locked;
}

function zoomIn(): void {
  zoom.value = Math.min(zoom.value * 1.2, 4);
}

function zoomOut(): void {
  zoom.value = Math.max(zoom.value / 1.2, 0.25);
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function clearAllClips(): void {
  if (timeline.value.clips.length === 0) return;
  if (!confirm('Clear all clips from the timeline? This cannot be undone.')) return;
  projectStore.clearAllClips();
  selectedClipId.value = null;
}

function addClipFromScene(): void {
  const scenes = story.value.scenes;
  if (scenes.length === 0) {
    alert('No scenes available. Create scenes in the Story Designer first.');
    return;
  }

  let startTime = timeline.value.total_duration;
  for (const scene of scenes) {
    const duration = scene.duration_estimate || 5;

    // Video clip
    projectStore.addClip({
      track_id: 'video_main',
      start_time: startTime,
      duration,
      source_type: 'placeholder',
      scene_id: scene.id,
      status: 'draft',
      script_line_ids: [],
    });

    // Audio clip for dialog
    if (scene.script_lines.length > 0) {
      projectStore.addClip({
        track_id: 'audio_dialog',
        start_time: startTime,
        duration,
        source_type: 'generated_audio',
        scene_id: scene.id,
        status: 'draft',
        script_line_ids: scene.script_lines.map((l) => l.id),
        volume: 1.0,
        fade_in_seconds: 0,
        fade_out_seconds: 0,
      });
    }

    startTime += duration;
  }
}

async function generateAllAudio(): Promise<void> {
  const dialogClips = timeline.value.clips.filter((c) => c.track_id === 'audio_dialog');
  if (dialogClips.length === 0) {
    alert('No dialog clips on timeline. Add clips from scenes first.');
    return;
  }
  try {
    await jobsStore.generateAudio({ clipIds: dialogClips.map((c) => c.id) });
  } catch (e) {
    console.error('Failed to start audio generation:', e);
  }
}

async function generateImages(): Promise<void> {
  const clipIds = timeline.value.clips
    .filter((c) => c.track_id === 'video_main')
    .map((c) => c.id);
  if (clipIds.length === 0) {
    alert('No video clips on timeline');
    return;
  }
  try {
    await jobsStore.generateImages({ clipIds });
  } catch (e) {
    console.error('Failed to start image generation:', e);
  }
}

async function generateVideos(): Promise<void> {
  const clipIds = timeline.value.clips
    .filter((c) => c.track_id === 'video_main')
    .map((c) => c.id);
  if (clipIds.length === 0) {
    alert('No video clips on timeline');
    return;
  }
  try {
    await jobsStore.generateVideo({ clipIds });
  } catch (e) {
    console.error('Failed to start video generation:', e);
  }
}

async function exportVideo(): Promise<void> {
  try {
    await jobsStore.exportProject();
  } catch (e) {
    console.error('Failed to start export:', e);
  }
}
</script>

<style scoped lang="scss">
.timeline-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.timeline-header {
  flex-shrink: 0;
  border-bottom: 1px solid var(--q-grey-4);
}

.track-label {
  width: 120px;
  flex-shrink: 0;
}

.timeline-ruler {
  flex: 1;
  position: relative;
  height: 20px;
}

.time-marker {
  position: absolute;
  font-size: 10px;
  color: var(--q-grey-7);
  transform: translateX(-50%);
}

.timeline-tracks {
  flex: 1;
  overflow-y: auto;
  background: #ffffff;
}

.timeline-track {
  display: flex;
  border-bottom: 1px solid var(--q-grey-3);
}

.track-header {
  width: 120px;
  flex-shrink: 0;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  border-right: 1px solid var(--q-grey-3);
  font-size: 12px;
}

.track-content {
  flex: 1;
  position: relative;
  background: #f8f9fa;
}

.timeline-clip {
  position: absolute;
  top: 3px;
  bottom: 3px;
  background: var(--q-primary);
  border-radius: 3px;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.1s, box-shadow 0.1s;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }

  &.selected {
    box-shadow: 0 0 0 2px var(--q-primary);
  }

  &.status-draft { background: #e0e0e0; color: #333; .clip-content { color: #333; } }
  &.status-generating { background: var(--q-info); color: white; }
  &.status-done { background: var(--q-positive); color: white; }
  &.status-error { background: var(--q-negative); color: white; }

  &.track-audio { background: #7c4dff; &.status-draft { background: #d1c4e9; } &.status-done { background: #7c4dff; } }
  &.track-music { background: #e91e63; &.status-draft { background: #f8bbd0; } &.status-done { background: #e91e63; } }
  &.track-sfx { background: #009688; &.status-draft { background: #b2dfdb; } &.status-done { background: #009688; } }
}

.clip-content {
  padding: 2px 6px;
  color: inherit;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
}

.clip-label {
  margin-left: 3px;
}

.stale-indicator {
  position: absolute;
  top: 1px;
  right: 1px;
}

.volume-indicator {
  position: absolute;
  bottom: 1px;
  right: 3px;
  font-size: 9px;
  opacity: 0.8;
  display: flex;
  align-items: center;
  gap: 2px;
}

.timeline-controls {
  flex-shrink: 0;
  border-top: 1px solid var(--q-grey-4);
}

.rotating {
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
