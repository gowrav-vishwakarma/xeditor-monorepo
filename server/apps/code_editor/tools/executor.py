"""
Tool Executor for XEditor Local Companion.
Handles execution of AI agent tools like read_file, write_file, search_code, etc.
"""

import errno
import os
import re
import ssl
import subprocess
import asyncio
import hashlib
import sys
import shutil
import urllib.request
import zipfile
import tarfile
import platform as platform_module
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime

from apps.code_editor.filesystem import get_xeditor_data_path
from apps.code_editor.indexing_builder import handle_retrieve_chunks
from apps.code_editor.project import get_project_manager, sanitize_project_name
from apps.code_editor.file_events import (
    add_file_change_listener,
    remove_file_change_listener,
    notify_file_changed,
)

# Track approved commands (by hash)
_approved_commands: set[str] = set()

# Store pending commands awaiting confirmation: hash -> {command, args, cwd, timeout, project_id, chat_id}
_pending_commands: Dict[str, Dict[str, Any]] = {}

# Cached resolved rg path to avoid re-validation on every search
_rg_binary_cache: Optional[str] = None


def _get_ripgrep_platform_info() -> tuple[str, str, str]:
    """
    Get ripgrep download info for current platform.
    
    Returns:
        Tuple of (platform_name, archive_extension, binary_name)
    """
    if sys.platform.startswith("linux"):
        # Check architecture
        machine = platform_module.machine().lower()
        if machine in ("x86_64", "amd64"):
            return ("x86_64-unknown-linux-musl", "tar.gz", "rg")
        elif machine in ("aarch64", "arm64"):
            return ("aarch64-unknown-linux-gnu", "tar.gz", "rg")
        elif machine.startswith("arm"):
            return ("arm-unknown-linux-gnueabihf", "tar.gz", "rg")
        else:
            # Default to x86_64
            return ("x86_64-unknown-linux-musl", "tar.gz", "rg")
    elif sys.platform == "darwin":
        machine = platform_module.machine().lower()
        if machine == "arm64":
            return ("aarch64-apple-darwin", "tar.gz", "rg")
        else:
            return ("x86_64-apple-darwin", "tar.gz", "rg")
    elif os.name == "nt":
        machine = platform_module.machine().lower()
        if machine == "arm64":
            return ("aarch64-pc-windows-msvc", "zip", "rg.exe")
        else:
            return ("x86_64-pc-windows-msvc", "zip", "rg.exe")
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _validate_rg_binary(path: str) -> bool:
    """
    Verify that the ripgrep binary at path is executable on this system.
    Returns False if file missing, not executable, wrong arch (ENOEXEC), or --version fails.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False
    if sys.platform != "win32" and not os.access(p, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(p), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except OSError as e:
        if getattr(e, "errno", None) == errno.ENOEXEC:
            return False  # Wrong architecture
        raise
    except subprocess.TimeoutExpired:
        return False


def _get_rg_cache_dir() -> Path:
    """Return ~/.xeditor/bin/ for cached ripgrep binary (no sudo needed)."""
    cache_dir = Path(get_xeditor_data_path()) / "bin"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works in Nuitka standalone builds."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


def _download_url(url: str, dest: Path) -> None:
    """Download a URL to a file, handling SSL and redirects."""
    ctx = _build_ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "XEditor/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def _download_rg_to_cache() -> Optional[str]:
    """
    Download ripgrep binary for current runtime platform into ~/.xeditor/bin/.
    Returns path to rg if successful and validated, None otherwise.
    """
    ripgrep_version = "15.1.0"
    platform_name, archive_ext, binary_name = _get_ripgrep_platform_info()
    archive_name = f"ripgrep-{ripgrep_version}-{platform_name}.{archive_ext}"
    url = f"https://github.com/BurntSushi/ripgrep/releases/download/{ripgrep_version}/{archive_name}"

    cache_dir = _get_rg_cache_dir()
    binary_path = cache_dir / binary_name
    archive_path = cache_dir / archive_name

    print(f"[rg] Downloading ripgrep {ripgrep_version} for {platform_name}...")
    print(f"[rg] URL: {url}")
    print(f"[rg] Target: {cache_dir}")

    try:
        _download_url(url, archive_path)
        print(f"[rg] Downloaded {archive_name}")

        if archive_ext == "zip":
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                for member in zip_ref.namelist():
                    if member.endswith(binary_name) and not member.endswith("/"):
                        zip_ref.extract(member, cache_dir)
                        extracted = cache_dir / member
                        if extracted.exists() and extracted != binary_path:
                            if binary_path.exists():
                                binary_path.unlink()
                            extracted.rename(binary_path)
                        else:
                            for nested in cache_dir.rglob(binary_name):
                                if nested.is_file() and nested != binary_path:
                                    if binary_path.exists():
                                        binary_path.unlink()
                                    nested.rename(binary_path)
                                    break
                        break
        else:
            with tarfile.open(archive_path, "r:gz") as tar_ref:
                for member in tar_ref.getmembers():
                    if member.name.endswith(binary_name) and member.isfile():
                        tar_ref.extract(member, cache_dir)
                        extracted = cache_dir / member.name
                        if extracted.exists() and extracted != binary_path:
                            if binary_path.exists():
                                binary_path.unlink()
                            extracted.rename(binary_path)
                        else:
                            for nested in cache_dir.rglob(binary_name):
                                if nested.is_file() and nested != binary_path:
                                    if binary_path.exists():
                                        binary_path.unlink()
                                    nested.rename(binary_path)
                                    break
                        break

        archive_path.unlink(missing_ok=True)
        for d in cache_dir.iterdir():
            if d.is_dir() and d.name.startswith("ripgrep-"):
                shutil.rmtree(d, ignore_errors=True)
        if sys.platform != "win32":
            os.chmod(binary_path, 0o755)

        if _validate_rg_binary(str(binary_path)):
            print(f"[rg] Successfully installed ripgrep to {binary_path}")
            return str(binary_path)

        print(f"[rg] Downloaded binary failed validation, removing")
        binary_path.unlink(missing_ok=True)
        return None
    except Exception as e:
        print(f"[rg] Failed to download ripgrep: {e}")
        archive_path.unlink(missing_ok=True)
        binary_path.unlink(missing_ok=True)
        return None


def _is_dev_mode() -> bool:
    """
    Check if running in development mode (not bundled executable).
    
    Returns:
        True if running in dev mode, False otherwise
    """
    try:
        # Check if running from source: server/bin directory should exist and be writable
        server_dir = Path(__file__).resolve().parent.parent
        dev_bin_dir = server_dir / "bin"
        
        # If bin directory exists and is writable, we're likely in dev mode
        if dev_bin_dir.exists():
            # Check if we can write to it (or if it's writable)
            try:
                test_file = dev_bin_dir / ".test_write"
                test_file.touch()
                test_file.unlink()
                return True
            except (OSError, PermissionError):
                pass
        
        # Also check if sys.argv[0] points to a Python script (not bundled executable)
        exe_path = Path(sys.argv[0]).resolve()
        if exe_path.suffix in (".py", "") and "python" in sys.executable.lower():
            return True
            
    except (OSError, ValueError):
        pass
    
    return False


def _download_ripgrep_for_dev() -> Optional[str]:
    """
    Download ripgrep binary for development use to server/bin/ directory.
    
    Returns:
        Path to downloaded rg binary if successful, None otherwise.
    """
    try:
        server_dir = Path(__file__).resolve().parent.parent
        dev_bin_dir = server_dir / "bin"
        dev_bin_dir.mkdir(parents=True, exist_ok=True)
        
        ripgrep_version = "15.1.0"  # Latest stable version
        platform_name, archive_ext, binary_name = _get_ripgrep_platform_info()
        
        archive_name = f"ripgrep-{ripgrep_version}-{platform_name}.{archive_ext}"
        url = f"https://github.com/BurntSushi/ripgrep/releases/download/{ripgrep_version}/{archive_name}"
        
        binary_path = dev_bin_dir / binary_name
        
        # Skip download if binary already exists
        if binary_path.exists():
            return str(binary_path)
        
        print(f"[dev] Downloading ripgrep {ripgrep_version} for {platform_name}...")
        print(f"[dev] URL: {url}")
        
        # Download archive to a temporary location
        archive_path = dev_bin_dir / archive_name
        
        try:
            # Download archive
            urllib.request.urlretrieve(url, archive_path)
            print(f"[dev] Downloaded {archive_name}")
            
            # Extract archive
            if archive_ext == "zip":
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    # Find the binary in the archive (usually in a subdirectory)
                    for member in zip_ref.namelist():
                        if member.endswith(binary_name) and not member.endswith("/"):
                            # Extract the binary
                            zip_ref.extract(member, dev_bin_dir)
                            # Move to expected location (handle nested paths)
                            extracted_path = dev_bin_dir / member
                            if extracted_path.exists() and extracted_path != binary_path:
                                extracted_path.rename(binary_path)
                            else:
                                # Search for extracted binary in subdirectories
                                for nested in dev_bin_dir.rglob(binary_name):
                                    if nested.is_file() and nested != binary_path:
                                        nested.rename(binary_path)
                                        break
                            break
            else:  # tar.gz
                with tarfile.open(archive_path, "r:gz") as tar_ref:
                    # Find the binary in the archive
                    for member in tar_ref.getmembers():
                        if member.name.endswith(binary_name) and member.isfile():
                            # Extract the binary
                            tar_ref.extract(member, dev_bin_dir)
                            # Move to expected location (handle nested paths)
                            extracted_path = dev_bin_dir / member.name
                            if extracted_path.exists() and extracted_path != binary_path:
                                extracted_path.rename(binary_path)
                            else:
                                # Search for extracted binary in subdirectories
                                for nested in dev_bin_dir.rglob(binary_name):
                                    if nested.is_file() and nested != binary_path:
                                        nested.rename(binary_path)
                                        break
                            break
            
            # Make executable on Unix-like systems
            if sys.platform != "win32":
                os.chmod(binary_path, 0o755)
            
            # Clean up archive
            archive_path.unlink()
            
            # Clean up any extracted directories
            for nested_dir in dev_bin_dir.iterdir():
                if nested_dir.is_dir() and nested_dir.name.startswith("ripgrep-"):
                    shutil.rmtree(nested_dir, ignore_errors=True)
            
            print(f"[dev] Successfully downloaded ripgrep to {binary_path}")
            return str(binary_path)
            
        except Exception as e:
            # Clean up archive on error
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)
            raise e
            
    except Exception as e:
        print(f"[dev] Warning: Failed to download ripgrep: {e}")
        return None


def _find_ripgrep_binary(auto_download: bool = False) -> Optional[str]:
    """
    Find ripgrep binary. Resolution order differs by mode:
    - Production: bundled (validated) -> cache (~/.xeditor/bin) -> download to cache -> None
    - Development: bundled -> server/bin -> PATH -> download to server/bin -> None (caller may fallback)
    """
    global _rg_binary_cache
    if _rg_binary_cache is not None and Path(_rg_binary_cache).exists():
        return _rg_binary_cache

    def _set_cache(path: str) -> str:
        global _rg_binary_cache
        _rg_binary_cache = path
        return path

    rg_name = "rg.exe" if sys.platform == "win32" else "rg"

    # Bundled rg (next to executable)
    try:
        exe_dir = Path(sys.argv[0]).resolve().parent
        bundled_rg = exe_dir / rg_name
        if bundled_rg.exists() and bundled_rg.is_file():
            if _validate_rg_binary(str(bundled_rg)):
                return _set_cache(str(bundled_rg))
            print(f"[rg] Bundled rg at {bundled_rg} failed validation (wrong arch?), skipping")
    except (OSError, ValueError):
        pass

    if _is_dev_mode():
        # Dev: server/bin
        try:
            server_dir = Path(__file__).resolve().parent.parent.parent.parent
            dev_rg = server_dir / "bin" / rg_name
            if dev_rg.exists() and dev_rg.is_file() and _validate_rg_binary(str(dev_rg)):
                return _set_cache(str(dev_rg))
        except (OSError, ValueError):
            pass
        # Dev: system PATH
        rg_path = shutil.which("rg")
        if rg_path and _validate_rg_binary(rg_path):
            return _set_cache(rg_path)
        # Dev: auto-download to server/bin
        if auto_download:
            downloaded = _download_ripgrep_for_dev()
            if downloaded and _validate_rg_binary(downloaded):
                return _set_cache(downloaded)
    else:
        # Production: check cache (~/.xeditor/bin)
        cached_rg = _get_rg_cache_dir() / rg_name
        if cached_rg.exists() and cached_rg.is_file() and _validate_rg_binary(str(cached_rg)):
            return _set_cache(str(cached_rg))
        # Production: system rg — check both PATH and common install locations
        # AppImage may isolate PATH, so also probe standard locations directly
        system_candidates: list[str] = []
        rg_from_path = shutil.which("rg")
        if rg_from_path:
            system_candidates.append(rg_from_path)
        if sys.platform != "win32":
            for loc in ("/usr/bin/rg", "/usr/local/bin/rg", "/snap/bin/rg"):
                if loc not in system_candidates:
                    system_candidates.append(loc)
        for candidate in system_candidates:
            if Path(candidate).exists() and _validate_rg_binary(candidate):
                print(f"[rg] Using system ripgrep: {candidate}")
                return _set_cache(candidate)
        # Production: auto-download to cache
        if auto_download:
            print("[rg] No valid ripgrep found, attempting auto-download...")
            downloaded = _download_rg_to_cache()
            if downloaded:
                return _set_cache(downloaded)

    return None


def ensure_ripgrep_available() -> bool:
    """
    Ensure ripgrep is available for use, downloading it automatically in dev mode if needed.
    
    Returns:
        True if ripgrep is available (either found or downloaded), False otherwise.
    """
    # Check if ripgrep is already available
    rg_binary = _find_ripgrep_binary(auto_download=False)
    if rg_binary:
        return True
    
    # If not found and we're in dev mode, try to download it
    if _is_dev_mode():
        print("[dev] Ripgrep not found. Downloading to server/bin/ for better code search performance...")
        downloaded_path = _find_ripgrep_binary(auto_download=True)
        if downloaded_path:
            print(f"[dev] Successfully downloaded ripgrep to {downloaded_path}")
            return True
        else:
            print("[dev] Warning: Failed to download ripgrep. Using Python regex fallback.")
            print("[dev] Run 'npm run setup:rg' to install manually if needed.")
            return False
    else:
        # In production mode, just return False (will use Python regex fallback)
        return False


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None


# Default read_file settings (used when not configured in PromptSet)
DEFAULT_READ_FILE_SETTINGS = {
    "thresholdChars": 50000,  # Start chunking above this
    "maxChars": 100000,       # Hard cap on total chars returned
    "maxLines": 2000,         # Hard cap on total lines returned
    "headLines": 100,         # Lines to show from head
    "middleLines": 50,        # Lines to show from middle
    "tailLines": 100,         # Lines to show from tail
}


def chunk_content_head_middle_tail(
    lines: List[str],
    head_lines: int,
    middle_lines: int,
    tail_lines: int,
) -> str:
    """
    Chunk content into head, middle, and tail sections with truncation markers.
    
    Args:
        lines: List of lines from the file
        head_lines: Number of lines to include from the start
        middle_lines: Number of lines to include from the middle
        tail_lines: Number of lines to include from the end
    
    Returns:
        Chunked content string with truncation markers
    """
    total_lines = len(lines)
    
    # Calculate middle position
    middle_start = (total_lines - middle_lines) // 2
    middle_end = middle_start + middle_lines
    
    # Build chunked content
    head = lines[:head_lines]
    middle = lines[middle_start:middle_end] if middle_lines > 0 else []
    tail = lines[-tail_lines:] if tail_lines > 0 else []
    
    # Calculate what's being skipped
    head_skip_end = head_lines
    middle_skip_start = middle_start
    tail_skip_start = total_lines - tail_lines
    
    chunks = []
    
    # Add head
    chunks.append("".join(head))
    
    # Add marker between head and middle (if there's a gap)
    if head_lines < middle_start:
        skipped = middle_start - head_lines
        chunks.append(f"\n... [{skipped} lines truncated] ...\n")
    
    # Add middle (if present and not overlapping with head)
    if middle_lines > 0 and middle_start > head_lines:
        chunks.append("".join(middle))
        
        # Add marker between middle and tail (if there's a gap)
        if middle_end < tail_skip_start:
            skipped = tail_skip_start - middle_end
            chunks.append(f"\n... [{skipped} lines truncated] ...\n")
    elif head_lines < tail_skip_start:
        # No middle, but there's a gap between head and tail
        skipped = tail_skip_start - head_lines
        chunks.append(f"\n... [{skipped} lines truncated] ...\n")
    
    # Add tail (if not overlapping with previous content)
    if tail_lines > 0:
        # Only add tail if it doesn't overlap with head or middle
        tail_start_idx = total_lines - tail_lines
        if tail_start_idx > head_lines and (middle_lines == 0 or tail_start_idx > middle_end):
            chunks.append("".join(tail))
    
    return "".join(chunks)


class ToolExecutor:
    """
    Executes AI agent tools.
    """

    def __init__(self, project_root: Optional[str] = None, mode: Optional[str] = None, set_id: str = "default", family: Optional[str] = None, version: Optional[str] = None, project_id: Optional[str] = None):
        """
        Initialize the tool executor.
        
        Args:
            project_root: Base path for relative file operations
            mode: Current mode (agent, plan, ask, debug) - used to filter allowed tools
            set_id: Prompt set ID for tool filtering
            family: Model family for tool filtering
            version: Model version for tool filtering
            project_id: Project ID for sub-agent delegation
        """
        self.mode = mode
        self.set_id = set_id
        self.family = family
        self.version = version
        self.project_root = Path(project_root) if project_root else None
        self.project_id = project_id
        self._settings_cache: Optional[Dict[str, Any]] = None
    
    def get_mode_settings(self) -> Dict[str, Any]:
        """Get mode settings from the PromptSet's tools.json."""
        if self._settings_cache is not None:
            return self._settings_cache
        
        if not self.mode or not self.family:
            self._settings_cache = {}
            return self._settings_cache
        
        try:
            from apps.code_editor.sets.manager import get_set_manager
            set_manager = get_set_manager()
            set_obj = set_manager.get_set(self.set_id)
            if set_obj:
                self._settings_cache = set_obj.read_mode_settings(
                    self.family, self.mode, self.version
                )
            else:
                self._settings_cache = {}
        except Exception:
            self._settings_cache = {}
        
        return self._settings_cache
    
    def get_read_file_settings(self) -> Dict[str, Any]:
        """Get read_file specific settings, merged with defaults."""
        mode_settings = self.get_mode_settings()
        read_file_settings = mode_settings.get("read_file", {})
        
        # Merge with defaults
        result = DEFAULT_READ_FILE_SETTINGS.copy()
        result.update(read_file_settings)
        return result

    def resolve_path(self, path: str) -> Path:
        """Resolve a path, handling relative paths if project_root is set."""
        p = Path(path)
        
        # If path is absolute but starts with project_root, convert to relative
        if p.is_absolute() and self.project_root:
            try:
                # Try to get relative path from apps.code_editor.project_root
                relative = p.relative_to(self.project_root)
                # Use the relative path instead
                result = self.project_root / relative
            except ValueError:
                # Path is absolute but not under project_root, use as-is
                result = p
        elif p.is_absolute():
            # Absolute path but no project_root set, use as-is
            result = p
        elif self.project_root:
            # Relative path with project_root set, join them
            result = self.project_root / path
        else:
            # Relative path but no project_root, make absolute from cwd
            result = p.absolute()
        
        return result

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        tool_call_id: Optional[str] = None,
        model_config: Optional[Dict[str, Any]] = None,
        original_on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> ToolResult:
        """
        Execute a tool by name with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            args: Tool arguments
            on_event: Optional callback for streaming events (tool_chunk)
            tool_call_id: Optional tool call ID for event correlation
            model_config: Optional model config for tools that need LLM access (e.g., delegate_task)
        """
        # Strip meta-parameters that tools should never see (safety net; agent_runner also strips)
        args = {k: v for k, v in (args or {}).items() if k != "_context_updates"}
        
        # Check if tool is allowed for current mode
        if self.mode:
            from apps.code_editor.tools.registry import get_tool_registry
            tool_registry = get_tool_registry()
            if not tool_registry.is_tool_allowed(tool_name, self.mode, self.set_id, self.family, self.version):
                return ToolResult(
                    success=False,
                    error=f"Tool '{tool_name}' is not allowed in {self.mode} mode",
                )
        
        # Special handling for delegate_task (needs model_config and project_id)
        if tool_name == "delegate_task":
            return await self.delegate_task(args, on_event, tool_call_id, model_config, original_on_event)
        
        tool_map = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "search_code": lambda a: self.search_code(a, on_event, tool_call_id),
            "run_command": lambda a: self.run_command(a, on_event, tool_call_id),
            "create_file": self.create_file,
            "delete_file": self.delete_file,
            "delete_path": self.delete_path,
            "file_exists": self.file_exists,
            "git_read_file_at_ref": self.git_read_file_at_ref,
            "search_replace": self.search_replace,
            "semantic_search": self.semantic_search,
            "create_plan": self.create_plan,
            "ask_question": self.ask_question,
            "todo_write": self.todo_write,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        try:
            result = await handler(args)
            return result
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    async def read_file(self, args: Dict[str, Any]) -> ToolResult:
        """Read a file from disk with optional chunking for large files."""
        path = args.get("path", "")
        if not path:
            return ToolResult(success=False, error="Path is required")

        file_path = self.resolve_path(path)

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")

        if not file_path.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")

        try:
            # Get read_file settings
            settings = self.get_read_file_settings()
            threshold_chars = settings.get("thresholdChars", 50000)
            max_chars = settings.get("maxChars", 100000)
            max_lines = settings.get("maxLines", 2000)
            head_lines = settings.get("headLines", 100)
            middle_lines = settings.get("middleLines", 50)
            tail_lines = settings.get("tailLines", 100)
            
            # Handle optional offset and limit (explicit user request takes precedence)
            offset = args.get("offset", 0)
            limit = args.get("limit")
            
            # Read file
            file_size = file_path.stat().st_size
            
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            
            total_lines = len(all_lines)
            
            # If explicit offset/limit provided, honor that selection
            if offset or limit:
                if offset:
                    selected_lines = all_lines[offset:]
                else:
                    selected_lines = all_lines
                if limit:
                    selected_lines = selected_lines[:limit]
                content = "".join(selected_lines)
                truncated = False
                strategy = "explicit_range"
            else:
                # Apply chunking based on settings
                full_content = "".join(all_lines)
                
                # Check if content exceeds thresholds
                content_chars = len(full_content)
                needs_chunking = (
                    content_chars > threshold_chars or
                    total_lines > max_lines
                )
                
                if needs_chunking:
                    # Apply head/middle/tail chunking
                    content = chunk_content_head_middle_tail(
                        all_lines,
                        head_lines=head_lines,
                        middle_lines=middle_lines,
                        tail_lines=tail_lines,
                    )
                    truncated = True
                    strategy = "head_middle_tail"
                    
                    # Apply max_chars cap as a safety net
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n... [truncated at {max_chars} chars]"
                else:
                    content = full_content
                    truncated = False
                    strategy = "full"

            return ToolResult(
                success=True,
                result={
                    "content": content,
                    "path": str(file_path),
                    "sizeBytes": file_size,
                    "totalLines": total_lines,
                    "truncated": truncated,
                    "strategy": strategy,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def write_file(self, args: Dict[str, Any]) -> ToolResult:
        """Write content to a file."""
        path = args.get("path", "")
        content = args.get("content", "")

        if not path:
            return ToolResult(success=False, error="Path is required")

        file_path = self.resolve_path(path)

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if file exists (for change type)
            existed = file_path.exists()
            
            # Capture before content for diff (only if file exists and not too large)
            before_content = None
            if existed:
                try:
                    # Limit capture to reasonable size (1MB) to avoid memory issues
                    file_size = file_path.stat().st_size
                    if file_size <= 1024 * 1024:  # 1MB limit
                        before_content = file_path.read_text(encoding="utf-8")
                    else:
                        # For large files, we'll use git diff as fallback
                        before_content = None
                except Exception:
                    # If read fails, continue without before_content
                    before_content = None

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Notify listeners
            change_type = "modified" if existed else "created"
            await notify_file_changed(str(file_path), change_type)

            result = {
                "path": str(file_path),
                "bytesWritten": len(content.encode("utf-8")),
                "changeType": change_type,
            }
            
            # Include before/after content for diff if we captured it
            # For modified files: include both before and after content
            # For created files: include afterContent if content size is within limit
            if before_content is not None:
                result["beforeContent"] = before_content
                result["afterContent"] = content
            elif change_type == "created":
                # For created files, include afterContent if content is within 1MB limit
                content_size = len(content.encode("utf-8"))
                if content_size <= 1024 * 1024:  # 1MB limit
                    result["afterContent"] = content
            
            return ToolResult(
                success=True,
                result=result,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def create_file(self, args: Dict[str, Any]) -> ToolResult:
        """Create a new file with optional content."""
        return await self.write_file(args)

    async def delete_file(self, args: Dict[str, Any]) -> ToolResult:
        """Delete a file."""
        path = args.get("path", "")
        if not path:
            return ToolResult(success=False, error="Path is required")

        file_path = self.resolve_path(path)

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")

        try:
            file_path.unlink()
            await notify_file_changed(str(file_path), "deleted")

            return ToolResult(
                success=True,
                result={"path": str(file_path), "deleted": True},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def delete_path(self, args: Dict[str, Any]) -> ToolResult:
        """
        Delete a file or directory.
        
        Args:
            args: Dictionary containing:
                - path: Path to file or directory
                - recursive: Boolean, required True for directories
        """
        path = args.get("path", "")
        recursive = args.get("recursive", False)
        
        if not path:
            return ToolResult(success=False, error="Path is required")

        target_path = self.resolve_path(path)

        if not target_path.exists():
            return ToolResult(success=False, error=f"Path not found: {path}")

        try:
            # Handle file deletion
            if target_path.is_file():
                target_path.unlink()
                await notify_file_changed(str(target_path), "deleted")
                return ToolResult(
                    success=True,
                    result={"path": str(target_path), "deleted": True},
                )
            
            # Handle directory deletion
            if target_path.is_dir():
                if not recursive:
                    return ToolResult(
                        success=False,
                        error="recursive=True is required to delete directories",
                    )
                
                # Walk directory and collect file paths for notification
                # Cap at 2000 files to avoid flooding with notifications
                MAX_NOTIFICATION_FILES = 2000
                deleted_files: List[str] = []
                
                def collect_files(dir_path: Path) -> None:
                    """Recursively collect file paths."""
                    if len(deleted_files) >= MAX_NOTIFICATION_FILES:
                        return
                    try:
                        for item in dir_path.iterdir():
                            if item.is_file():
                                if len(deleted_files) < MAX_NOTIFICATION_FILES:
                                    deleted_files.append(str(item))
                            elif item.is_dir():
                                collect_files(item)
                    except (PermissionError, OSError):
                        pass
                
                # Collect files before deletion
                collect_files(target_path)
                
                # Delete the directory
                shutil.rmtree(target_path)
                
                # Notify for each deleted file (up to cap)
                for file_path_str in deleted_files:
                    await notify_file_changed(file_path_str, "deleted")
                
                # If we hit the cap, signal that reindex is needed
                needs_reindex = len(deleted_files) >= MAX_NOTIFICATION_FILES
                
                return ToolResult(
                    success=True,
                    result={
                        "path": str(target_path),
                        "deleted": True,
                        "filesDeleted": len(deleted_files),
                        "needsReindex": needs_reindex,
                    },
                )
            
            return ToolResult(
                success=False,
                error=f"Path is neither a file nor a directory: {path}",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def file_exists(self, args: Dict[str, Any]) -> ToolResult:
        """Check if a file exists."""
        path = args.get("path", "")
        if not path:
            return ToolResult(success=False, error="Path is required")

        file_path = self.resolve_path(path)

        return ToolResult(
            success=True,
            result={
                "exists": file_path.exists(),
                "isFile": file_path.is_file() if file_path.exists() else False,
                "isDirectory": file_path.is_dir() if file_path.exists() else False,
            },
        )

    async def git_read_file_at_ref(self, args: Dict[str, Any]) -> ToolResult:
        """
        Read file content from git at a specific ref (e.g., HEAD).
        
        Args:
            args: Dictionary containing:
                - path: Absolute path to the file
                - ref: Git ref (default: "HEAD")
        """
        path = args.get("path", "")
        ref = args.get("ref", "HEAD")
        
        if not path:
            return ToolResult(success=False, error="Path is required")

        file_path = self.resolve_path(path)
        
        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")

        try:
            # Determine git repository root
            # Use the directory containing the file as starting point
            file_dir = file_path.parent
            
            # Find git root by running git rev-parse --show-toplevel
            git_root_result = subprocess.run(
                ["git", "-C", str(file_dir), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if git_root_result.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Not a git repository or git not available: {git_root_result.stderr}",
                )
            
            git_root = Path(git_root_result.stdout.strip())
            
            # Compute relative path from git root
            try:
                rel_path = file_path.relative_to(git_root)
            except ValueError:
                return ToolResult(
                    success=False,
                    error=f"File is not within git repository: {path}",
                )
            
            # Use forward slashes for git paths (git expects this)
            git_path = str(rel_path).replace("\\", "/")
            
            # Read file content from git
            git_show_result = subprocess.run(
                ["git", "-C", str(git_root), "show", f"{ref}:{git_path}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if git_show_result.returncode != 0:
                # File doesn't exist in this ref (might be untracked/new)
                return ToolResult(
                    success=True,
                    result={
                        "content": "",
                        "ref": ref,
                        "existsInRef": False,
                    },
                )
            
            return ToolResult(
                success=True,
                result={
                    "content": git_show_result.stdout,
                    "ref": ref,
                    "existsInRef": True,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="Git command timed out",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to read file from git: {str(e)}",
            )

    async def search_replace(self, args: Dict[str, Any]) -> ToolResult:
        """
        Perform exact string replacements in files.
        
        Args:
            args: Dictionary containing:
                - file_path or path: Path to the file to modify
                - old_string: The text to replace
                - new_string: The text to replace it with
                - replace_all: Optional boolean, if True replaces all occurrences (default False)
        """
        file_path_arg = args.get("path") or args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        replace_all = args.get("replace_all", False)

        if not file_path_arg:
            return ToolResult(success=False, error="file_path is required")
        
        if not old_string:
            return ToolResult(success=False, error="old_string is required")
        
        if old_string == new_string:
            return ToolResult(success=False, error="old_string and new_string must be different")

        file_path = self.resolve_path(file_path_arg)

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path_arg}")

        if not file_path.is_file():
            return ToolResult(success=False, error=f"Not a file: {file_path_arg}")

        try:
            # Read the file content
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Check if old_string exists in the file
            if old_string not in content:
                return ToolResult(
                    success=False,
                    error=f"old_string not found in file: {file_path_arg}",
                )

            # Count occurrences
            count = content.count(old_string)

            # If replace_all is False and there are multiple occurrences, fail
            if not replace_all and count > 1:
                return ToolResult(
                    success=False,
                    error=(
                        f"old_string appears {count} times in file. "
                        "Either provide more context to make it unique, "
                        "or set replace_all=True to replace all occurrences."
                    ),
                )

            # Perform replacement
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements_made = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements_made = 1

            # Capture before content for diff (only if file is not too large)
            before_content = None
            try:
                file_size = file_path.stat().st_size
                if file_size <= 1024 * 1024:  # 1MB limit
                    before_content = content
            except Exception:
                before_content = None

            # Write the modified content back
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Notify listeners
            await notify_file_changed(str(file_path), "modified")

            result = {
                "path": str(file_path),
                "replacementsMade": replacements_made,
                "totalOccurrences": count,
            }

            # Include before/after content for diff if we captured it
            if before_content is not None:
                result["beforeContent"] = before_content
                result["afterContent"] = new_content

            return ToolResult(
                success=True,
                result=result,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def list_dir(self, args: Dict[str, Any]) -> ToolResult:
        """List directory contents."""
        path = args.get("path", "")
        
        if not path:
            if self.project_root:
                path = str(self.project_root)
            else:
                return ToolResult(success=False, error="Path is required")

        dir_path = self.resolve_path(path)

        if not dir_path.exists():
            return ToolResult(success=False, error=f"Directory not found: {path}")

        if not dir_path.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path}")

        try:
            show_hidden = args.get("showHidden", False)
            entries = []

            for item in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                name = item.name

                if not show_hidden and name.startswith("."):
                    continue

                # Skip common ignored directories
                if name in ("node_modules", "__pycache__", ".git", "venv", ".venv"):
                    continue

                entries.append({
                    "name": name,
                    "path": str(item),
                    "isDirectory": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else None,
                })

            return ToolResult(
                success=True,
                result={
                    "path": str(dir_path),
                    "entries": entries,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def search_code(
        self,
        args: Dict[str, Any],
        on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> ToolResult:
        """Search for code using ripgrep with optional streaming progress."""
        query = args.get("query", "")
        search_path = args.get("path", "")

        if not query:
            return ToolResult(success=False, error="Query is required")

        if not search_path and self.project_root:
            search_path = str(self.project_root)
        elif not search_path:
            return ToolResult(success=False, error="Path is required")

        search_dir = self.resolve_path(search_path)

        # Find ripgrep binary (bundled -> cache -> download in prod; bundled -> bin -> PATH -> download in dev)
        rg_binary = _find_ripgrep_binary(auto_download=True)

        if not rg_binary:
            if _is_dev_mode():
                return await self._regex_search(query, search_dir)
            return ToolResult(
                success=False,
                error="Code search unavailable: ripgrep binary not found and could not be downloaded. "
                "Check internet connection or reinstall the application.",
            )

        try:
            # Use ripgrep for fast searching
            # Use --regexp to explicitly mark the query as a pattern,
            # preventing queries starting with -- from being interpreted as flags
            cmd = [
                rg_binary,
                "--json",
                "--max-count", "50",  # Limit matches per file
                "--max-filesize", "1M",  # Skip large files
                "--regexp", query,
                str(search_dir),
            ]

            # Add file type filters if specified
            file_type = args.get("type")
            if file_type:
                cmd.extend(["--type", file_type])

            # Add glob filters if specified
            glob = args.get("glob")
            if glob:
                cmd.extend(["--glob", glob])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            import json
            matches = []
            stdout_chunks = []
            
            # Stream output if callback provided
            if on_event and tool_call_id and process.stdout:
                # Read stdout line by line for streaming
                while True:
                    try:
                        line = await asyncio.wait_for(
                            process.stdout.readline(),
                            timeout=30,
                        )
                        if not line:
                            break
                        
                        decoded = line.decode("utf-8", errors="replace").strip()
                        stdout_chunks.append(decoded + "\n")
                        
                        # Parse JSON line and emit progress
                        if decoded:
                            try:
                                data = json.loads(decoded)
                                if data.get("type") == "match":
                                    match_data = data.get("data", {})
                                    path = match_data.get("path", {}).get("text", "")
                                    line_number = match_data.get("line_number")
                                    content = match_data.get("lines", {}).get("text", "").strip()
                                    
                                    match_info = {
                                        "path": path,
                                        "lineNumber": line_number,
                                        "content": content,
                                    }
                                    matches.append(match_info)
                                    
                                    # Emit progress chunk
                                    progress_msg = f"Found match in {path}:{line_number}\n"
                                    await on_event("tool_chunk", {
                                        "id": tool_call_id,
                                        "content": progress_msg,
                                    })
                            except json.JSONDecodeError:
                                # Skip non-JSON lines (like summary lines)
                                continue
                    except asyncio.TimeoutError:
                        # Continue reading even if a single line times out
                        break
                
                # Wait for process to complete
                try:
                    await asyncio.wait_for(process.wait(), timeout=30)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
                stdout = "".join(stdout_chunks)
                stderr = await process.stderr.read() if process.stderr else b""
                stderr = stderr.decode("utf-8", errors="replace")
            else:
                # Non-streaming mode (original behavior)
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
                stdout = stdout.decode("utf-8", errors="replace")
                stderr = stderr.decode("utf-8", errors="replace")
                
                # Parse JSON lines output
                for line in stdout.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") == "match":
                            match_data = data.get("data", {})
                            matches.append({
                                "path": match_data.get("path", {}).get("text", ""),
                                "lineNumber": match_data.get("line_number"),
                                "content": match_data.get("lines", {}).get("text", "").strip(),
                            })
                    except json.JSONDecodeError:
                        continue

            if process.returncode == 1:
                # No matches found
                return ToolResult(
                    success=True,
                    result={"matches": [], "message": "No matches found"},
                )

            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Search failed: {stderr}",
                )

            return ToolResult(
                success=True,
                result={
                    "query": query,
                    "matches": matches[:100],  # Limit total matches
                    "truncated": len(matches) > 100,
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(success=False, error="Search timed out")
        except FileNotFoundError:
            # ripgrep binary not found, fall back to Python regex search
            return await self._regex_search(query, search_dir)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _regex_search(self, query: str, search_dir: Path) -> ToolResult:
        """
        Python regex fallback search when ripgrep is not available.
        Uses Python's re module to support regex patterns like 'a|b|c'.
        """
        matches = []
        
        # Compile regex pattern (case-insensitive by default for better UX)
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            return ToolResult(
                success=False,
                error=f"Invalid regex pattern: {str(e)}",
            )
        
        # Common ignored directories and files
        ignored_dirs = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', '.pytest_cache', 'dist', 'build'}
        ignored_extensions = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib', '.exe', '.bin'}
        
        # Limit file size (1MB like ripgrep)
        max_file_size = 1024 * 1024
        
        for root, dirs, files in os.walk(search_dir):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith('.')]
            
            for file_name in files:
                # Skip binary files by extension
                if any(file_name.lower().endswith(ext) for ext in ignored_extensions):
                    continue
                
                file_path = Path(root) / file_name
                
                # Check file size
                try:
                    if file_path.stat().st_size > max_file_size:
                        continue
                except OSError:
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern.search(line):
                                matches.append({
                                    "path": str(file_path),
                                    "lineNumber": line_num,
                                    "content": line.strip()[:200],
                                })
                                if len(matches) >= 100:
                                    return ToolResult(
                                        success=True,
                                        result={
                                            "query": query,
                                            "matches": matches,
                                            "truncated": True,
                                            "message": "Using Python regex fallback (ripgrep not available)",
                                        },
                                    )
                except (OSError, UnicodeDecodeError):
                    # Skip files that can't be read or decoded
                    continue
        
        return ToolResult(
            success=True,
            result={
                "query": query,
                "matches": matches,
                "truncated": False,
                "message": "Using Python regex fallback (ripgrep not available)" if matches else None,
            },
        )

    async def semantic_search(self, args: Dict[str, Any]) -> ToolResult:
        """
        Perform semantic code search using vector embeddings.
        
        Uses the project's code index to find semantically similar code chunks
        based on natural language queries. Automatically resolves the project
        from the current project root path.
        """
        query = args.get("query", "")
        limit = args.get("limit", 10)
        folder_ids = args.get("folder_ids", [])
        embedding_model_id = args.get("embedding_model_id")
        hf_token = args.get("hf_token")
        
        if not query:
            return ToolResult(success=False, error="Query is required")
        
        # Always resolve project_id from current project_root
        if not self.project_root:
            return ToolResult(
                success=False,
                error="Project root is not available. Cannot perform semantic search."
            )
        
        project_manager = get_project_manager()
        resolved_project = project_manager.find_project_by_root(self.project_root)
        
        if not resolved_project:
            # Get list of known projects for error message
            known_projects = project_manager.list_projects()
            project_list = ", ".join([
                f"{p.get('name', p.get('id', 'unknown'))} (id: {p.get('id', 'unknown')})"
                for p in known_projects[:5]  # Limit to first 5
            ])
            root_str = str(self.project_root)
            error_msg = (
                f"No registered project matches root: {root_str}. "
                f"Known projects: {project_list if project_list else 'none'}. "
                f"Please connect this folder as a project in XEditor to enable semantic search."
            )
            return ToolResult(success=False, error=error_msg)
        
        project_id = resolved_project.get("id")
        
        try:
            payload = {
                "projectId": project_id,
                "query": query,
                "limit": limit,
            }
            
            if folder_ids:
                payload["folderIds"] = folder_ids
            
            if embedding_model_id:
                payload["embeddingModelId"] = embedding_model_id
            
            if hf_token:
                payload["hfToken"] = hf_token
            
            result = await handle_retrieve_chunks(payload)
            
            if result.get("success"):
                return ToolResult(
                    success=True,
                    result={
                        "query": query,
                        "results": result.get("results", []),
                        "count": len(result.get("results", [])),
                    },
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "Semantic search failed"),
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def run_command(
        self,
        args: Dict[str, Any],
        on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> ToolResult:
        """
        Run a shell command with optional streaming output.
        
        Requires user confirmation before execution. If not approved, returns
        a confirmation request. If approved, executes the command.
        
        Args:
            args: Command arguments (command, cwd, timeout)
            on_event: Optional callback for streaming tool_chunk events
            tool_call_id: Optional tool call ID for event correlation
        """
        command = args.get("command", "")
        if not command:
            return ToolResult(success=False, error="Command is required")

        # Security: Check for dangerous commands
        dangerous_patterns = [
            "rm -rf /",
            "rm -rf ~",
            "mkfs",
            "> /dev/sd",
            "dd if=",
            ":(){:|:&};:",  # Fork bomb
        ]

        for pattern in dangerous_patterns:
            if pattern in command:
                return ToolResult(
                    success=False,
                    error=f"Potentially dangerous command blocked: {pattern}",
                )

        # Calculate command hash for approval tracking
        command_hash = hashlib.md5(command.encode("utf-8")).hexdigest()
        
        # Check if command is already approved
        if command_hash not in _approved_commands:
            # Store pending command info for later execution
            _pending_commands[command_hash] = {
                "command": command,
                "args": args,
                "project_root": str(self.project_root) if self.project_root else None,
            }
            # Return confirmation request
            return ToolResult(
                success=True,
                result={
                    "action": "confirm_command",
                    "command": command,
                    "id": command_hash,
                    "message": "Command requires user confirmation before execution.",
                },
            )
        
        # Command is approved - remove from set and execute
        _approved_commands.discard(command_hash)

        cwd = args.get("cwd")
        if cwd:
            cwd = str(self.resolve_path(cwd))
        elif self.project_root:
            cwd = str(self.project_root)

        timeout = args.get("timeout", 30)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout for streaming
                cwd=cwd,
            )

            stdout_chunks = []
            stderr_chunks = []
            
            # Stream output if callback provided
            if on_event and tool_call_id:
                # Read stdout line by line
                if process.stdout:
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                process.stdout.readline(),
                                timeout=timeout,
                            )
                            if not line:
                                break
                            
                            decoded = line.decode("utf-8", errors="replace")
                            stdout_chunks.append(decoded)
                            
                            # Emit chunk event
                            await on_event("tool_chunk", {
                                "id": tool_call_id,
                                "content": decoded,
                            })
                        except asyncio.TimeoutError:
                            # Continue reading even if a single line times out
                            break
                
                # Read stderr separately (if not merged)
                if process.stderr and process.stderr != process.stdout:
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                process.stderr.readline(),
                                timeout=timeout,
                            )
                            if not line:
                                break
                            
                            decoded = line.decode("utf-8", errors="replace")
                            stderr_chunks.append(decoded)
                            
                            # Emit chunk event (prefixed to indicate stderr)
                            await on_event("tool_chunk", {
                                "id": tool_call_id,
                                "content": f"[stderr] {decoded}",
                            })
                        except asyncio.TimeoutError:
                            break
                
                # Wait for process to complete
                try:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
                stdout = "".join(stdout_chunks)
                stderr = "".join(stderr_chunks)
            else:
                # Non-streaming mode (original behavior)
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                stdout = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr = stderr.decode("utf-8", errors="replace") if stderr else ""

            return ToolResult(
                success=True,
                result={
                    "exitCode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def create_plan(self, args: Dict[str, Any]) -> ToolResult:
        """
        Create a plan file and save it to the project's plans directory.
        
        Storage location: ~/.xeditor/projects/{projectName}/plans/{plan_name}_{hash}.plan.md
        
        Args:
            args: Dictionary containing:
                - name: Short 3-4 word name for the plan
                - overview: 1-2 sentence summary
                - plan: Full markdown plan content
                - todos: Optional array of {id, content} todo items
        """
        name = args.get("name", "")
        overview = args.get("overview", "")
        plan_content = args.get("plan", "")
        todos = args.get("todos", [])
        
        if not name:
            return ToolResult(success=False, error="name is required")
        if not overview:
            return ToolResult(success=False, error="overview is required")
        if not plan_content:
            return ToolResult(success=False, error="plan content is required")
        
        # Generate filename from name
        # Convert to lowercase, replace spaces with underscores, remove special chars
        safe_name = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_').replace('-', '_'))
        
        # Generate short hash for uniqueness
        hash_input = f"{name}{overview}{datetime.now().isoformat()}"
        short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        
        filename = f"{safe_name}_{short_hash}.plan.md"
        
        # Get project name from apps.code_editor.project manager
        project_name = "default"
        project_safe_name = "default"
        if self.project_root:
            project_manager = get_project_manager()
            resolved_project = project_manager.find_project_by_root(self.project_root)
            if resolved_project:
                # Use project name instead of UUID for display
                project_name = resolved_project.get("name", resolved_project.get("id", "default"))
                # Use safeName for directory path if available, otherwise sanitize the name
                project_safe_name = resolved_project.get("safeName", sanitize_project_name(project_name))
        
        # Build plans directory path
        # ~/.xeditor/projects/{projectSafeName}/plans/
        xeditor_base = Path.home() / ".xeditor"
        plans_dir = xeditor_base / "projects" / project_safe_name / "plans"
        
        # Ensure directory exists
        plans_dir.mkdir(parents=True, exist_ok=True)
        
        plan_file_path = plans_dir / filename
        
        # Build the plan file content with frontmatter
        frontmatter_lines = [
            "---",
            f"name: {name}",
            f"overview: {overview}",
            f"created: {datetime.now().isoformat()}",
            f"project: {project_name}",
            f"plan_file_path: {str(plan_file_path.resolve())}",
            "status: pending",
        ]
        
        # Add todos to frontmatter if provided
        if todos:
            frontmatter_lines.append("todos:")
            for todo in todos:
                todo_id = todo.get("id", "")
                todo_content = todo.get("content", "")
                frontmatter_lines.append(f"  - id: {todo_id}")
                frontmatter_lines.append(f"    content: {todo_content}")
                frontmatter_lines.append(f"    status: pending")
        
        frontmatter_lines.append("---")
        frontmatter_lines.append("")
        
        # Combine frontmatter with plan content
        full_content = "\n".join(frontmatter_lines) + plan_content
        
        try:
            with open(plan_file_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            
            return ToolResult(
                success=True,
                result={
                    "plan_file_path": str(plan_file_path),
                    "filename": filename,
                    "project": project_name,
                    "action": "open_in_editor",  # Signal to frontend to open this file
                    "message": f"Plan saved to: {plan_file_path}",
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to save plan: {str(e)}",
            )

    async def ask_question(self, args: Dict[str, Any]) -> ToolResult:
        """
        Present structured questions to the user for clarification.
        
        The frontend will display these as a form and collect responses.
        The response is returned in the next user message.
        
        Args:
            args: Dictionary containing:
                - title: Optional title for the question form
                - questions: Array of question objects with id, prompt, options, allow_multiple
        """
        title = args.get("title", "")
        questions = args.get("questions", [])
        
        if not questions:
            return ToolResult(success=False, error="questions array is required")
        
        # Validate questions structure
        for i, q in enumerate(questions):
            if not q.get("id"):
                return ToolResult(success=False, error=f"Question {i} missing 'id'")
            if not q.get("prompt"):
                return ToolResult(success=False, error=f"Question {i} missing 'prompt'")
            if not q.get("options") or len(q.get("options", [])) < 2:
                return ToolResult(success=False, error=f"Question {i} must have at least 2 options")
            
            for j, opt in enumerate(q.get("options", [])):
                if not opt.get("id"):
                    return ToolResult(success=False, error=f"Question {i}, Option {j} missing 'id'")
                if not opt.get("label"):
                    return ToolResult(success=False, error=f"Question {i}, Option {j} missing 'label'")
        
        return ToolResult(
            success=True,
            result={
                "action": "ask_question",
                "title": title,
                "questions": questions,
                "message": "Questions presented to user. Awaiting response.",
            },
        )

    async def todo_write(self, args: Dict[str, Any]) -> ToolResult:
        """
        Update todos in a plan file's frontmatter.
        
        Updates the todos section in a .plan.md file created by create_plan.
        Can merge with existing todos or replace them entirely.
        
        Args:
            args: Dictionary containing:
                - plan_file_path or path: Path to the .plan.md file to update
                - todos: Array of todo items with id, content (optional), status
                - merge: Boolean, if True merges with existing todos by id, if False replaces all
        """
        plan_file_path_arg = args.get("plan_file_path") or args.get("path", "")
        todos = args.get("todos", [])
        merge = args.get("merge", True)
        
        if not plan_file_path_arg:
            return ToolResult(success=False, error="plan_file_path (or path) is required")
        
        if not todos:
            return ToolResult(success=False, error="todos array is required")
        
        # Validate todos structure
        for i, todo in enumerate(todos):
            if not todo.get("id"):
                return ToolResult(success=False, error=f"Todo {i} missing required 'id' field")
            status = todo.get("status", "pending")
            if status not in ("pending", "in_progress", "completed", "cancelled"):
                return ToolResult(
                    success=False,
                    error=f"Todo {i} has invalid status '{status}'. Must be one of: pending, in_progress, completed, cancelled"
                )
        
        plan_file_path = self.resolve_path(plan_file_path_arg)
        
        # Validate file exists and is a .plan.md file
        if not plan_file_path.exists():
            return ToolResult(success=False, error=f"Plan file not found: {plan_file_path_arg}")
        
        if not plan_file_path.is_file():
            return ToolResult(success=False, error=f"Not a file: {plan_file_path_arg}")
        
        if not str(plan_file_path).endswith(".plan.md"):
            return ToolResult(
                success=False,
                error=f"File must be a .plan.md file: {plan_file_path_arg}"
            )
        
        try:
            # Read the plan file
            with open(plan_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Parse frontmatter
            if not content.startswith("---"):
                return ToolResult(
                    success=False,
                    error="Plan file does not have valid frontmatter (must start with '---')"
                )
            
            # Find frontmatter boundaries
            lines = content.split("\n")
            frontmatter_start = 0
            frontmatter_end = None
            
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "---":
                    frontmatter_end = i
                    break
            
            if frontmatter_end is None:
                return ToolResult(
                    success=False,
                    error="Plan file does not have valid frontmatter (missing closing '---')"
                )
            
            # Extract frontmatter and content
            frontmatter_lines = lines[1:frontmatter_end]
            plan_content_lines = lines[frontmatter_end + 1:]
            plan_content = "\n".join(plan_content_lines)
            
            # Parse existing todos from frontmatter
            existing_todos = {}
            other_frontmatter = []
            in_todos_section = False
            current_todo = None
            
            for line in frontmatter_lines:
                stripped = line.strip()
                
                if stripped == "todos:":
                    in_todos_section = True
                    continue
                
                if in_todos_section:
                    # Check indentation: todos are indented with 2 spaces, content/status with 4 spaces
                    if line.startswith("  - id:"):
                        # Save previous todo if exists
                        if current_todo and current_todo.get("id"):
                            existing_todos[current_todo["id"]] = current_todo
                        
                        # Start new todo
                        todo_id = stripped.split(":", 1)[1].strip()
                        current_todo = {"id": todo_id, "content": "", "status": "pending"}
                    elif line.startswith("    content:"):
                        if current_todo:
                            current_todo["content"] = stripped.split(":", 1)[1].strip()
                    elif line.startswith("    status:"):
                        if current_todo:
                            current_todo["status"] = stripped.split(":", 1)[1].strip()
                    elif not stripped:
                        # Empty line - continue in todos section
                        continue
                    elif not line.startswith(" "):
                        # Line doesn't start with space - end of todos section (top-level key)
                        if current_todo and current_todo.get("id"):
                            existing_todos[current_todo["id"]] = current_todo
                        current_todo = None
                        in_todos_section = False
                        other_frontmatter.append(line)
                    # Otherwise, it's an indented line that's part of current todo (already handled above)
                else:
                    other_frontmatter.append(line)
            
            # Save last todo if exists
            if current_todo and current_todo.get("id"):
                existing_todos[current_todo["id"]] = current_todo
            
            # Apply merge or replace
            if merge:
                # Merge: update existing todos, add new ones
                updated_todos = existing_todos.copy()
                for todo in todos:
                    todo_id = todo["id"]
                    updated_todos[todo_id] = {
                        "id": todo_id,
                        "content": todo.get("content", updated_todos.get(todo_id, {}).get("content", "")),
                        "status": todo.get("status", updated_todos.get(todo_id, {}).get("status", "pending")),
                    }
                final_todos = list(updated_todos.values())
            else:
                # Replace: use only the provided todos
                final_todos = todos
            
            # Rebuild frontmatter
            new_frontmatter_lines = ["---"]
            new_frontmatter_lines.extend(other_frontmatter)
            
            # Add todos section
            if final_todos:
                new_frontmatter_lines.append("todos:")
                for todo in final_todos:
                    new_frontmatter_lines.append(f"  - id: {todo.get('id', '')}")
                    new_frontmatter_lines.append(f"    content: {todo.get('content', '')}")
                    new_frontmatter_lines.append(f"    status: {todo.get('status', 'pending')}")
            
            new_frontmatter_lines.append("---")
            new_frontmatter_lines.append("")
            
            # Combine frontmatter with plan content
            new_content = "\n".join(new_frontmatter_lines) + plan_content
            
            # Write back using write_file to get file change notifications
            write_result = await self.write_file({
                "path": str(plan_file_path),
                "content": new_content,
            })
            
            if not write_result.success:
                return write_result
            
            return ToolResult(
                success=True,
                result={
                    "path": str(plan_file_path),
                    "updated": True,
                    "todos": final_todos,
                    "merge": merge,
                    "todos_count": len(final_todos),
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to update todos in plan file: {str(e)}",
            )

    async def delegate_task(
        self,
        args: Dict[str, Any],
        on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        tool_call_id: Optional[str] = None,
        model_config: Optional[Dict[str, Any]] = None,
        original_on_event: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> ToolResult:
        """
        Delegate a research or information-finding task to a sub-agent.
        
        The sub-agent runs in its own context with access to read-only tools,
        investigates the task autonomously, and returns only the final answer.
        This keeps the main agent's context clean while allowing multi-turn research.
        
        Args:
            args: Dictionary containing:
                - task: Detailed description of what to find/research
                - purpose: Optional context about why this information is needed
            on_event: Callback for streaming events
            tool_call_id: Tool call ID for event correlation
            model_config: Model configuration for the sub-agent
        """
        import uuid
        
        task = args.get("task", "")
        purpose = args.get("purpose", "")
        
        if not task:
            return ToolResult(success=False, error="task is required")
        
        if not model_config:
            return ToolResult(
                success=False,
                error="delegate_task requires model_config to be passed from apps.code_editor.agent_runner"
            )
        
        if not self.project_id:
            return ToolResult(
                success=False,
                error="delegate_task requires project_id to be set on ToolExecutor"
            )
        
        if not on_event:
            return ToolResult(
                success=False,
                error="delegate_task requires on_event callback for streaming"
            )
        
        # Generate unique sub-agent ID
        sub_agent_id = f"sub_{str(uuid.uuid4())[:8]}"
        
        # Import AgentRunner here to avoid circular imports
        from apps.code_editor.agent_runner import get_agent_runner
        
        agent_runner = get_agent_runner()
        
        # Build user message for sub-agent
        sub_message = f"Research Task: {task}"
        if purpose:
            sub_message += f"\n\nContext: {purpose}"
        
        # Emit sub_agent_start event IMMEDIATELY before running the sub-agent
        # This ensures the UI receives it during streaming and can render the expander
        # CRITICAL: This must be emitted BEFORE run_agent_turn so the frontend receives it
        # during streaming, not just after completion when trace_events are reloaded
        import time
        import logging
        sub_agent_start_event = {
            "type": "sub_agent_start",
            "id": sub_agent_id,
            "timestamp": int(time.time() * 1000),
            "parentId": tool_call_id,  # Link to the delegate_task tool call
            "agentName": "Research Assistant",
            "purpose": sub_message[:100] + ("..." if len(sub_message) > 100 else ""),
            "input": {"task": task, "purpose": purpose} if purpose else {"task": task},
        }
        # CRITICAL: Emit sub_agent_start event BEFORE running sub-agent
        # This must happen synchronously and immediately to ensure frontend receives it during streaming
        # Use original_on_event if available (direct websocket callback), otherwise fall back to on_event (wrapper)
        event_callback = original_on_event if original_on_event else on_event
        if not event_callback:
            return ToolResult(
                success=False,
                error="delegate_task requires on_event callback for streaming sub_agent_start event"
            )
        
        try:
            # Emit the event immediately - use original callback to bypass wrapper and ensure it reaches frontend
            # The original_on_event is the direct websocket handler callback, not the emit_event wrapper
            await event_callback("sub_agent_start", sub_agent_start_event)
        except Exception as e:
            # Log error but don't fail the tool - event is still in trace_events for persistence
            logging.error(f"[delegate_task] Failed to emit sub_agent_start event: {e}", exc_info=True)
            # Don't raise - allow sub-agent to continue even if event emission fails
        
        try:
            # Run sub-agent with parent_tool_call_id
            # Note: sub_agent_start is already emitted above, so run_agent_turn will skip emitting it again
            result = await agent_runner.run_agent_turn(
                project_id=self.project_id,
                chat_id="sub_agent",  # Virtual chat ID - not used in sub-agent mode
                user_message=sub_message,
                user_context=[],
                mode="ask",  # Force ask mode for read-only tools
                model_config=model_config,
                on_event=on_event,
                debug=False,
                parent_tool_call_id=tool_call_id,
                sub_agent_id=sub_agent_id,
            )
            
            # Extract the result from the sub-agent
            assistant_message = result.get("assistantMessage", "")
            error = result.get("meta", {}).get("error")
            sub_trace_events = result.get("meta", {}).get("traceEvents", [])
            
            if error:
                return ToolResult(
                    success=False,
                    result=assistant_message,
                    error=error,
                )
            
            return ToolResult(
                success=True,
                # Return structured payload so AgentRunner can persist sub-agent activity
                result={
                    "answer": assistant_message,
                    "traceEvents": sub_trace_events if isinstance(sub_trace_events, list) else [],
                },
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Sub-agent execution failed: {str(e)}",
            )


# Singleton instance (keyed by project_root + mode for mode-aware execution)
_tool_executors: Dict[str, ToolExecutor] = {}


def get_tool_executor(
    project_root: Optional[str] = None,
    mode: Optional[str] = None,
    set_id: str = "default",
    family: Optional[str] = None,
    version: Optional[str] = None,
    project_id: Optional[str] = None,
) -> ToolExecutor:
    """
    Get a ToolExecutor instance.
    
    Creates a new executor if project_root or mode changes to ensure mode-aware tool filtering.
    """
    global _tool_executors
    
    # Create cache key from apps.code_editor.project_root and mode
    cache_key = f"{project_root or 'default'}:{mode or 'default'}:{set_id}:{family or 'default'}:{version or 'default'}:{project_id or 'default'}"
    
    if cache_key not in _tool_executors:
        _tool_executors[cache_key] = ToolExecutor(
            project_root=project_root,
            mode=mode,
            set_id=set_id,
            family=family,
            version=version,
            project_id=project_id,
        )
    elif project_root and str(_tool_executors[cache_key].project_root) != project_root:
        # Project root changed - create new executor
        _tool_executors[cache_key] = ToolExecutor(
            project_root=project_root,
            mode=mode,
            set_id=set_id,
            family=family,
            version=version,
            project_id=project_id,
        )
    
    return _tool_executors[cache_key]


async def execute_tool(
    tool_name: str,
    args: Dict[str, Any],
    project_root: Optional[str] = None,
    mode: Optional[str] = None,
    set_id: str = "default",
    family: Optional[str] = None,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a tool and return the result as a dict."""
    executor = get_tool_executor(
        project_root=project_root,
        mode=mode,
        set_id=set_id,
        family=family,
        version=version,
    )
    result = await executor.execute(tool_name, args)
    
    return {
        "success": result.success,
        "result": result.result,
        "error": result.error,
    }


def approve_command(command_hash: str) -> None:
    """Approve a command by adding its hash to the approved set."""
    _approved_commands.add(command_hash)


def get_pending_command(command_hash: str) -> Optional[Dict[str, Any]]:
    """Get stored pending command info."""
    return _pending_commands.get(command_hash)


def clear_pending_command(command_hash: str) -> None:
    """Remove a pending command from storage."""
    _pending_commands.pop(command_hash, None)


async def handle_confirm_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for confirming a command. Returns pending command info for execution."""
    command_hash = payload.get("id")
    if not command_hash:
        return {
            "success": False,
            "error": "Command hash (id) is required",
        }
    
    # Get pending command info
    pending = get_pending_command(command_hash)
    if not pending:
        return {
            "success": False,
            "error": "Pending command not found",
        }
    
    # Approve and return command info
    approve_command(command_hash)
    
    return {
        "success": True,
        "message": "Command approved",
        "pendingCommand": pending,
    }


# RPC Handlers

async def handle_execute_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RPC handler for executing a tool."""
    tool_name = payload.get("tool", "")
    args = payload.get("args", {})
    project_root = payload.get("projectRoot")
    
    if not tool_name:
        return {
            "success": False,
            "error": "Tool name is required",
        }
    
    return await execute_tool(tool_name, args, project_root)
