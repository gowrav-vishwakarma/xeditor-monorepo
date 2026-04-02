"""
TorchAudio 2.9+ routes load/save through TorchCodec, whose wheels can require
CUDA NVRTC libs (e.g. libnvrtc.so.13) that do not match the installed PyTorch
CUDA build. F5-TTS and other code call torchaudio.load/save for WAV I/O only.

We replace those entry points with SoundFile-backed implementations so video
editor TTS/music/SFX work without a working libtorchcodec.
"""

from __future__ import annotations

import os
from typing import Any, BinaryIO, Optional, Tuple, Union

_PATCHED = False


def _patched_load(
    uri: Union[BinaryIO, str, os.PathLike[str]],
    frame_offset: int = 0,
    num_frames: int = -1,
    normalize: bool = True,
    channels_first: bool = True,
    format: Optional[str] = None,
    buffer_size: int = 4096,
    backend: Optional[str] = None,
) -> Tuple[Any, int]:
    import io

    import numpy as np
    import soundfile as sf
    import torch

    del format, buffer_size, backend  # API compatibility; SoundFile infers format

    if hasattr(uri, "read"):
        raw = uri.read()  # type: ignore[union-attr]
        data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    else:
        data, sr = sf.read(os.fsdecode(uri), dtype="float32", always_2d=True)

    if not normalize:
        # Match legacy expectation loosely: keep float32 in [-1, 1]
        pass

    if frame_offset > 0 or num_frames != -1:
        end = None if num_frames == -1 else frame_offset + num_frames
        data = data[frame_offset:end]

    audio = torch.from_numpy(np.ascontiguousarray(data))
    if channels_first:
        audio = audio.T
    return audio, int(sr)


def _patched_save(
    uri: Union[str, os.PathLike[str]],
    src: Any,
    sample_rate: int,
    channels_first: bool = True,
    format: Optional[str] = None,
    encoding: Optional[str] = None,
    bits_per_sample: int = 16,
    buffer_size: int = 4096,
    backend: Optional[str] = None,
) -> None:
    import numpy as np
    import soundfile as sf
    import torch

    del format, encoding, buffer_size, backend

    t = src.detach().cpu().float()
    arr = t.numpy()
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    elif channels_first and arr.shape[0] <= 8 and arr.shape[0] < arr.shape[-1]:
        arr = np.ascontiguousarray(arr.T)
    arr = np.clip(arr, -1.0, 1.0)
    subtype = "PCM_16" if bits_per_sample == 16 else "FLOAT"
    sf.write(os.fsdecode(uri), arr, sample_rate, subtype=subtype)


def apply_patch() -> None:
    """Idempotent: patch torchaudio.load / torchaudio.save for WAV/file I/O."""
    global _PATCHED
    if _PATCHED:
        return

    import torchaudio

    torchaudio.load = _patched_load  # type: ignore[assignment]
    torchaudio.save = _patched_save  # type: ignore[assignment]
    _PATCHED = True
