"""
Video Editor WebSocket Routes

Provides dual WebSocket endpoints for the video editor:
- /ws/ve/control: RPC operations (project CRUD, asset management)
- /ws/ve/stream: Streaming operations (job progress, generation)

This follows the same pattern as code_editor but with separate endpoints
to avoid interference between the two apps.
"""

import json
import asyncio
from typing import Dict, Any, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.video_editor.project import (
    handle_ve_create_project,
    handle_ve_open_project,
    handle_ve_save_project,
    handle_ve_close_project,
    handle_ve_get_project,
    handle_ve_list_recent_projects,
    handle_ve_check_folder,
    handle_ve_update_settings,
    handle_ve_update_library,
    handle_ve_update_story,
    handle_ve_update_timeline,
    handle_ve_put_project_state,
)
from apps.video_editor.generators.base import (
    handle_ve_list_generators,
    handle_ve_get_generator_capabilities,
    handle_ve_find_compatible_generators,
    get_generator_registry,
)
from apps.video_editor.generators.discovery import (
    discover_custom_generators,
    handle_ve_custom_generators_list,
    handle_ve_custom_generators_add,
    handle_ve_custom_generators_remove,
    handle_ve_generators_reload,
)
from apps.video_editor.jobs.queue import (
    handle_ve_start_job,
    handle_ve_cancel_job,
    handle_ve_get_job,
    handle_ve_list_jobs,
    get_job_queue,
)
from apps.video_editor.planner import (
    handle_ve_plan_scene,
    handle_ve_plan_all_scenes,
)
from apps.video_editor.assets import router as assets_router
from apps.code_editor.filesystem import (
    handle_get_home_directory,
    handle_list_directory,
)


router = APIRouter(prefix="/video-editor", tags=["video-editor"])

# Include assets sub-router → endpoints become /video-editor/assets/*
router.include_router(assets_router)


# Track connected WebSocket clients
_stream_websockets: Set[WebSocket] = set()
_control_websockets: Set[WebSocket] = set()

# Message types for stream endpoint
STREAM_MESSAGE_TYPES = {"ve_job_start", "ve_job_cancel", "ve_job_resume"}


async def init_video_editor() -> None:
    """Initialize video editor on startup."""
    print("[video_editor] Initializing video editor...")
    
    # Register built-in generators
    registry = get_generator_registry()
    
    # Import generators with error handling for missing dependencies
    generators_to_register = []
    
    try:
        from apps.video_editor.generators.impl.story_llm import StoryLLMGenerator
        generators_to_register.append(StoryLLMGenerator)
        print("[video_editor] Registered: StoryLLMGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping StoryLLMGenerator: {e}")
    
    # Coqui XTTS is abandoned and incompatible with modern transformers/huggingface_hub.
    # Use F5-TTS instead.
    print("[video_editor] Skipping CoquiXTTSGenerator (deprecated, use F5-TTS)")
    
    try:
        from apps.video_editor.generators.impl.t2i_sdxl import SDXLT2IGenerator
        generators_to_register.append(SDXLT2IGenerator)
        print("[video_editor] Registered: SDXLT2IGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping SDXLT2IGenerator: {e}")
    
    try:
        from apps.video_editor.generators.impl.i2v_slideshow import SlideshowI2VGenerator
        generators_to_register.append(SlideshowI2VGenerator)
        print("[video_editor] Registered: SlideshowI2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping SlideshowI2VGenerator: {e}")
    
    try:
        from apps.video_editor.generators.impl.i2v_svd import SVDI2VGenerator
        generators_to_register.append(SVDI2VGenerator)
        print("[video_editor] Registered: SVDI2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping SVDI2VGenerator: {e}")
    
    try:
        from apps.video_editor.generators.impl.t2v_wan import WanT2VGenerator
        generators_to_register.append(WanT2VGenerator)
        print("[video_editor] Registered: WanT2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping WanT2VGenerator: {e}")
    
    try:
        from apps.video_editor.generators.impl.t2v_zeroscope import ZeroscopeT2VGenerator
        generators_to_register.append(ZeroscopeT2VGenerator)
        print("[video_editor] Registered: ZeroscopeT2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping ZeroscopeT2VGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.tts_f5 import F5TTSGenerator
        generators_to_register.append(F5TTSGenerator)
        print("[video_editor] Registered: F5TTSGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping F5TTSGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.music_musicgen import MusicGenGenerator
        generators_to_register.append(MusicGenGenerator)
        print("[video_editor] Registered: MusicGenGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping MusicGenGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.music_acestep import ACEStepMusicGenerator
        generators_to_register.append(ACEStepMusicGenerator)
        print("[video_editor] Registered: ACEStepMusicGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping ACEStepMusicGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.sfx_audiogen import AudioGenSFXGenerator
        generators_to_register.append(AudioGenSFXGenerator)
        print("[video_editor] Registered: AudioGenSFXGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping AudioGenSFXGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.t2i_ipadapter import IPAdapterSDXLGenerator
        generators_to_register.append(IPAdapterSDXLGenerator)
        print("[video_editor] Registered: IPAdapterSDXLGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping IPAdapterSDXLGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.t2v_cogvideox import CogVideoXT2VGenerator
        generators_to_register.append(CogVideoXT2VGenerator)
        print("[video_editor] Registered: CogVideoXT2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping CogVideoXT2VGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.i2v_wan import WanI2VGenerator
        generators_to_register.append(WanI2VGenerator)
        print("[video_editor] Registered: WanI2VGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping WanI2VGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.t2v_hunyuan import HunyuanVideoGenerator
        generators_to_register.append(HunyuanVideoGenerator)
        print("[video_editor] Registered: HunyuanVideoGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping HunyuanVideoGenerator: {e}")

    try:
        from apps.video_editor.generators.impl.lipsync_musetalk import MuseTalkLipSyncGenerator
        generators_to_register.append(MuseTalkLipSyncGenerator)
        print("[video_editor] Registered: MuseTalkLipSyncGenerator")
    except ImportError as e:
        print(f"[video_editor] Skipping MuseTalkLipSyncGenerator: {e}")

    # Register all loaded generators
    for gen_class in generators_to_register:
        try:
            registry.register(gen_class)
        except Exception as e:
            print(f"[video_editor] Error registering {gen_class.__name__}: {e}")
    
    print(f"[video_editor] Registered {len(generators_to_register)} built-in generators")

    # Discover custom generators from plugins directory
    custom_results = discover_custom_generators(registry)
    custom_ok = sum(1 for errs in custom_results.values() if not errs)
    custom_fail = sum(1 for errs in custom_results.values() if errs)
    if custom_results:
        print(f"[video_editor] Custom generators: {custom_ok} loaded, {custom_fail} failed")
        for gen_id, errs in custom_results.items():
            if errs:
                print(f"[video_editor]   FAILED {gen_id}: {'; '.join(errs)}")

    total = len(registry.list_generators())
    print(f"[video_editor] Initialized with {total} total generators")


async def shutdown_video_editor() -> None:
    """Cleanup video editor on shutdown."""
    print("[video_editor] Shutting down video editor...")
    
    # Shutdown job queue
    queue = get_job_queue()
    await queue.shutdown()
    
    # Unload all generators
    registry = get_generator_registry()
    await registry.unload_all()
    
    print("[video_editor] Shutdown complete")


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Endpoints (for compatibility)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
async def root():
    """Video editor API root."""
    return {
        "status": "ok",
        "message": "Video Editor API",
        "version": "1.0.0",
    }


@router.get("/capabilities")
async def capabilities():
    """Return video editor capabilities."""
    return {
        "status": "ok",
        "capabilities": {
            "dualWebSocket": True,
            "streamEndpoint": "/ws/ve/stream",
            "controlEndpoint": "/ws/ve/control",
            "jobTypes": [
                "script_generate", "tts_generate", "image_generate",
                "video_generate", "av_generate", "music_generate",
                "sfx_generate", "lipsync", "scene_plan",
                "final_merge", "model_download",
            ],
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stream WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/ve/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for streaming operations.
    
    Handles:
    - ve_job_start: Start a generation job
    - ve_job_cancel: Cancel a running job
    - ve_job_resume: Resume job progress stream
    
    Receives:
    - ve_job_progress: Job progress events
    """
    await websocket.accept()
    print("[video_editor] Client connected (stream)")
    _stream_websockets.add(websocket)
    
    async def broadcast_to_client(msg_type: str, payload: Dict[str, Any]) -> None:
        """Send a message to this client."""
        try:
            await websocket.send_text(json.dumps({
                "type": msg_type,
                "payload": payload,
            }))
        except Exception:
            pass
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            msg_type = message.get("type")
            request_id = message.get("id")
            payload = message.get("payload", {})
            
            print(f"[video_editor/stream] Received: {msg_type} (ID: {request_id})")
            
            try:
                if msg_type == "ve_job_start":
                    response = await handle_ve_start_job(payload, broadcast_to_client)
                    await websocket.send_text(json.dumps({
                        "type": "ve_job_start_response",
                        "id": request_id,
                        "payload": response,
                    }))
                
                elif msg_type == "ve_job_cancel":
                    response = await handle_ve_cancel_job(payload)
                    await websocket.send_text(json.dumps({
                        "type": "ve_job_cancel_response",
                        "id": request_id,
                        "payload": response,
                    }))
                
                elif msg_type == "ve_job_resume":
                    # Resume job progress from a sequence number
                    # TODO: Implement job progress resumption
                    await websocket.send_text(json.dumps({
                        "type": "ve_job_resume_response",
                        "id": request_id,
                        "payload": {"success": True, "message": "Resume not yet implemented"},
                    }))
                
                elif msg_type == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "id": request_id,
                    }))
                
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "id": request_id,
                        "message": f"Unsupported message type for stream endpoint: {msg_type}. Use /ws/ve/control for this operation.",
                    }))
            
            except Exception as e:
                print(f"[video_editor/stream] Error processing {msg_type}: {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "id": request_id,
                    "message": f"Request failed: {str(e)}",
                }))
    
    except WebSocketDisconnect:
        print("[video_editor] Client disconnected (stream)")
    except Exception as e:
        print(f"[video_editor] WebSocket error (stream): {e}")
    finally:
        _stream_websockets.discard(websocket)


# ─────────────────────────────────────────────────────────────────────────────
# Control WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/ve/control")
async def websocket_control_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for control/RPC operations.
    
    Handles:
    - Project operations (create, open, save, close)
    - Asset library management
    - Story updates
    - Timeline updates
    - Generator queries
    - Job status queries
    """
    await websocket.accept()
    print("[video_editor] Client connected (control)")
    _control_websockets.add(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            msg_type = message.get("type")
            request_id = message.get("id")
            payload = message.get("payload", {})
            
            print(f"[video_editor/control] Received: {msg_type} (ID: {request_id})")
            
            # Reject streaming messages on control endpoint
            if msg_type in STREAM_MESSAGE_TYPES:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "id": request_id,
                    "message": f"Message type '{msg_type}' should be sent to /ws/ve/stream endpoint",
                }))
                continue
            
            try:
                response = None
                response_type = f"{msg_type}_response"
                
                # ─────────────────────────────────────────────────────────
                # Project Operations
                # ─────────────────────────────────────────────────────────
                
                if msg_type == "ve_create_project":
                    response = await handle_ve_create_project(payload)
                
                elif msg_type == "ve_open_project":
                    response = await handle_ve_open_project(payload)
                
                elif msg_type == "ve_save_project":
                    response = await handle_ve_save_project(payload)
                
                elif msg_type == "ve_close_project":
                    response = await handle_ve_close_project(payload)
                
                elif msg_type == "ve_get_project":
                    response = await handle_ve_get_project(payload)
                
                elif msg_type == "ve_list_recent_projects":
                    response = await handle_ve_list_recent_projects(payload)
                
                elif msg_type == "ve_check_folder":
                    response = await handle_ve_check_folder(payload)
                
                # ─────────────────────────────────────────────────────────
                # Project Updates
                # ─────────────────────────────────────────────────────────
                
                elif msg_type == "ve_update_settings":
                    response = await handle_ve_update_settings(payload)
                
                elif msg_type == "ve_update_library":
                    response = await handle_ve_update_library(payload)
                
                elif msg_type == "ve_update_story":
                    response = await handle_ve_update_story(payload)
                
                elif msg_type == "ve_update_timeline":
                    response = await handle_ve_update_timeline(payload)
                
                elif msg_type == "ve_put_project_state":
                    response = await handle_ve_put_project_state(payload)
                
                # ─────────────────────────────────────────────────────────
                # Generator Operations
                # ─────────────────────────────────────────────────────────
                
                elif msg_type == "ve_list_generators":
                    response = await handle_ve_list_generators(payload)
                
                elif msg_type == "ve_get_generator_capabilities":
                    response = await handle_ve_get_generator_capabilities(payload)
                
                elif msg_type == "ve_find_compatible_generators":
                    response = await handle_ve_find_compatible_generators(payload)

                # ─────────────────────────────────────────────────────────
                # Custom Generator Management
                # ─────────────────────────────────────────────────────────

                elif msg_type == "ve_custom_generators_list":
                    response = await handle_ve_custom_generators_list(payload)

                elif msg_type == "ve_custom_generators_add":
                    response = await handle_ve_custom_generators_add(payload)

                elif msg_type == "ve_custom_generators_remove":
                    response = await handle_ve_custom_generators_remove(payload)

                elif msg_type == "ve_generators_reload":
                    response = await handle_ve_generators_reload(payload)

                # ─────────────────────────────────────────────────────────
                # Scene Planning
                # ─────────────────────────────────────────────────────────

                elif msg_type == "ve_plan_scene":
                    response = await handle_ve_plan_scene(payload)

                elif msg_type == "ve_plan_all_scenes":
                    response = await handle_ve_plan_all_scenes(payload)

                # ─────────────────────────────────────────────────────────
                # Job Queries (not start/cancel which go on stream)
                # ─────────────────────────────────────────────────────────
                
                elif msg_type == "ve_get_job":
                    response = await handle_ve_get_job(payload)
                
                elif msg_type == "ve_list_jobs":
                    response = await handle_ve_list_jobs(payload)
                
                # ─────────────────────────────────────────────────────────
                # Filesystem (shared with code editor)
                # ─────────────────────────────────────────────────────────

                elif msg_type == "get_home_directory":
                    response = await handle_get_home_directory(payload)

                elif msg_type == "list_directory":
                    response = await handle_list_directory(payload)

                # ─────────────────────────────────────────────────────────
                # Utility
                # ─────────────────────────────────────────────────────────
                
                elif msg_type == "ping":
                    response = {"pong": True}
                    response_type = "pong"
                
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "id": request_id,
                        "message": f"Unknown message type: {msg_type}",
                    }))
                    continue
                
                # Send response
                await websocket.send_text(json.dumps({
                    "type": response_type,
                    "id": request_id,
                    "payload": response,
                }))
            
            except Exception as e:
                print(f"[video_editor/control] Error processing {msg_type}: {e}")
                import traceback
                traceback.print_exc()
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "id": request_id,
                    "message": f"Request failed: {str(e)}",
                }))
    
    except WebSocketDisconnect:
        print("[video_editor] Client disconnected (control)")
    except Exception as e:
        print(f"[video_editor] WebSocket error (control): {e}")
    finally:
        _control_websockets.discard(websocket)


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast Utilities
# ─────────────────────────────────────────────────────────────────────────────

async def broadcast_to_stream(msg_type: str, payload: Dict[str, Any]) -> None:
    """Broadcast a message to all stream clients."""
    message = json.dumps({"type": msg_type, "payload": payload})
    disconnected = set()
    
    for ws in _stream_websockets:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    
    for ws in disconnected:
        _stream_websockets.discard(ws)


async def broadcast_to_control(msg_type: str, payload: Dict[str, Any]) -> None:
    """Broadcast a message to all control clients."""
    message = json.dumps({"type": msg_type, "payload": payload})
    disconnected = set()
    
    for ws in _control_websockets:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    
    for ws in disconnected:
        _control_websockets.discard(ws)
