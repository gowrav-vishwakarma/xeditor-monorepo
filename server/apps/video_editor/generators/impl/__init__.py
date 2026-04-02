"""
Video Editor Generator Implementations

This package contains the concrete generator implementations for the video editor.
"""

from apps.video_editor.generators.impl.tts_coqui_xtts import CoquiXTTSGenerator
from apps.video_editor.generators.impl.tts_f5 import F5TTSGenerator
from apps.video_editor.generators.impl.t2i_sdxl import SDXLT2IGenerator
from apps.video_editor.generators.impl.t2i_ipadapter import IPAdapterSDXLGenerator
from apps.video_editor.generators.impl.i2v_slideshow import SlideshowI2VGenerator
from apps.video_editor.generators.impl.i2v_svd import SVDI2VGenerator
from apps.video_editor.generators.impl.i2v_wan import WanI2VGenerator
from apps.video_editor.generators.impl.t2v_wan import WanT2VGenerator
from apps.video_editor.generators.impl.t2v_zeroscope import ZeroscopeT2VGenerator
from apps.video_editor.generators.impl.t2v_cogvideox import CogVideoXT2VGenerator
from apps.video_editor.generators.impl.t2v_hunyuan import HunyuanVideoGenerator
from apps.video_editor.generators.impl.story_llm import StoryLLMGenerator
from apps.video_editor.generators.impl.music_musicgen import MusicGenGenerator
from apps.video_editor.generators.impl.music_acestep import ACEStepMusicGenerator
from apps.video_editor.generators.impl.sfx_audiogen import AudioGenSFXGenerator
from apps.video_editor.generators.impl.lipsync_musetalk import MuseTalkLipSyncGenerator

__all__ = [
    "CoquiXTTSGenerator",
    "F5TTSGenerator",
    "SDXLT2IGenerator",
    "IPAdapterSDXLGenerator",
    "SlideshowI2VGenerator",
    "SVDI2VGenerator",
    "WanI2VGenerator",
    "WanT2VGenerator",
    "ZeroscopeT2VGenerator",
    "CogVideoXT2VGenerator",
    "HunyuanVideoGenerator",
    "StoryLLMGenerator",
    "MusicGenGenerator",
    "ACEStepMusicGenerator",
    "AudioGenSFXGenerator",
    "MuseTalkLipSyncGenerator",
]
