"""
Video Editor Project Manager

Handles project operations for video projects stored in user-selected folders.
Unlike the code editor which stores projects in ~/.xeditor, video projects are
stored entirely within the user's chosen folder.

Project structure:
  /user-selected-folder/
    xeditor.video.project.json  <- Openable project file (root marker)
    xeditor.video/
      project.json              <- Full project state
      assets/
        characters/
        props/
        voices/
        audio/                  <- Generated TTS audio
        video/                  <- Generated video clips
        images/                 <- Generated images
      story/
        story.json              <- Story structure
      renders/                  <- Final exports
      cache/
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from apps.video_editor.models import (
    VideoProject,
    ProjectSettings,
    AssetLibrary,
    Story,
    Timeline,
    JobQueue,
    CreateProjectRequest,
    CreateProjectResponse,
    OpenProjectRequest,
    OpenProjectResponse,
    SaveProjectRequest,
    SaveProjectResponse,
)


# File names
ROOT_PROJECT_FILE = "xeditor.video.project.json"
PROJECT_DIR = "xeditor.video"
STATE_FILE = "project.json"
STORY_FILE = "story/story.json"

# Recent projects storage (in user home)
RECENTS_FILE = Path.home() / ".xeditor" / "video_editor_recents.json"


class VideoProjectManager:
    """
    Manages video projects stored in user-selected folders.
    """

    def __init__(self):
        self._open_projects: Dict[str, VideoProject] = {}
        self._ensure_recents_dir()

    def _ensure_recents_dir(self) -> None:
        """Ensure the recents directory exists."""
        RECENTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _get_project_dir(self, root_path: Path) -> Path:
        """Get the project data directory within the user folder."""
        return root_path / PROJECT_DIR

    def _get_root_file(self, root_path: Path) -> Path:
        """Get the root project file path."""
        return root_path / ROOT_PROJECT_FILE

    def _get_state_file(self, root_path: Path) -> Path:
        """Get the full state file path."""
        return self._get_project_dir(root_path) / STATE_FILE

    def is_empty_folder(self, folder_path: str) -> bool:
        """Check if a folder is empty or doesn't exist."""
        path = Path(folder_path)
        if not path.exists():
            return True
        if not path.is_dir():
            return False
        # Allow existing xeditor project to be re-initialized
        entries = list(path.iterdir())
        if not entries:
            return True
        # Check if only xeditor files exist (allow re-open)
        non_xeditor = [e for e in entries if not e.name.startswith("xeditor.video")]
        return len(non_xeditor) == 0

    def has_project(self, folder_path: str) -> bool:
        """Check if a folder contains a video project."""
        path = Path(folder_path)
        root_file = self._get_root_file(path)
        return root_file.exists()

    def create_project(
        self,
        folder_path: str,
        name: str,
        settings: Optional[ProjectSettings] = None,
    ) -> CreateProjectResponse:
        """
        Create a new video project in the specified folder.
        
        Args:
            folder_path: User-selected folder path
            name: Project name
            settings: Optional project settings
            
        Returns:
            CreateProjectResponse with success status and project
        """
        try:
            root_path = Path(folder_path).resolve()
            
            # Validate folder
            if not root_path.parent.exists():
                return CreateProjectResponse(
                    success=False,
                    error=f"Parent directory does not exist: {root_path.parent}"
                )
            
            # Create folder if it doesn't exist
            root_path.mkdir(parents=True, exist_ok=True)
            
            # Check if not already a project
            if self.has_project(str(root_path)):
                # Try to open existing project instead
                return self.open_project(str(root_path))
            
            # Create project structure
            project_dir = self._get_project_dir(root_path)
            project_dir.mkdir(exist_ok=True)
            
            # Create subdirectories
            subdirs = [
                "assets/characters",
                "assets/props",
                "assets/voices",
                "assets/audio",
                "assets/video",
                "assets/videos",
                "assets/images",
                "assets/music",
                "assets/sfx",
                "assets/av",
                "story",
                "renders",
                "cache",
            ]
            for subdir in subdirs:
                (project_dir / subdir).mkdir(parents=True, exist_ok=True)
            
            # Create project model
            project = VideoProject(
                name=name,
                settings=settings or ProjectSettings(),
                root_path=str(root_path),
            )
            
            # Write root project file (minimal, just for opening)
            root_file = self._get_root_file(root_path)
            root_data = {
                "id": project.id,
                "name": project.name,
                "version": project.version,
                "created_at": project.created_at,
            }
            self._write_json(root_file, root_data)
            
            # Write full state
            self._save_project_state(project)
            
            # Track as open
            self._open_projects[project.id] = project
            
            # Add to recents
            self._add_to_recents(project)
            
            return CreateProjectResponse(success=True, project=project)
            
        except Exception as e:
            return CreateProjectResponse(success=False, error=str(e))

    def open_project(self, folder_path: str) -> OpenProjectResponse:
        """
        Open an existing video project from a folder.
        
        Args:
            folder_path: Path to folder containing xeditor.video.project.json
            
        Returns:
            OpenProjectResponse with success status and project
        """
        try:
            root_path = Path(folder_path).resolve()
            
            # Check if project exists
            if not self.has_project(str(root_path)):
                return OpenProjectResponse(
                    success=False,
                    error=f"No video project found in: {folder_path}"
                )
            
            # Load state
            state_file = self._get_state_file(root_path)
            if not state_file.exists():
                # Try to recover from root file
                root_file = self._get_root_file(root_path)
                root_data = self._read_json(root_file)
                
                # Create minimal project from root data
                project = VideoProject(
                    id=root_data.get("id"),
                    name=root_data.get("name", "Untitled"),
                    version=root_data.get("version", "1.0.0"),
                    created_at=root_data.get("created_at", datetime.now().timestamp()),
                    root_path=str(root_path),
                )
                
                # Save full state for next time
                self._save_project_state(project)
            else:
                # Load full state
                state_data = self._read_json(state_file)
                project = VideoProject.model_validate(state_data)
                project.root_path = str(root_path)
            
            # Track as open
            self._open_projects[project.id] = project
            
            # Add to recents
            self._add_to_recents(project)
            
            return OpenProjectResponse(success=True, project=project)
            
        except Exception as e:
            return OpenProjectResponse(success=False, error=str(e))

    def save_project(self, project_id: str) -> SaveProjectResponse:
        """
        Save the current state of a project.
        
        Args:
            project_id: ID of the project to save
            
        Returns:
            SaveProjectResponse with success status
        """
        try:
            project = self._open_projects.get(project_id)
            if not project:
                return SaveProjectResponse(success=False, error="Project not open")
            
            if not project.root_path:
                return SaveProjectResponse(success=False, error="Project has no root path")
            
            project.update_timestamp()
            self._save_project_state(project)
            
            return SaveProjectResponse(success=True)
            
        except Exception as e:
            return SaveProjectResponse(success=False, error=str(e))

    def close_project(self, project_id: str) -> bool:
        """
        Close a project (save and remove from open list).
        
        Args:
            project_id: ID of the project to close
            
        Returns:
            True if successful
        """
        project = self._open_projects.pop(project_id, None)
        if project and project.root_path:
            try:
                project.update_timestamp()
                self._save_project_state(project)
            except Exception:
                pass
        return True

    def get_project(self, project_id: str) -> Optional[VideoProject]:
        """Get an open project by ID."""
        return self._open_projects.get(project_id)

    def list_open_projects(self) -> List[VideoProject]:
        """List all currently open projects."""
        return list(self._open_projects.values())

    def list_recent_projects(self) -> List[Dict[str, Any]]:
        """List recently opened projects."""
        try:
            if not RECENTS_FILE.exists():
                return []
            data = self._read_json(RECENTS_FILE)
            recents = data.get("recents", [])
            
            # Filter out non-existent projects
            valid_recents = []
            for recent in recents:
                path = recent.get("path")
                if path and self.has_project(path):
                    valid_recents.append(recent)
            
            return valid_recents[:20]  # Limit to 20 recent projects
            
        except Exception:
            return []

    def _save_project_state(self, project: VideoProject) -> None:
        """Save complete project state to disk."""
        if not project.root_path:
            raise ValueError("Project has no root path")
        
        root_path = Path(project.root_path)
        
        # Ensure directories exist
        project_dir = self._get_project_dir(root_path)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "story").mkdir(exist_ok=True)
        
        # Save main state (excluding story for separate file)
        state_file = self._get_state_file(root_path)
        state_data = project.model_dump()
        self._write_json(state_file, state_data)
        
        # Also update root file
        root_file = self._get_root_file(root_path)
        root_data = {
            "id": project.id,
            "name": project.name,
            "version": project.version,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        self._write_json(root_file, root_data)

    def _add_to_recents(self, project: VideoProject) -> None:
        """Add a project to the recents list."""
        try:
            recents = []
            if RECENTS_FILE.exists():
                data = self._read_json(RECENTS_FILE)
                recents = data.get("recents", [])
            
            # Remove if already exists
            recents = [r for r in recents if r.get("id") != project.id]
            
            # Add to front
            recents.insert(0, {
                "id": project.id,
                "name": project.name,
                "path": project.root_path,
                "opened_at": datetime.now().timestamp(),
            })
            
            # Limit to 20
            recents = recents[:20]
            
            self._write_json(RECENTS_FILE, {"recents": recents})
            
        except Exception:
            pass  # Don't fail if recents can't be saved

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        """Read a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: Path, data: Dict[str, Any]) -> None:
        """Write a JSON file atomically."""
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(path)

    def update_project_settings(
        self,
        project_id: str,
        settings: ProjectSettings
    ) -> Optional[VideoProject]:
        """Update project settings."""
        project = self._open_projects.get(project_id)
        if not project:
            return None
        
        project.settings = settings
        project.update_timestamp()
        self._save_project_state(project)
        return project

    def update_library(
        self,
        project_id: str,
        library: AssetLibrary
    ) -> Optional[VideoProject]:
        """Update project asset library."""
        project = self._open_projects.get(project_id)
        if not project:
            return None
        
        project.library = library
        project.update_timestamp()
        self._save_project_state(project)
        return project

    def update_story(
        self,
        project_id: str,
        story: Story
    ) -> Optional[VideoProject]:
        """Update project story."""
        project = self._open_projects.get(project_id)
        if not project:
            return None
        
        project.story = story
        project.story.updated_at = datetime.now().timestamp()
        project.update_timestamp()
        self._save_project_state(project)
        return project

    def update_timeline(
        self,
        project_id: str,
        timeline: Timeline
    ) -> Optional[VideoProject]:
        """Update project timeline."""
        project = self._open_projects.get(project_id)
        if not project:
            return None
        
        project.timeline = timeline
        project.timeline.recompute_duration()
        project.update_timestamp()
        self._save_project_state(project)
        return project

    def get_asset_path(self, project_id: str, asset_type: str, filename: str) -> Optional[str]:
        """Get the full path for an asset file."""
        project = self._open_projects.get(project_id)
        if not project or not project.root_path:
            return None
        
        root_path = Path(project.root_path)
        asset_dir = self._get_project_dir(root_path) / "assets" / asset_type
        asset_dir.mkdir(parents=True, exist_ok=True)
        return str(asset_dir / filename)

    def put_project_state(
        self,
        project_id: str,
        project_data: Dict[str, Any]
    ) -> Optional[VideoProject]:
        """
        Replace the entire project state with client-provided data.
        
        Preserves root_path from the server-side open project (never trust client paths).
        This is the main method for autosave functionality.
        
        Args:
            project_id: ID of the project to update
            project_data: Full project data from client
            
        Returns:
            Updated VideoProject or None if project not open
        """
        existing = self._open_projects.get(project_id)
        if not existing:
            return None
        
        # Preserve critical server-side fields
        preserved_root_path = existing.root_path
        preserved_id = existing.id
        
        try:
            # Validate and create new project from client data
            new_project = VideoProject.model_validate(project_data)
            
            # Override with preserved values (never trust client for these)
            new_project.id = preserved_id
            new_project.root_path = preserved_root_path
            new_project.update_timestamp()
            
            # Replace in open projects
            self._open_projects[project_id] = new_project
            
            # Persist to disk
            self._save_project_state(new_project)
            
            return new_project
            
        except Exception as e:
            print(f"[VideoProjectManager] Error validating project state: {e}")
            return None


# Singleton instance
_project_manager: Optional[VideoProjectManager] = None


def get_video_project_manager() -> VideoProjectManager:
    """Get the singleton VideoProjectManager instance."""
    global _project_manager
    if _project_manager is None:
        _project_manager = VideoProjectManager()
    return _project_manager


def get_open_project(project_id: str) -> Optional[VideoProject]:
    """Convenience function to get an open project by ID."""
    manager = get_video_project_manager()
    return manager.get_project(project_id)


# ─────────────────────────────────────────────────────────────────────────────
# RPC Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def handle_ve_create_project(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for creating a new video project."""
    manager = get_video_project_manager()
    
    folder_path = payload.get("folderPath", "")
    name = payload.get("name", "Untitled Project")
    settings_data = payload.get("settings")
    
    if not folder_path:
        return {"success": False, "error": "Folder path is required"}
    
    settings = None
    if settings_data:
        settings = ProjectSettings.model_validate(settings_data)
    
    response = manager.create_project(folder_path, name, settings)
    
    if response.success and response.project:
        return {
            "success": True,
            "project": response.project.model_dump(),
        }
    return {"success": False, "error": response.error}


async def handle_ve_open_project(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for opening an existing video project."""
    manager = get_video_project_manager()
    
    folder_path = payload.get("folderPath", "")
    
    if not folder_path:
        return {"success": False, "error": "Folder path is required"}
    
    response = manager.open_project(folder_path)
    
    if response.success and response.project:
        return {
            "success": True,
            "project": response.project.model_dump(),
        }
    return {"success": False, "error": response.error}


async def handle_ve_save_project(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for saving a video project."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    
    response = manager.save_project(project_id)
    return {"success": response.success, "error": response.error}


async def handle_ve_close_project(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for closing a video project."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    
    manager.close_project(project_id)
    return {"success": True}


async def handle_ve_get_project(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for getting an open project."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    
    project = manager.get_project(project_id)
    if project:
        return {
            "success": True,
            "project": project.model_dump(),
        }
    return {"success": False, "error": "Project not found"}


async def handle_ve_list_recent_projects(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """RPC handler for listing recent video projects."""
    manager = get_video_project_manager()
    recents = manager.list_recent_projects()
    return {"success": True, "recents": recents}


async def handle_ve_check_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for checking if a folder is valid for a new project."""
    manager = get_video_project_manager()
    
    folder_path = payload.get("folderPath", "")
    
    if not folder_path:
        return {"success": False, "error": "Folder path is required"}
    
    is_empty = manager.is_empty_folder(folder_path)
    has_project = manager.has_project(folder_path)
    
    return {
        "success": True,
        "isEmpty": is_empty,
        "hasProject": has_project,
    }


async def handle_ve_update_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for updating project settings."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    settings_data = payload.get("settings")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    if not settings_data:
        return {"success": False, "error": "Settings are required"}
    
    settings = ProjectSettings.model_validate(settings_data)
    project = manager.update_project_settings(project_id, settings)
    
    if project:
        return {"success": True, "project": project.model_dump()}
    return {"success": False, "error": "Project not found"}


async def handle_ve_update_library(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for updating project asset library."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    library_data = payload.get("library")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    if not library_data:
        return {"success": False, "error": "Library data is required"}
    
    library = AssetLibrary.model_validate(library_data)
    project = manager.update_library(project_id, library)
    
    if project:
        return {"success": True, "project": project.model_dump()}
    return {"success": False, "error": "Project not found"}


async def handle_ve_update_story(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for updating project story."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    story_data = payload.get("story")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    if not story_data:
        return {"success": False, "error": "Story data is required"}
    
    story = Story.model_validate(story_data)
    project = manager.update_story(project_id, story)
    
    if project:
        return {"success": True, "project": project.model_dump()}
    return {"success": False, "error": "Project not found"}


async def handle_ve_update_timeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for updating project timeline."""
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    timeline_data = payload.get("timeline")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    if not timeline_data:
        return {"success": False, "error": "Timeline data is required"}
    
    timeline = Timeline.model_validate(timeline_data)
    project = manager.update_timeline(project_id, timeline)
    
    if project:
        return {"success": True, "project": project.model_dump()}
    return {"success": False, "error": "Project not found"}


async def handle_ve_put_project_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    RPC handler for replacing entire project state (autosave).
    
    This is the primary endpoint for the client's debounced autosave.
    It accepts the full project state and persists it to disk.
    """
    manager = get_video_project_manager()
    
    project_id = payload.get("projectId", "")
    project_data = payload.get("project")
    
    if not project_id:
        return {"success": False, "error": "Project ID is required"}
    if not project_data:
        return {"success": False, "error": "Project data is required"}
    
    project = manager.put_project_state(project_id, project_data)
    
    if project:
        return {"success": True, "project": project.model_dump()}
    return {"success": False, "error": "Project not found or validation failed"}
