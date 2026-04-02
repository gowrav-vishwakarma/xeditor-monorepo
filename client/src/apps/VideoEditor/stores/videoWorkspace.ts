import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { useVideoProjectStore } from './videoProject';

export type WorkspaceMode =
  | 'script'
  | 'characters'
  | 'voices'
  | 'audio'
  | 'music'
  | 'video'
  | 'export';

export const useVideoWorkspaceStore = defineStore('videoWorkspace', () => {
  const projectStore = useVideoProjectStore();

  const activeMode = ref<WorkspaceMode>('script');

  const selectedCharacterId = ref<string | null>(null);
  const selectedVoiceId = ref<string | null>(null);
  const selectedClipId = ref<string | null>(null);
  const selectedSceneId = ref<string | null>(null);
  const selectedMusicClipId = ref<string | null>(null);
  const selectedProductId = ref<string | null>(null);

  const showSettings = ref(false);
  const rightDrawerOpen = ref(true);
  const timelineCollapsed = ref(false);

  const selectedClip = computed(() => {
    if (!selectedClipId.value || !projectStore.project) return null;
    return (
      projectStore.project.timeline.clips.find(
        (c) => c.id === selectedClipId.value,
      ) ?? null
    );
  });

  const selectedScene = computed(() => {
    if (!selectedSceneId.value || !projectStore.project) return null;
    return (
      projectStore.project.story.scenes.find(
        (s) => s.id === selectedSceneId.value,
      ) ?? null
    );
  });

  const selectedCharacter = computed(() => {
    if (!selectedCharacterId.value || !projectStore.project) return null;
    return (
      projectStore.project.library.characters.find(
        (c) => c.id === selectedCharacterId.value,
      ) ?? null
    );
  });

  const selectedVoice = computed(() => {
    if (!selectedVoiceId.value || !projectStore.project) return null;
    return (
      projectStore.project.library.voices.find(
        (v) => v.id === selectedVoiceId.value,
      ) ?? null
    );
  });

  function setMode(mode: WorkspaceMode): void {
    activeMode.value = mode;
  }

  function selectClip(clipId: string | null): void {
    selectedClipId.value = clipId;
  }

  function selectScene(sceneId: string | null): void {
    selectedSceneId.value = sceneId;
  }

  function selectCharacter(charId: string | null): void {
    selectedCharacterId.value = charId;
  }

  function selectVoice(voiceId: string | null): void {
    selectedVoiceId.value = voiceId;
  }

  function selectProduct(productId: string | null): void {
    selectedProductId.value = productId;
  }

  function selectMusicClip(clipId: string | null): void {
    selectedMusicClipId.value = clipId;
  }

  function clearSelections(): void {
    selectedCharacterId.value = null;
    selectedVoiceId.value = null;
    selectedClipId.value = null;
    selectedSceneId.value = null;
    selectedMusicClipId.value = null;
    selectedProductId.value = null;
  }

  function toggleRightDrawer(): void {
    rightDrawerOpen.value = !rightDrawerOpen.value;
  }

  return {
    activeMode,
    selectedCharacterId,
    selectedVoiceId,
    selectedClipId,
    selectedSceneId,
    selectedMusicClipId,
    selectedProductId,
    showSettings,
    rightDrawerOpen,
    timelineCollapsed,

    selectedClip,
    selectedScene,
    selectedCharacter,
    selectedVoice,

    setMode,
    selectClip,
    selectScene,
    selectCharacter,
    selectVoice,
    selectProduct,
    selectMusicClip,
    clearSelections,
    toggleRightDrawer,
  };
});
