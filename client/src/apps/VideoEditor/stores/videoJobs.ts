/**
 * Video Jobs Store
 *
 * Manages generation jobs and their progress.
 * Communicates via the stream WebSocket for real-time updates.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { useVideoCompanionStore } from './videoCompanion';
import { useVideoProjectStore } from './videoProject';
import type {
  Job,
  JobType,
  JobStatus,
  JobProgressEvent,
  GeneratorCapabilities,
  RegenerationMode,
} from '../types';

export const useVideoJobsStore = defineStore('videoJobs', () => {
  const companion = useVideoCompanionStore();
  const projectStore = useVideoProjectStore();

  // ─────────────────────────────────────────────────────────────────────
  // State
  // ─────────────────────────────────────────────────────────────────────

  const jobs = ref<Map<string, Job>>(new Map());
  const activeJobId = ref<string | null>(null);
  const generators = ref<GeneratorCapabilities[]>([]);
  const isLoadingGenerators = ref(false);

  // Progress tracking
  const jobProgress = ref<Map<string, JobProgressEvent>>(new Map());

  // ─────────────────────────────────────────────────────────────────────
  // Computed
  // ─────────────────────────────────────────────────────────────────────

  const jobList = computed(() => Array.from(jobs.value.values()));

  const pendingJobs = computed(() =>
    jobList.value.filter((j) => j.status === 'pending' || j.status === 'queued'),
  );

  const runningJobs = computed(() => jobList.value.filter((j) => j.status === 'running'));

  const completedJobs = computed(() => jobList.value.filter((j) => j.status === 'completed'));

  const failedJobs = computed(() => jobList.value.filter((j) => j.status === 'failed'));

  const hasActiveJob = computed(() => activeJobId.value !== null);

  const activeJob = computed(() => (activeJobId.value ? jobs.value.get(activeJobId.value) : null));

  const activeJobProgress = computed(() =>
    activeJobId.value ? jobProgress.value.get(activeJobId.value) : null,
  );

  // Generator helpers
  const llmGenerators = computed(() => generators.value.filter((g) => g.generator_type === 'llm'));

  const ttsGenerators = computed(() => generators.value.filter((g) => g.generator_type === 'tts'));

  const imageGenerators = computed(() =>
    generators.value.filter((g) => g.generator_type === 't2i'),
  );

  const videoGenerators = computed(() =>
    generators.value.filter((g) => g.generator_type === 'i2v' || g.generator_type === 't2v'),
  );

  const musicGenerators = computed(() =>
    generators.value.filter((g) => g.generator_type === 'music'),
  );

  const avGenerators = computed(() => generators.value.filter((g) => g.generator_type === 'av'));

  const lipsyncGenerators = computed(() =>
    generators.value.filter((g) => g.generator_type === 'lipsync'),
  );

  const sfxGenerators = computed(() => generators.value.filter((g) => g.generator_type === 'sfx'));

  // ─────────────────────────────────────────────────────────────────────
  // WebSocket Communication
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Send a control message (for queries)
   */
  async function sendControlMessage<T>(type: string, payload: Record<string, unknown>): Promise<T> {
    const response = await companion.request(type, payload);
    if (response && typeof response === 'object' && 'error' in response) {
      throw new Error((response as { error: string }).error);
    }
    return response as T;
  }

  /**
   * Send a stream message (for job operations)
   */
  async function sendStreamMessage<T>(type: string, payload: Record<string, unknown>): Promise<T> {
    const response = await companion.streamRequest(type, payload);
    if (response && typeof response === 'object' && 'error' in response) {
      throw new Error((response as { error: string }).error);
    }
    return response as T;
  }

  // Register job progress handler (unsubscribe function kept for potential cleanup)
  const _unsubscribeProgress = companion.onJobProgress((data) => {
    if (data.event) {
      handleJobProgress(data.event as unknown as JobProgressEvent);
    }
  });

  /**
   * Handle incoming job progress events
   */
  function handleJobProgress(event: JobProgressEvent): void {
    jobProgress.value.set(event.job_id, event);

    // Update job in map
    const job = jobs.value.get(event.job_id);
    if (job) {
      job.last_seq = event.seq;
      job.last_progress = event.overall_progress;

      // Update status based on stage
      if (event.stage === 'completed') {
        job.status = 'completed';
        job.completed_at = Date.now() / 1000;
        if (activeJobId.value === event.job_id) {
          activeJobId.value = null;
        }
        // Refresh project to get updated artifacts
        void refreshProjectAfterJob();
      } else if (event.stage === 'error') {
        job.status = 'failed';
        if (event.message) {
          job.error_message = event.message;
        }
        job.completed_at = Date.now() / 1000;
        if (activeJobId.value === event.job_id) {
          activeJobId.value = null;
        }
      } else if (event.stage === 'cancelled') {
        job.status = 'cancelled';
        if (activeJobId.value === event.job_id) {
          activeJobId.value = null;
        }
      } else if (job.status !== 'running') {
        job.status = 'running';
        job.started_at = job.started_at || Date.now() / 1000;
      }
    }
  }

  /**
   * Refresh project state after a job completes to pick up generated artifacts.
   */
  async function refreshProjectAfterJob(): Promise<void> {
    const projectId = projectStore.projectId;
    if (!projectId) return;

    try {
      const response = await sendControlMessage<{
        success: boolean;
        project?: unknown;
      }>('ve_get_project', { projectId });

      if (response.success && response.project) {
        // Update project store with server state (without triggering autosave)
        projectStore.project = response.project as typeof projectStore.project;
      }
    } catch (e) {
      console.error('Failed to refresh project after job:', e);
    }
  }

  // ─────────────────────────────────────────────────────────────────────
  // Job Operations
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Start a new generation job
   */
  async function startJob(
    jobType: JobType,
    options: {
      clipIds?: string[];
      sceneIds?: string[];
      generatorId?: string;
      generatorConfig?: Record<string, unknown>;
      regenerationMode?: RegenerationMode;
    } = {},
  ): Promise<string> {
    const projectId = projectStore.projectId;
    if (!projectId) {
      throw new Error('No project open');
    }

    const response = await sendStreamMessage<{
      success: boolean;
      jobId?: string;
      status?: JobStatus;
      error?: string;
    }>('ve_job_start', {
      projectId,
      jobType,
      clipIds: options.clipIds || [],
      sceneIds: options.sceneIds || [],
      generatorId: options.generatorId,
      generatorConfig: options.generatorConfig,
      regenerationMode: options.regenerationMode,
    });

    if (!response.success || !response.jobId) {
      throw new Error(response.error || 'Failed to start job');
    }

    // Add to local jobs map
    const job: Job = {
      id: response.jobId,
      type: jobType,
      status: response.status || 'queued',
      clip_ids: options.clipIds || [],
      scene_ids: options.sceneIds || [],
      depends_on: [],
      ...(options.generatorId && { generator_id: options.generatorId }),
      ...(options.generatorConfig && { generator_config: options.generatorConfig }),
      vram_gb_required: 0,
      created_at: Date.now() / 1000,
      artifact_paths: [],
      last_seq: 0,
      last_progress: 0,
    };

    jobs.value.set(job.id, job);

    if (!activeJobId.value) {
      activeJobId.value = job.id;
    }

    return job.id;
  }

  /**
   * Cancel a running job
   */
  async function cancelJob(jobId: string): Promise<void> {
    const response = await sendStreamMessage<{
      success: boolean;
      error?: string;
    }>('ve_job_cancel', { jobId });

    if (!response.success) {
      throw new Error(response.error || 'Failed to cancel job');
    }

    const job = jobs.value.get(jobId);
    if (job) {
      job.status = 'cancelled';
    }

    if (activeJobId.value === jobId) {
      activeJobId.value = null;
    }
  }

  /**
   * Get job status from server
   */
  async function refreshJob(jobId: string): Promise<Job | null> {
    const projectId = projectStore.projectId;
    if (!projectId) return null;

    const response = await sendControlMessage<{
      success: boolean;
      job?: Job;
    }>('ve_get_job', { projectId, jobId });

    if (response.success && response.job) {
      jobs.value.set(response.job.id, response.job);
      return response.job;
    }

    return null;
  }

  /**
   * Load all jobs for current project
   */
  async function loadJobs(): Promise<void> {
    const projectId = projectStore.projectId;
    if (!projectId) return;

    const response = await sendControlMessage<{
      success: boolean;
      jobs?: Job[];
    }>('ve_list_jobs', { projectId });

    if (response.success && response.jobs) {
      jobs.value.clear();
      for (const job of response.jobs) {
        jobs.value.set(job.id, job);
      }
    }
  }

  /**
   * Clear completed jobs from the list
   */
  function clearCompleted(): void {
    for (const [id, job] of jobs.value) {
      if (job.status === 'completed' || job.status === 'cancelled') {
        jobs.value.delete(id);
        jobProgress.value.delete(id);
      }
    }
  }

  // ─────────────────────────────────────────────────────────────────────
  // Generator Operations
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Load available generators from server
   */
  async function loadGenerators(type?: string): Promise<void> {
    isLoadingGenerators.value = true;

    try {
      const response = await sendControlMessage<{
        success: boolean;
        generators?: GeneratorCapabilities[];
      }>('ve_list_generators', { type });

      if (response.success && response.generators) {
        generators.value = response.generators;
      }
    } finally {
      isLoadingGenerators.value = false;
    }
  }

  /**
   * Find generators compatible with requirements
   */
  async function findCompatibleGenerators(
    type: string,
    options: {
      vramAvailableGb?: number;
      resolution?: [number, number];
      requiresI2v?: boolean;
      requiresFlf?: boolean;
      requiresVoiceCloning?: boolean;
    } = {},
  ): Promise<GeneratorCapabilities[]> {
    const response = await sendControlMessage<{
      success: boolean;
      generators?: GeneratorCapabilities[];
    }>('ve_find_compatible_generators', {
      type,
      vramAvailableGb: options.vramAvailableGb ?? 24.0,
      resolution: options.resolution,
      requiresI2v: options.requiresI2v,
      requiresFlf: options.requiresFlf,
      requiresVoiceCloning: options.requiresVoiceCloning,
    });

    return response.generators || [];
  }

  // ─────────────────────────────────────────────────────────────────────
  // Convenience Methods
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Start story generation job
   */
  async function generateStory(options?: {
    topic?: string;
    genre?: string;
    numScenes?: number;
    targetDurationSeconds?: number;
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    const projectId = projectStore.projectId;
    if (!projectId) {
      throw new Error('No project open');
    }

    // Pass story spec through to server
    const storySpec: Record<string, unknown> = {
      topic: options?.topic || projectStore.story.title || 'Untitled story',
      genre: options?.genre || projectStore.story.genre,
      num_scenes: options?.numScenes || 5,
    };

    if (options?.targetDurationSeconds) {
      storySpec.target_duration_seconds = options.targetDurationSeconds;
    }

    const response = await sendStreamMessage<{
      success: boolean;
      jobId?: string;
      status?: JobStatus;
      error?: string;
    }>('ve_job_start', {
      projectId,
      jobType: 'script_generate',
      generatorId: options?.generatorId || 'story_llm',
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
      storySpec,
    });

    if (!response.success || !response.jobId) {
      throw new Error(response.error || 'Failed to start story job');
    }

    const job: Job = {
      id: response.jobId,
      type: 'script_generate',
      status: response.status || 'queued',
      clip_ids: [],
      scene_ids: [],
      depends_on: [],
      generator_id: options?.generatorId ?? 'story_llm',
      vram_gb_required: 0,
      created_at: Date.now() / 1000,
      artifact_paths: [],
      last_seq: 0,
      last_progress: 0,
    };

    jobs.value.set(job.id, job);
    if (!activeJobId.value) {
      activeJobId.value = job.id;
    }

    return job.id;
  }

  /**
   * Start TTS generation for clips or all clips
   */
  async function generateAudio(options?: {
    clipIds?: string[];
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    return startJob('tts_generate', {
      clipIds: options?.clipIds || [],
      generatorId: options?.generatorId || 'tts_f5',
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Start image generation for clips or all clips
   */
  async function generateImages(options?: {
    clipIds?: string[];
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    return startJob('image_generate', {
      clipIds: options?.clipIds || [],
      generatorId: options?.generatorId || 't2i_sdxl',
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Start video generation for clips or all clips
   */
  async function generateVideo(options?: {
    clipIds?: string[];
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    return startJob('video_generate', {
      clipIds: options?.clipIds || [],
      generatorId: options?.generatorId || 'i2v_slideshow',
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Start final merge/export
   */
  async function exportProject(): Promise<string> {
    return startJob('final_merge');
  }

  /**
   * Start joint audio+video generation
   */
  async function generateAV(options?: {
    clipIds?: string[];
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    return startJob('av_generate', {
      clipIds: options?.clipIds || [],
      ...(options?.generatorId && { generatorId: options.generatorId }),
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Start lip-sync generation
   */
  async function generateLipSync(options?: {
    clipIds?: string[];
    generatorId?: string;
    generatorConfig?: Record<string, unknown>;
  }): Promise<string> {
    return startJob('lipsync', {
      clipIds: options?.clipIds || [],
      ...(options?.generatorId && { generatorId: options.generatorId }),
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Regenerate specific clips with mode
   */
  async function regenerateClips(
    clipIds: string[],
    mode: RegenerationMode,
    options?: {
      generatorId?: string;
      generatorConfig?: Record<string, unknown>;
    },
  ): Promise<string> {
    const modeToJobType: Record<string, JobType> = {
      preview_audio: 'tts_generate',
      regen_audio: 'tts_generate',
      regen_video: 'video_generate',
      regen_av: 'av_generate',
      regen_audio_video: 'video_generate',
      regen_chain: 'video_generate',
      regen_all_stale: 'video_generate',
    };

    const jobType: JobType = modeToJobType[mode] || 'video_generate';

    return startJob(jobType, {
      clipIds,
      regenerationMode: mode,
      ...(options?.generatorId && { generatorId: options.generatorId }),
      ...(options?.generatorConfig && { generatorConfig: options.generatorConfig }),
    });
  }

  /**
   * Run the full generation pipeline: story -> audio -> images -> video -> export
   */
  async function runFullPipeline(options?: {
    storyTopic?: string;
    storyGeneratorId?: string;
    ttsGeneratorId?: string;
    imageGeneratorId?: string;
    videoGeneratorId?: string;
  }): Promise<void> {
    // Step 1: Generate story
    await generateStory({
      ...(options?.storyTopic && { topic: options.storyTopic }),
      ...(options?.storyGeneratorId && { generatorId: options.storyGeneratorId }),
    });

    // Note: Subsequent steps should be triggered after completion
    // through the job progress handler or manual UI action
  }

  // ─────────────────────────────────────────────────────────────────────
  // Initialize
  // ─────────────────────────────────────────────────────────────────────

  // Load generators on store creation
  void loadGenerators();

  return {
    // State
    jobs,
    activeJobId,
    generators,
    isLoadingGenerators,
    jobProgress,

    // Computed
    jobList,
    pendingJobs,
    runningJobs,
    completedJobs,
    failedJobs,
    hasActiveJob,
    activeJob,
    activeJobProgress,
    llmGenerators,
    ttsGenerators,
    imageGenerators,
    videoGenerators,
    musicGenerators,
    avGenerators,
    lipsyncGenerators,
    sfxGenerators,

    // Job operations
    startJob,
    cancelJob,
    refreshJob,
    loadJobs,
    clearCompleted,
    handleJobProgress,
    refreshProjectAfterJob,

    // Generator operations
    loadGenerators,
    findCompatibleGenerators,

    // Convenience methods
    generateStory,
    generateAudio,
    generateImages,
    generateVideo,
    generateAV,
    generateLipSync,
    exportProject,
    regenerateClips,
    runFullPipeline,
  };
});
