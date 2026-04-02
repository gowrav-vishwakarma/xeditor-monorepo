"""
VRAM-Aware Job Queue (v2)

Manages generation jobs with:
- Single GPU lock (one heavy job at a time)
- Explicit job graph support (dependencies)
- Progress streaming via WebSocket
- Cancellation support
- All new job types: script, tts, image, video, av, music, sfx, lipsync, plan, merge
"""

import asyncio
import logging
import os
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("ve.jobs")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.DEBUG)

from apps.video_editor.models import (
    AssetType,
    ClipStatus,
    GeneratedAsset,
    GeneratorConfig,
    Job,
    JobProgressEvent,
    JobStatus,
    JobType,
    RegenerationMode,
    StoryScene,
    ScriptLine,
    Story,
    TimelineClip,
)
from apps.video_editor.generators.base import (
    AudioVideoGenerator,
    BaseGenerator,
    GeneratorRegistry,
    ImageGenerator,
    LLMGenerator,
    LipSyncGenerator,
    MusicGenerator,
    ProgressCallback,
    SFXGenerator,
    TTSGenerator,
    VideoGenerator,
    get_generator_registry,
)


# Type for WebSocket broadcast callback
BroadcastCallback = Callable[[str, Dict[str, Any]], Any]


@dataclass
class QueuedJob:
    """Internal representation of a queued job with runtime state."""
    job: Job
    project_id: str
    task: Optional[asyncio.Task[None]] = None
    cancelled: bool = False
    broadcast: Optional[BroadcastCallback] = None
    seq: int = 0


class JobQueue:
    """
    VRAM-aware job queue for video generation.

    Features:
    - Single GPU lock: only one heavy job runs at a time
    - Lightweight jobs (LLM via API) can run concurrently
    - Dependency resolution: jobs wait for dependencies
    - Progress streaming with sequence numbers
    - Graceful cancellation
    """

    def __init__(self, vram_budget_gb: float = 24.0):
        self.vram_budget_gb = vram_budget_gb
        self.vram_in_use_gb = 0.0

        # Job storage by project
        self._jobs: Dict[str, Dict[str, QueuedJob]] = {}  # project_id -> job_id -> job

        # Queue state
        self._running_job_id: Optional[str] = None
        self._pending_queue: List[QueuedJob] = []

        # Locks
        self._gpu_lock = asyncio.Lock()
        self._queue_lock = asyncio.Lock()

        # Cancellation tokens
        self._cancel_events: Dict[str, asyncio.Event] = {}

        # Shutdown flag
        self._shutdown = False

    async def enqueue(
        self,
        project_id: str,
        job: Job,
        broadcast: Optional[BroadcastCallback] = None,
    ) -> str:
        """
        Enqueue a job for execution.

        Returns:
            Job ID
        """
        async with self._queue_lock:
            if not job.id:
                job.id = str(uuid.uuid4())

            queued = QueuedJob(
                job=job,
                project_id=project_id,
                broadcast=broadcast,
            )

            if project_id not in self._jobs:
                self._jobs[project_id] = {}
            self._jobs[project_id][job.id] = queued

            self._cancel_events[job.id] = asyncio.Event()
            self._pending_queue.append(queued)
            job.status = JobStatus.QUEUED

            log.info(
                "[enqueue] %s job %s queued (project=%s, clips=%d, generator=%s)",
                job.type.value, job.id, project_id,
                len(job.clip_ids), job.generator_id or "default",
            )
            asyncio.create_task(self._process_queue())
            return job.id

    async def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event:
            cancel_event.set()

        for project_jobs in self._jobs.values():
            if job_id in project_jobs:
                queued = project_jobs[job_id]
                queued.cancelled = True
                queued.job.status = JobStatus.CANCELLED
                if queued.task and not queued.task.done():
                    queued.task.cancel()
                return True

        return False

    async def get_job(self, project_id: str, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        project_jobs = self._jobs.get(project_id, {})
        queued = project_jobs.get(job_id)
        return queued.job if queued else None

    async def list_jobs(self, project_id: str) -> List[Job]:
        """List all jobs for a project."""
        project_jobs = self._jobs.get(project_id, {})
        return [q.job for q in project_jobs.values()]

    async def clear_completed(self, project_id: str) -> int:
        """Clear completed/cancelled/failed jobs."""
        async with self._queue_lock:
            project_jobs = self._jobs.get(project_id, {})
            to_remove = [
                jid for jid, q in project_jobs.items()
                if q.job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED)
            ]
            for jid in to_remove:
                del project_jobs[jid]
                self._cancel_events.pop(jid, None)
            return len(to_remove)

    async def shutdown(self) -> None:
        """Graceful shutdown: cancel all running jobs."""
        self._shutdown = True
        for job_id in list(self._cancel_events.keys()):
            await self.cancel(job_id)

    # ─────────────────────────────────────────────────────────────────────
    # Queue processing
    # ─────────────────────────────────────────────────────────────────────

    async def _process_queue(self) -> None:
        """Process the pending queue and start eligible jobs."""
        if self._shutdown:
            return

        async with self._queue_lock:
            if self._running_job_id:
                return

            for i, queued in enumerate(self._pending_queue):
                if queued.cancelled:
                    continue
                if not await self._dependencies_met(queued):
                    continue

                vram_needed = queued.job.vram_gb_required
                if vram_needed > 0 and vram_needed > (self.vram_budget_gb - self.vram_in_use_gb):
                    continue

                self._pending_queue.pop(i)
                self._running_job_id = queued.job.id
                self.vram_in_use_gb += vram_needed
                queued.task = asyncio.create_task(self._run_job(queued))
                break

    async def _dependencies_met(self, queued: QueuedJob) -> bool:
        """Check if all job dependencies are completed."""
        for dep_id in queued.job.depends_on:
            for project_jobs in self._jobs.values():
                if dep_id in project_jobs:
                    if project_jobs[dep_id].job.status != JobStatus.COMPLETED:
                        return False
                    break
        return True

    async def _run_job(self, queued: QueuedJob) -> None:
        """Execute a job."""
        job = queued.job
        cancel_event = self._cancel_events.get(job.id)

        try:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().timestamp()

            log.info(
                "[run] ▶ %s job %s RUNNING (vram=%.1fGB)",
                job.type.value, job.id, job.vram_gb_required,
            )

            await self._broadcast_progress(queued, JobProgressEvent(
                job_id=job.id,
                seq=self._next_seq(queued),
                stage="starting",
                stage_progress=0.0,
                overall_progress=0.0,
                message=f"Starting {job.type.value} job",
            ))

            handler = self._get_handler(job.type)
            if handler is None:
                raise ValueError(f"No handler for job type: {job.type}")

            await handler(queued, cancel_event)

            if not queued.cancelled:
                elapsed = datetime.now().timestamp() - (job.started_at or 0)
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now().timestamp()
                log.info(
                    "[run] ✓ %s job %s COMPLETED in %.1fs",
                    job.type.value, job.id, elapsed,
                )
                await self._broadcast_progress(queued, JobProgressEvent(
                    job_id=job.id,
                    seq=self._next_seq(queued),
                    stage="completed",
                    stage_progress=1.0,
                    overall_progress=1.0,
                    message="Job completed successfully",
                ))

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            log.warning("[run] ✗ %s job %s CANCELLED", job.type.value, job.id)
            await self._broadcast_progress(queued, JobProgressEvent(
                job_id=job.id,
                seq=self._next_seq(queued),
                stage="cancelled",
                stage_progress=0.0,
                overall_progress=job.last_progress,
                message="Job was cancelled",
            ))

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now().timestamp()
            log.error(
                "[run] ✗ %s job %s FAILED: %s\n%s",
                job.type.value, job.id, e, traceback.format_exc(),
            )
            await self._broadcast_progress(queued, JobProgressEvent(
                job_id=job.id,
                seq=self._next_seq(queued),
                stage="error",
                stage_progress=0.0,
                overall_progress=job.last_progress,
                message=f"Job failed: {str(e)}",
            ))

        finally:
            async with self._queue_lock:
                if self._running_job_id == job.id:
                    self._running_job_id = None
                    self.vram_in_use_gb = max(0, self.vram_in_use_gb - job.vram_gb_required)
            self._cancel_events.pop(job.id, None)
            asyncio.create_task(self._process_queue())

    def _get_handler(self, job_type: JobType):  # type: ignore[return]
        """Get the handler function for a job type."""
        handlers = {
            JobType.SCRIPT_GENERATE: self._run_story_job,
            JobType.TTS_GENERATE: self._run_tts_job,
            JobType.IMAGE_GENERATE: self._run_image_job,
            JobType.VIDEO_GENERATE: self._run_video_job,
            JobType.AV_GENERATE: self._run_av_job,
            JobType.MUSIC_GENERATE: self._run_music_job,
            JobType.SFX_GENERATE: self._run_sfx_job,
            JobType.LIPSYNC: self._run_lipsync_job,
            JobType.SCENE_PLAN: self._run_plan_job,
            JobType.FINAL_MERGE: self._run_merge_job,
            JobType.MODEL_DOWNLOAD: self._run_model_download_job,
        }
        return handlers.get(job_type)

    # ─────────────────────────────────────────────────────────────────────
    # Progress helpers
    # ─────────────────────────────────────────────────────────────────────

    def _next_seq(self, queued: QueuedJob) -> int:
        queued.seq += 1
        queued.job.last_seq = queued.seq
        return queued.seq

    async def _broadcast_progress(
        self, queued: QueuedJob, event: JobProgressEvent
    ) -> None:
        queued.job.last_progress = event.overall_progress
        log.info(
            "[progress] %s | %s %.0f%% | %s",
            queued.job.id[:12], event.stage,
            event.overall_progress * 100, event.message,
        )
        if queued.broadcast:
            try:
                await queued.broadcast(
                    "ve_job_progress",
                    {"projectId": queued.project_id, "event": event.model_dump()},
                )
            except Exception as exc:
                log.warning("[progress] Failed to broadcast: %s", exc)

    def _make_progress_callback(
        self, queued: QueuedJob, stage: str,
        stage_weight: float = 1.0, stage_offset: float = 0.0,
    ) -> ProgressCallback:
        async def callback(event: JobProgressEvent) -> None:
            event.stage = stage
            event.overall_progress = stage_offset + (event.stage_progress * stage_weight)
            await self._broadcast_progress(queued, event)
        return callback

    # ─────────────────────────────────────────────────────────────────────
    # Generator resolution helper
    # ─────────────────────────────────────────────────────────────────────

    def _resolve_generator(
        self,
        generator_id: Optional[str],
        config: Optional[Dict[str, Any]],
        fallback_id: str = "",
    ) -> BaseGenerator:
        """Resolve and instantiate a generator."""
        registry = get_generator_registry()
        gid = generator_id or fallback_id

        if not gid:
            raise RuntimeError("No generator ID specified")

        gen_class = registry.get_generator_class(gid)
        if not gen_class and fallback_id and gid != fallback_id:
            log.warning("[resolve] Generator '%s' not found, falling back to '%s'", gid, fallback_id)
            gid = fallback_id
            gen_class = registry.get_generator_class(gid)
        if not gen_class:
            available = [g.id for g in registry.list_generators()]
            raise RuntimeError(
                f"Generator not found: {gid}. Available: {available}"
            )

        log.info("[resolve] Using generator: %s (%s)", gid, gen_class.__name__)
        gen_config = GeneratorConfig(
            generator_id=gid,
            custom=config or {},
        )
        return gen_class(gen_config)

    def _get_project(self, project_id: str):  # type: ignore[return]
        """Get project from manager."""
        from apps.video_editor.project import get_open_project
        project = get_open_project(project_id)
        if not project:
            raise RuntimeError("Project not found or not open")
        return project

    # ─────────────────────────────────────────────────────────────────────
    # Job Type Implementations
    # ─────────────────────────────────────────────────────────────────────

    async def _run_story_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run story generation job (LLM-based)."""
        from apps.video_editor.project import get_video_project_manager
        from apps.video_editor.models import SceneDescription

        job = queued.job
        project = self._get_project(queued.project_id)
        manager = get_video_project_manager()

        log.info("[story] Resolving LLM generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config, "story_llm")
        log.info("[story] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading story LLM: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[story] Model loaded")

        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError()

        try:
            spec = job.story_spec or {}
            topic = spec.get("topic", "")
            genre = spec.get("genre")
            num_scenes = spec.get("num_scenes", 5)
            target_duration = spec.get("target_duration_seconds")

            # Build character info for the prompt
            char_info = None
            if project.library.characters:
                char_info = [
                    {
                        "code": c.code,
                        "name": c.name,
                        "description": c.description or "",
                    }
                    for c in project.library.characters
                ]

            # Build code→id lookup
            char_code_to_id: Dict[str, str] = {}
            for c in project.library.characters:
                char_code_to_id[c.code.upper()] = c.id
                char_code_to_id[c.name.upper()] = c.id

            progress_cb = self._make_progress_callback(queued, "generating_story")

            if hasattr(gen, "generate_story"):
                result = await gen.generate_story(
                    topic=topic,
                    genre=genre,
                    num_scenes=num_scenes,
                    target_duration_seconds=target_duration,
                    characters=char_info,
                    progress_callback=progress_cb,
                )
            else:
                result = await gen.generate(prompt=topic, progress_callback=progress_cb)

            success = result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False)
            if not success:
                error = result.get("error") if isinstance(result, dict) else getattr(result, "error", "Unknown")
                raise RuntimeError(f"Story generation failed: {error}")

            story_data = result.get("story") if isinstance(result, dict) else None
            if story_data:
                scenes = []
                for idx, sd in enumerate(story_data.get("scenes", [])):
                    script_lines: List[ScriptLine] = []
                    scene_character_ids: List[str] = []

                    # New format: script_lines array with speaker/text/emotion
                    raw_lines = sd.get("script_lines", [])
                    if raw_lines:
                        for sl in raw_lines:
                            speaker = (sl.get("speaker") or "NARRATOR").strip().upper()
                            text = sl.get("text", "")
                            if not text:
                                continue

                            # Map speaker to character_id
                            character_id: Optional[str] = None
                            if speaker != "NARRATOR":
                                character_id = char_code_to_id.get(speaker)
                                if character_id and character_id not in scene_character_ids:
                                    scene_character_ids.append(character_id)

                            script_lines.append(ScriptLine(
                                text=text,
                                character_id=character_id,
                                emotion_hint=sl.get("emotion_hint"),
                                duration_hint=sl.get("duration_hint"),
                            ))
                    else:
                        # Legacy format: single narration string
                        narration = sd.get("narration", "")
                        if narration:
                            script_lines.append(ScriptLine(text=narration))

                    scenes.append(StoryScene(
                        title=sd.get("title", f"Scene {idx + 1}"),
                        order=idx,
                        script_lines=script_lines,
                        character_ids=scene_character_ids,
                        description=SceneDescription(
                            visual_prompt=sd.get("visual_prompt", ""),
                            camera_notes=sd.get("camera_notes"),
                        ),
                        duration_estimate=sd.get("duration_estimate", 5.0),
                    ))

                new_story = Story(
                    title=story_data.get("title", project.story.title),
                    genre=story_data.get("genre", project.story.genre),
                    synopsis=story_data.get("synopsis", ""),
                    scenes=scenes,
                    updated_at=datetime.now().timestamp(),
                )
                manager.update_story(queued.project_id, new_story)
                log.info("[story] ✓ Story updated with %d scenes", len(scenes))

        finally:
            log.info("[story] Unloading model...")
            await gen.unload()

    async def _run_tts_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run TTS generation for audio clips."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[tts] Resolving TTS generator (requested=%s)", job.generator_id)
        gen = self._resolve_generator(job.generator_id, job.generator_config, "tts_f5")

        log.info("[tts] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading TTS model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[tts] Model loaded successfully")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            if not clips:
                log.warning("[tts] No matching clips found for IDs: %s", job.clip_ids)
                return

            log.info("[tts] Processing %d clip(s)", len(clips))

            assets_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "audio"
            assets_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                texts = []
                for line_id in clip.script_line_ids:
                    for scene in project.story.scenes:
                        for line in scene.script_lines:
                            if line.id == line_id:
                                texts.append(line.text)

                if not texts:
                    log.warning("[tts] Clip %s has no script text, skipping", clip.id)
                    continue

                full_text = " ".join(texts)
                output_path = str(assets_dir / f"{clip.id}.wav")
                log.info(
                    "[tts] Clip %d/%d (%s): \"%s\"",
                    i + 1, len(clips), clip.id[:12],
                    full_text[:80] + ("..." if len(full_text) > 80 else ""),
                )

                voice_sample = None
                first_line_id = clip.script_line_ids[0] if clip.script_line_ids else None
                matched_line = None
                if first_line_id:
                    for scene in project.story.scenes:
                        for line in scene.script_lines:
                            if line.id == first_line_id:
                                matched_line = line
                                break
                        if matched_line:
                            break

                if matched_line and matched_line.voice_override:
                    voice_asset = next(
                        (v for v in project.library.voices if v.id == matched_line.voice_override),
                        None,
                    )
                    if voice_asset and voice_asset.sample_path:
                        voice_sample = str(Path(project.root_path or "") / voice_asset.sample_path)

                if not voice_sample and matched_line and matched_line.character_id:
                    char = next(
                        (c for c in project.library.characters if c.id == matched_line.character_id),
                        None,
                    )
                    if char:
                        if char.voice_id:
                            voice_asset = next(
                                (v for v in project.library.voices if v.id == char.voice_id),
                                None,
                            )
                            if voice_asset and voice_asset.sample_path:
                                voice_sample = str(Path(project.root_path or "") / voice_asset.sample_path)
                        elif char.voice_sample_path:
                            voice_sample = str(Path(project.root_path or "") / char.voice_sample_path)

                if not voice_sample and clip.scene_id:
                    scene = next((s for s in project.story.scenes if s.id == clip.scene_id), None)
                    if scene and scene.character_ids:
                        char = next(
                            (c for c in project.library.characters if c.id == scene.character_ids[0]),
                            None,
                        )
                        if char and char.voice_sample_path:
                            voice_sample = str(Path(project.root_path or "") / char.voice_sample_path)

                log.info(
                    "[tts] Voice sample: %s",
                    voice_sample or "(none / default voice)",
                )

                progress_cb = self._make_progress_callback(
                    queued, f"tts_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                if not isinstance(gen, TTSGenerator):
                    raise RuntimeError("Generator is not a TTSGenerator")

                result = await gen.generate(
                    text=full_text,
                    output_path=output_path,
                    voice_sample_path=voice_sample,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.audio_artifact_path = f"xeditor.video/assets/audio/{clip.id}.wav"
                    clip.duration = result.duration_seconds or clip.duration
                    clip.audio_generated_at = datetime.now().timestamp()
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.append(output_path)
                    log.info(
                        "[tts] ✓ Clip %s done (%.1fs audio → %s)",
                        clip.id[:12], result.duration_seconds or 0, output_path,
                    )
                else:
                    clip.status = ClipStatus.ERROR
                    log.error("[tts] ✗ Clip %s failed: %s", clip.id[:12], result.error)

        finally:
            log.info("[tts] Unloading model...")
            await gen.unload()
            log.info("[tts] Model unloaded")

    async def _run_image_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run image generation job (keyframes)."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[image] Resolving image generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config, "t2i_sdxl")
        log.info("[image] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading image model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[image] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            if not clips:
                log.warning("[image] No matching clips found")
                return

            images_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                spec = clip.generation_spec
                if not spec or not spec.prompt:
                    continue

                output_path = str(images_dir / f"keyframe_{clip.id}.png")
                progress_cb = self._make_progress_callback(
                    queued, f"image_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                if not isinstance(gen, ImageGenerator):
                    raise RuntimeError("Generator is not an ImageGenerator")

                result = await gen.generate(
                    prompt=spec.prompt,
                    output_path=output_path,
                    negative_prompt=spec.negative_prompt,
                    width=project.settings.canvas.width,
                    height=project.settings.canvas.height,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.keyframe_path = f"xeditor.video/assets/images/keyframe_{clip.id}.png"
                    clip.keyframe_edited_at = datetime.now().timestamp()
                    clip.status = ClipStatus.KEYFRAME_READY
                    job.artifact_paths.append(output_path)
                    log.info("[image] ✓ Clip %s keyframe generated", clip.id[:12])
                else:
                    clip.status = ClipStatus.ERROR
                    log.error("[image] ✗ Clip %s failed: %s", clip.id[:12], result.error)

        finally:
            log.info("[image] Unloading model...")
            await gen.unload()

    async def _run_video_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run video generation job."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[video] Resolving video generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config, "i2v_slideshow")
        log.info("[video] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading video model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[video] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            if not clips:
                log.warning("[video] No matching clips found")
                return

            videos_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                spec = clip.generation_spec
                output_path = str(videos_dir / f"clip_{clip.id}.mp4")
                progress_cb = self._make_progress_callback(
                    queued, f"video_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                # Resolve keyframe path
                first_frame = None
                if clip.keyframe_path:
                    first_frame = str(Path(project.root_path or "") / clip.keyframe_path)

                # Resolve continuity frame
                if spec and spec.link_first_frame_from and not first_frame:
                    prev_clip = next(
                        (c for c in project.timeline.clips
                         if c.id == spec.link_first_frame_from.clip_id),
                        None,
                    )
                    if prev_clip and prev_clip.video_artifact_path:
                        # Extract last frame from previous video
                        prev_video = str(Path(project.root_path or "") / prev_clip.video_artifact_path)
                        if os.path.exists(prev_video):
                            first_frame = await self._extract_last_frame(
                                prev_video, videos_dir / f"cont_{clip.id}.png"
                            )

                if not isinstance(gen, VideoGenerator):
                    raise RuntimeError("Generator is not a VideoGenerator")

                result = await gen.generate(
                    output_path=output_path,
                    prompt=spec.prompt if spec else None,
                    negative_prompt=spec.negative_prompt if spec else None,
                    motion_prompt=spec.motion_prompt if spec else None,
                    first_frame_path=first_frame,
                    duration_seconds=clip.duration,
                    fps=project.settings.canvas.fps,
                    width=project.settings.canvas.width,
                    height=project.settings.canvas.height,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.video_artifact_path = f"xeditor.video/assets/videos/clip_{clip.id}.mp4"
                    clip.video_generated_at = datetime.now().timestamp()
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.append(output_path)
                    log.info("[video] ✓ Clip %s generated (%.1fs)", clip.id[:12], result.duration_seconds)
                else:
                    clip.status = ClipStatus.ERROR
                    log.error("[video] ✗ Clip %s failed: %s", clip.id[:12], result.error)

        finally:
            log.info("[video] Unloading model...")
            await gen.unload()

    async def _run_av_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run joint audio+video generation job (e.g. LTX-2)."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[av] Resolving AV generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config)
        log.info("[av] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading AV model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[av] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            if not clips:
                return

            av_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "av"
            av_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                spec = clip.generation_spec
                video_out = str(av_dir / f"av_video_{clip.id}.mp4")
                audio_out = str(av_dir / f"av_audio_{clip.id}.wav")

                progress_cb = self._make_progress_callback(
                    queued, f"av_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                first_frame = None
                if clip.keyframe_path:
                    first_frame = str(Path(project.root_path or "") / clip.keyframe_path)

                if not isinstance(gen, AudioVideoGenerator):
                    raise RuntimeError("Generator is not an AudioVideoGenerator")

                result = await gen.generate(
                    video_output_path=video_out,
                    audio_output_path=audio_out,
                    prompt=spec.prompt if spec else None,
                    negative_prompt=spec.negative_prompt if spec else None,
                    motion_prompt=spec.motion_prompt if spec else None,
                    first_frame_path=first_frame,
                    duration_seconds=clip.duration,
                    fps=project.settings.canvas.fps,
                    width=project.settings.canvas.width,
                    height=project.settings.canvas.height,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.video_artifact_path = f"xeditor.video/assets/av/av_video_{clip.id}.mp4"
                    clip.audio_artifact_path = f"xeditor.video/assets/av/av_audio_{clip.id}.wav"
                    clip.av_generated_at = datetime.now().timestamp()
                    clip.video_generated_at = clip.av_generated_at
                    clip.audio_generated_at = clip.av_generated_at
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.extend([video_out, audio_out])
                else:
                    clip.status = ClipStatus.ERROR

        finally:
            log.info("[av] Unloading model...")
            await gen.unload()

    async def _run_music_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run music generation job."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[music] Resolving music generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config)
        log.info("[music] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading music model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[music] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            if not clips:
                return

            music_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "music"
            music_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                spec = clip.generation_spec
                output_path = str(music_dir / f"music_{clip.id}.wav")
                progress_cb = self._make_progress_callback(
                    queued, f"music_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                if not isinstance(gen, MusicGenerator):
                    raise RuntimeError("Generator is not a MusicGenerator")

                result = await gen.generate(
                    prompt=spec.prompt if spec else "background music",
                    output_path=output_path,
                    duration_seconds=clip.duration,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.audio_artifact_path = f"xeditor.video/assets/music/music_{clip.id}.wav"
                    clip.audio_generated_at = datetime.now().timestamp()
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.append(output_path)
                    log.info("[music] ✓ Clip %s generated", clip.id[:12])
                else:
                    clip.status = ClipStatus.ERROR
                    log.error("[music] ✗ Clip %s failed: %s", clip.id[:12], result.error)

        finally:
            log.info("[music] Unloading model...")
            await gen.unload()

    async def _run_sfx_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run sound effects generation job."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[sfx] Resolving SFX generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config)
        log.info("[sfx] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading SFX model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[sfx] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            sfx_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "sfx"
            sfx_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                spec = clip.generation_spec
                output_path = str(sfx_dir / f"sfx_{clip.id}.wav")
                progress_cb = self._make_progress_callback(
                    queued, f"sfx_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                if not isinstance(gen, SFXGenerator):
                    raise RuntimeError("Generator is not an SFXGenerator")

                result = await gen.generate(
                    prompt=spec.prompt if spec else "sound effect",
                    output_path=output_path,
                    duration_seconds=clip.duration,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.audio_artifact_path = f"xeditor.video/assets/sfx/sfx_{clip.id}.wav"
                    clip.audio_generated_at = datetime.now().timestamp()
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.append(output_path)
                    log.info("[sfx] ✓ Clip %s generated", clip.id[:12])

        finally:
            log.info("[sfx] Unloading model...")
            await gen.unload()

    async def _run_lipsync_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run lip-sync generation job."""
        job = queued.job
        project = self._get_project(queued.project_id)

        log.info("[lipsync] Resolving lipsync generator...")
        gen = self._resolve_generator(job.generator_id, job.generator_config)
        log.info("[lipsync] Loading model...")
        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id, seq=self._next_seq(queued),
            stage="loading_model", stage_progress=0.0, overall_progress=0.0,
            message=f"Loading lipsync model: {gen.config.generator_id}",
        ))
        await gen.load()
        log.info("[lipsync] Model loaded")

        try:
            clips = [c for c in project.timeline.clips if c.id in job.clip_ids]
            lipsync_dir = Path(project.root_path or "") / "xeditor.video" / "assets" / "lipsync"
            lipsync_dir.mkdir(parents=True, exist_ok=True)

            for i, clip in enumerate(clips):
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()

                if not clip.video_artifact_path or not clip.audio_artifact_path:
                    continue

                video_in = str(Path(project.root_path or "") / clip.video_artifact_path)
                audio_in = str(Path(project.root_path or "") / clip.audio_artifact_path)
                output_path = str(lipsync_dir / f"lipsync_{clip.id}.mp4")

                progress_cb = self._make_progress_callback(
                    queued, f"lipsync_{i+1}", 1.0 / len(clips), i / len(clips)
                )

                # Get face reference if character is assigned
                face_ref = None
                if clip.scene_id:
                    scene = next((s for s in project.story.scenes if s.id == clip.scene_id), None)
                    if scene and scene.character_ids:
                        char = next(
                            (c for c in project.library.characters if c.id == scene.character_ids[0]),
                            None,
                        )
                        if char and char.image_path:
                            face_ref = str(Path(project.root_path or "") / char.image_path)

                if not isinstance(gen, LipSyncGenerator):
                    raise RuntimeError("Generator is not a LipSyncGenerator")

                result = await gen.generate(
                    video_input_path=video_in,
                    audio_input_path=audio_in,
                    output_path=output_path,
                    face_ref_path=face_ref,
                    progress_callback=progress_cb,
                )

                if result.success:
                    clip.video_artifact_path = f"xeditor.video/assets/lipsync/lipsync_{clip.id}.mp4"
                    clip.video_generated_at = datetime.now().timestamp()
                    clip.status = ClipStatus.DONE
                    job.artifact_paths.append(output_path)
                    log.info("[lipsync] ✓ Clip %s generated", clip.id[:12])

        finally:
            log.info("[lipsync] Unloading model...")
            await gen.unload()

    async def _run_plan_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run scene planning job (audio-first clip splitting)."""
        from apps.video_editor.planner import plan_all_scenes, replan_scene

        job = queued.job
        project = self._get_project(queued.project_id)

        if job.scene_ids:
            log.info("[plan] Replanning %d scene(s)...", len(job.scene_ids))
            for scene_id in job.scene_ids:
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()
                replan_scene(project, scene_id)
        else:
            log.info("[plan] Planning all scenes...")
            plan_all_scenes(project)
        log.info("[plan] Planning complete")

    async def _run_merge_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Run final merge/export job using FFmpeg."""
        log.info("[merge] Starting final merge/export...")
        job = queued.job
        project = self._get_project(queued.project_id)

        renders_dir = Path(project.root_path or "") / "xeditor.video" / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)

        output_path = str(renders_dir / f"export_{job.id}.mp4")

        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id,
            seq=self._next_seq(queued),
            stage="merging",
            stage_progress=0.1,
            overall_progress=0.1,
            message="Preparing video tracks for merge...",
        ))

        # Gather all video clips in timeline order
        video_clips = sorted(
            [c for c in project.timeline.clips
             if c.video_artifact_path and c.track_id.startswith("video")],
            key=lambda c: c.start_time,
        )

        # Gather all audio clips (dialog, music, sfx) -- skip muted tracks
        muted_track_ids = {t.id for t in project.timeline.tracks if t.muted}
        audio_clips = sorted(
            [c for c in project.timeline.clips
             if c.audio_artifact_path
             and c.track_id not in muted_track_ids
             and not c.track_id.startswith("video")],
            key=lambda c: c.start_time,
        )

        if not video_clips:
            raise RuntimeError("No video clips to merge")

        log.info(
            "[merge] Found %d video clips, %d audio clips (muted tracks: %s)",
            len(video_clips), len(audio_clips),
            muted_track_ids or "none",
        )

        root = Path(project.root_path or "")

        # Build FFmpeg concat file for video
        concat_file = renders_dir / f"concat_{job.id}.txt"
        with open(concat_file, "w") as f:
            for clip in video_clips:
                video_path = root / clip.video_artifact_path
                if video_path.exists():
                    f.write(f"file '{video_path}'\n")

        import subprocess

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
        ]

        # Add audio inputs with per-clip volume/fade filters
        audio_inputs = []
        filter_parts = []
        for idx, ac in enumerate(audio_clips):
            audio_path = root / ac.audio_artifact_path
            if not audio_path.exists():
                continue
            cmd.extend(["-i", str(audio_path)])
            audio_inputs.append(ac)

            input_idx = idx + 1  # 0 is video concat
            filters = []
            vol = ac.volume if ac.volume is not None else 1.0
            if vol != 1.0:
                filters.append(f"volume={vol}")
            if ac.fade_in_seconds and ac.fade_in_seconds > 0:
                filters.append(f"afade=t=in:st=0:d={ac.fade_in_seconds}")
            if ac.fade_out_seconds and ac.fade_out_seconds > 0:
                filters.append(f"afade=t=out:st={max(0, ac.duration - ac.fade_out_seconds)}:d={ac.fade_out_seconds}")

            if filters:
                filter_chain = ",".join(filters)
                filter_parts.append(f"[{input_idx}:a]{filter_chain}[a{idx}]")
            else:
                filter_parts.append(f"[{input_idx}:a]acopy[a{idx}]")

        # If multiple audio streams, mix them down
        if len(audio_inputs) > 1:
            mix_inputs = "".join(f"[a{i}]" for i in range(len(audio_inputs)))
            filter_parts.append(f"{mix_inputs}amix=inputs={len(audio_inputs)}:duration=longest[aout]")
            filter_str = ";".join(filter_parts)
            cmd.extend(["-filter_complex", filter_str, "-map", "0:v", "-map", "[aout]"])
        elif len(audio_inputs) == 1:
            filter_str = ";".join(filter_parts)
            cmd.extend(["-filter_complex", filter_str, "-map", "0:v", "-map", "[a0]"])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
        ])

        if audio_inputs:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.append(output_path)

        log.info("[merge] FFmpeg command: %s", " ".join(cmd[:6]) + " ...")

        await self._broadcast_progress(queued, JobProgressEvent(
            job_id=job.id,
            seq=self._next_seq(queued),
            stage="encoding",
            stage_progress=0.5,
            overall_progress=0.5,
            message="Encoding final video...",
        ))

        proc = subprocess.run(cmd, capture_output=True, text=True)

        concat_file.unlink(missing_ok=True)

        if proc.returncode != 0:
            log.error("[merge] FFmpeg failed (exit %d): %s", proc.returncode, proc.stderr[-1000:] if proc.stderr else "")
            raise RuntimeError(f"FFmpeg failed: {proc.stderr[-500:] if proc.stderr else 'Unknown error'}")

        log.info("[merge] ✓ Export written to %s", output_path)
        job.artifact_paths.append(output_path)

        # Add to generated assets
        project.library.generated.append(GeneratedAsset(
            asset_type=AssetType.VIDEO,
            path=f"xeditor.video/renders/export_{job.id}.mp4",
            source_prompt="Final export",
            metadata={"type": "export"},
        ))

    # ─────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────
    # Model Download Job
    # ─────────────────────────────────────────────────────────────────────

    async def _run_model_download_job(
        self, queued: QueuedJob, cancel_event: Optional[asyncio.Event]
    ) -> None:
        """Download a HuggingFace model to the local cache."""
        import asyncio as _aio

        job = queued.job
        config = job.generator_config or {}

        # Determine what to download
        repo_id = config.get("custom_model_repo_id", "").strip()
        if not repo_id:
            repo_id = config.get("model_repo_id", "")
        if not repo_id:
            raise RuntimeError("No model_repo_id specified for download")

        cache_dir = config.get(
            "models_cache_dir",
            str(Path.home() / ".cache" / "xeditor" / "models" / "hf"),
        )

        progress_cb = self._make_progress_callback(queued, "downloading_model")

        await progress_cb(JobProgressEvent(
            job_id=job.id,
            seq=self._next_seq(queued),
            stage="downloading_model",
            stage_progress=0.05,
            overall_progress=0.05,
            message=f"Starting download of {repo_id}…",
        ))

        if cancel_event and cancel_event.is_set():
            raise _aio.CancelledError()

        # Run the blocking download in a thread
        def _download() -> str:
            from huggingface_hub import snapshot_download
            return snapshot_download(
                repo_id,
                cache_dir=cache_dir,
                resume_download=True,
            )

        loop = _aio.get_running_loop()
        local_path = await loop.run_in_executor(None, _download)

        if cancel_event and cancel_event.is_set():
            raise _aio.CancelledError()

        await progress_cb(JobProgressEvent(
            job_id=job.id,
            seq=self._next_seq(queued),
            stage="download_complete",
            stage_progress=1.0,
            overall_progress=1.0,
            message=f"Model downloaded: {repo_id} → {local_path}",
        ))

        job.artifact_paths.append(local_path)

    # ─────────────────────────────────────────────────────────────────────

    async def _extract_last_frame(self, video_path: str, output_path: Path) -> Optional[str]:
        """Extract the last frame from a video file."""
        try:
            from moviepy import VideoFileClip
            from PIL import Image
            import numpy as np

            with VideoFileClip(video_path) as clip:
                frame = clip.get_frame(clip.duration - 0.01)
            img = Image.fromarray(frame)
            img.save(str(output_path))
            return str(output_path)
        except Exception as e:
            print(f"[JobQueue] Failed to extract last frame: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_job_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get the singleton job queue."""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue


# ─────────────────────────────────────────────────────────────────────────────
# RPC Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def handle_ve_start_job(
    payload: Dict[str, Any],
    broadcast: Optional[BroadcastCallback] = None,
) -> Dict[str, Any]:
    """RPC handler for starting a generation job."""
    project_id = payload.get("projectId", "")
    job_type_str = payload.get("jobType", "")
    clip_ids = payload.get("clipIds", [])
    scene_ids = payload.get("sceneIds", [])
    generator_id = payload.get("generatorId")
    generator_config = payload.get("generatorConfig")
    story_spec = payload.get("storySpec")

    log.info(
        "[rpc] ve_job_start: type=%s, project=%s, clips=%d, scenes=%d, generator=%s",
        job_type_str, project_id[:12] if project_id else "?",
        len(clip_ids), len(scene_ids), generator_id or "default",
    )

    if not project_id or not job_type_str:
        return {"success": False, "error": "projectId and jobType are required"}

    try:
        job_type = JobType(job_type_str)
    except ValueError:
        return {"success": False, "error": f"Invalid job type: {job_type_str}"}

    # Set VRAM requirement from generator capabilities
    vram_required = 0.0
    if generator_id:
        registry = get_generator_registry()
        gen_class = registry.get_generator_class(generator_id)
        if gen_class:
            vram_required = gen_class.get_capabilities().vram_gb_min

    job = Job(
        type=job_type,
        clip_ids=clip_ids,
        scene_ids=scene_ids,
        generator_id=generator_id,
        generator_config=generator_config,
        story_spec=story_spec,
        vram_gb_required=vram_required,
    )

    queue = get_job_queue()
    job_id = await queue.enqueue(project_id, job, broadcast)

    return {"success": True, "jobId": job_id}


async def handle_ve_cancel_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for cancelling a job."""
    job_id = payload.get("jobId", "")
    if not job_id:
        return {"success": False, "error": "jobId is required"}

    queue = get_job_queue()
    cancelled = await queue.cancel(job_id)
    return {"success": cancelled}


async def handle_ve_get_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for getting job details."""
    project_id = payload.get("projectId", "")
    job_id = payload.get("jobId", "")

    queue = get_job_queue()
    job = await queue.get_job(project_id, job_id)
    if not job:
        return {"success": False, "error": "Job not found"}

    return {"success": True, "job": job.model_dump()}


async def handle_ve_list_jobs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for listing jobs."""
    project_id = payload.get("projectId", "")
    if not project_id:
        return {"success": False, "error": "projectId is required"}

    queue = get_job_queue()
    jobs = await queue.list_jobs(project_id)
    return {"success": True, "jobs": [j.model_dump() for j in jobs]}
