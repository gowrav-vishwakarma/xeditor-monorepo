from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import tarfile
from pathlib import Path


def _repo_root(server_dir: Path) -> Path:
    return server_dir.parent


def _dist_dir(server_dir: Path) -> Path:
    return server_dir / "dist"


def _build_dir(server_dir: Path) -> Path:
    return server_dir / "build"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[build] $ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd))


def _detect_platform_suffix() -> str:
    if sys.platform.startswith("linux"):
        return "linux-x64"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows-x64"
    return sys.platform


def _get_ripgrep_platform_info() -> tuple[str, str, str]:
    """
    Get ripgrep download info for current platform.
    
    Returns:
        Tuple of (platform_name, archive_extension, binary_name)
    """
    if sys.platform.startswith("linux"):
        # Check architecture
        import platform
        machine = platform.machine().lower()
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
        import platform
        machine = platform.machine().lower()
        if machine == "arm64":
            return ("aarch64-apple-darwin", "tar.gz", "rg")
        else:
            return ("x86_64-apple-darwin", "tar.gz", "rg")
    elif os.name == "nt":
        import platform
        machine = platform.machine().lower()
        if machine == "arm64":
            return ("aarch64-pc-windows-msvc", "zip", "rg.exe")
        else:
            return ("x86_64-pc-windows-msvc", "zip", "rg.exe")
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _download_ripgrep_binary(server_dir: Path, build_dir: Path) -> Path:
    """
    Download ripgrep binary for current platform.
    
    Returns:
        Path to downloaded rg binary
    """
    ripgrep_version = "15.1.0"  # Latest stable version
    platform_name, archive_ext, binary_name = _get_ripgrep_platform_info()
    
    archive_name = f"ripgrep-{ripgrep_version}-{platform_name}.{archive_ext}"
    url = f"https://github.com/BurntSushi/ripgrep/releases/download/{ripgrep_version}/{archive_name}"
    
    # Create ripgrep directory in build folder
    ripgrep_dir = build_dir / "ripgrep"
    ripgrep_dir.mkdir(parents=True, exist_ok=True)
    
    archive_path = ripgrep_dir / archive_name
    binary_path = ripgrep_dir / binary_name
    
    # Skip download if binary already exists
    if binary_path.exists():
        print(f"[build] Ripgrep binary already exists at {binary_path}, skipping download")
        return binary_path
    
    print(f"[build] Downloading ripgrep {ripgrep_version} for {platform_name}...")
    print(f"[build] URL: {url}")
    
    try:
        # Download archive
        urllib.request.urlretrieve(url, archive_path)
        print(f"[build] Downloaded {archive_name}")
        
        # Extract archive
        if archive_ext == "zip":
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                # Find the binary in the archive (usually in a subdirectory)
                for member in zip_ref.namelist():
                    if member.endswith(binary_name) and not member.endswith("/"):
                        # Extract the binary
                        zip_ref.extract(member, ripgrep_dir)
                        # Move to expected location (handle nested paths)
                        extracted_path = ripgrep_dir / member
                        if extracted_path.exists() and extracted_path != binary_path:
                            extracted_path.rename(binary_path)
                        else:
                            # Search for extracted binary in subdirectories
                            for nested in ripgrep_dir.rglob(binary_name):
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
                        tar_ref.extract(member, ripgrep_dir)
                        # Move to expected location (handle nested paths)
                        extracted_path = ripgrep_dir / member.name
                        if extracted_path.exists() and extracted_path != binary_path:
                            extracted_path.rename(binary_path)
                        else:
                            # Search for extracted binary in subdirectories
                            for nested in ripgrep_dir.rglob(binary_name):
                                if nested.is_file() and nested != binary_path:
                                    nested.rename(binary_path)
                                    break
                        break
        
        # Make executable on Unix-like systems
        if sys.platform != "win32":
            os.chmod(binary_path, 0o755)
        
        # Clean up archive
        archive_path.unlink()
        
        print(f"[build] Extracted ripgrep binary to {binary_path}")
        return binary_path
        
    except Exception as e:
        print(f"[build] Warning: Failed to download ripgrep: {e}")
        print(f"[build] The application will use Python regex fallback if ripgrep is not in PATH")
        # Return None to indicate failure
        return None


def build_server_binary(*, server_dir: Path, output_name: str) -> Path:
    dist_dir = _dist_dir(server_dir)
    build_dir = _build_dir(server_dir)

    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    entry = server_dir / "main.py"
    if not entry.exists():
        raise FileNotFoundError(f"Entry not found: {entry}")

    # Clean previous binary artifacts for deterministic packaging
    for p in [dist_dir / output_name, dist_dir / f"{output_name}.exe"]:
        if p.exists():
            p.unlink()

    # Nuitka build: compile to a standalone directory, then use that as "the server".
    # We include prompt sets and JSON model registries as data.
    # Exclude problematic packages with complex native dependencies from compilation.
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--follow-imports",
        "--assume-yes-for-downloads",
        f"--output-filename={output_name}",
        f"--output-dir={str(dist_dir)}",
        f"--include-data-dir={str(server_dir / 'apps' / 'code_editor' / 'prompt_sets')}=apps/code_editor/prompt_sets",
        f"--include-data-file={str(server_dir / 'apps' / 'code_editor' / 'models' / 'defaults.json')}=apps/code_editor/models/defaults.json",
        f"--include-data-file={str(server_dir / 'apps' / 'code_editor' / 'models' / 'families.json')}=apps/code_editor/models/families.json",
        "--include-package=apps.code_editor.models",
        "--include-package=apps.code_editor.prompt_sets",
        "--include-package=apps.code_editor.tools",
        "--include-package=apps.code_editor.agent",
        "--include-package=apps.code_editor.parsers",
        "--include-package=apps.code_editor.prompts",
        "--include-package=apps.code_editor.sets",
        "--include-package=tree_sitter_languages",
        # Exclude onnxruntime packages from compilation - they have complex native deps
        # They'll be included as DLLs/shared libs in the distribution folder
        "--nofollow-import-to=onnxruntime",
        "--nofollow-import-to=onnxruntime.capi",
        "--nofollow-import-to=onnxruntime.capi.onnxruntime_pybind11_state",
        # Exclude numpy's internal modules that can cause issues
        "--nofollow-import-to=numpy.distutils",
        # Prefer dynamic linking for native extensions to avoid static library issues
        "--enable-plugin=anti-bloat",
        "--remove-output",
        str(entry),
    ]

    _run(cmd, cwd=server_dir)

    # Nuitka creates either dist/output_name.dist/<binary> or dist/<binary> depending on options.
    # However, when using --output-filename, Nuitka may create a folder named after the entry point
    # (e.g., "main.dist") instead of the output filename. We handle this case by renaming it.
    produced_dist = dist_dir / f"{output_name}.dist"
    
    # Check if Nuitka created a folder based on the entry point name (main.dist)
    if not produced_dist.exists():
        entry_based_dist = dist_dir / f"{entry.stem}.dist"
        if entry_based_dist.exists():
            print(f"[build] Renaming {entry_based_dist.name} to {produced_dist.name}")
            entry_based_dist.rename(produced_dist)

    if not produced_dist.exists():
        # Fallback (some configurations output directly into dist_dir)
        direct = dist_dir / output_name
        if direct.exists():
            produced_dist = direct
        else:
            raise RuntimeError("Nuitka build finished but output not found.")

    # Copy onnxruntime manually since we excluded it from compilation
    try:
        import onnxruntime
        ort_path = Path(onnxruntime.__path__[0])
        dest_ort = produced_dist / "onnxruntime"
        if dest_ort.exists():
            shutil.rmtree(dest_ort)
        shutil.copytree(ort_path, dest_ort)
        print(f"[build] Copied onnxruntime from {ort_path} to {dest_ort}")
    except ImportError:
        print("[build] Warning: onnxruntime not found, skipping copy.")

    # Ensure litellm data files are included (Nuitka may miss some JSON files)
    try:
        import litellm
        litellm_path = Path(litellm.__path__[0])
        dest_litellm = produced_dist / "litellm"
        
        # Check if endpoints.json exists in source but not in destination
        endpoints_src = litellm_path / "containers" / "endpoints.json"
        endpoints_dest = dest_litellm / "containers" / "endpoints.json"
        
        if endpoints_src.exists() and not endpoints_dest.exists():
            # Ensure containers directory exists
            endpoints_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(endpoints_src, endpoints_dest)
            print(f"[build] Copied missing litellm data file: {endpoints_dest.name}")
    except ImportError:
        print("[build] Warning: litellm not found, skipping data file copy.")

    # Copy prompt_sets directory with all Python files for runtime discovery
    # Nuitka compiles prompt_sets but doesn't preserve .py files on disk, which are needed
    # for PromptSetManager to discover sets and load parsers dynamically
    prompt_sets_src = server_dir / "apps" / "code_editor" / "prompt_sets"
    prompt_sets_dest = produced_dist / "apps" / "code_editor" / "prompt_sets"
    
    if prompt_sets_src.exists() and prompt_sets_src.is_dir():
        # Remove existing prompt_sets in dist (may have partial data from Nuitka)
        if prompt_sets_dest.exists():
            shutil.rmtree(prompt_sets_dest)
        
        # Copy entire prompt_sets directory including all .py files
        shutil.copytree(prompt_sets_src, prompt_sets_dest)
        print(f"[build] Copied prompt_sets directory from {prompt_sets_src} to {prompt_sets_dest}")
    else:
        print(f"[build] Warning: prompt_sets source directory not found at {prompt_sets_src}")

    # Download and bundle ripgrep binary for production search.
    # If bundling fails or the binary doesn't match the build host arch,
    # the runtime self-heal will download the correct one to ~/.xeditor/bin/.
    try:
        rg_binary = _download_ripgrep_binary(server_dir, build_dir)
        if rg_binary and rg_binary.exists():
            dest_rg = produced_dist / rg_binary.name
            shutil.copy2(rg_binary, dest_rg)
            if sys.platform != "win32":
                os.chmod(dest_rg, 0o755)
            print(f"[build] Bundled ripgrep binary: {dest_rg}")

            # Validate bundled rg runs on this host (best-effort)
            try:
                result = subprocess.run(
                    [str(dest_rg), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    print(f"[build] Ripgrep validation OK: {result.stdout.strip()}")
                else:
                    print(f"[build] Warning: bundled rg exited with {result.returncode}. "
                          "Runtime will auto-download correct binary if needed.")
            except OSError as e:
                if hasattr(e, "errno") and e.errno == 8:  # ENOEXEC — wrong arch
                    print("[build] Warning: bundled rg has wrong architecture for build host. "
                          "Runtime will auto-download correct binary on first search.")
                else:
                    print(f"[build] Warning: bundled rg failed to execute: {e}. "
                          "Runtime will auto-download correct binary if needed.")
        else:
            print("[build] Warning: could not download ripgrep. "
                  "Runtime will auto-download on first search.")
    except Exception as e:
        print(f"[build] Warning: ripgrep bundling failed: {e}. "
              "Runtime will auto-download on first search.")

    return produced_dist


def main() -> int:
    parser = argparse.ArgumentParser(description="Build XEditor Local Companion (protected)")
    parser.add_argument("--name", default="xeditor-server", help="Binary name (no extension)")
    parser.add_argument("--clean", action="store_true", help="Remove server/build and server/dist first")
    args = parser.parse_args()

    server_dir = Path(__file__).resolve().parent

    if args.clean:
        for p in [_build_dir(server_dir), _dist_dir(server_dir)]:
            if p.exists():
                shutil.rmtree(p)

    out_dir = build_server_binary(server_dir=server_dir, output_name=args.name)
    print(f"[build] produced: {out_dir}")
    print(f"[build] platform: {_detect_platform_suffix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

