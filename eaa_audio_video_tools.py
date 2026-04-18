"""
EAA Audio/Video Tools - Phase 9
Audio transcription, text-to-speech, and video analysis.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import traceback
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

try:
    from eaa_agent_tools import ToolResult
except ImportError:
    @dataclass
    class ToolResult:
        success: bool
        output: str
        error: Optional[str] = None
        def to_dict(self):
            return {"success": self.success, "output": self.output, "error": self.error}


# ─── AUDIO TRANSCRIBE ─────────────────────────────────────────────────────────
def tool_audio_transcribe(
    audio_path: str,
    language: str = "en",
    model_size: str = "base",
    output_file: str = None
) -> ToolResult:
    """
    Transcribe audio to text using Whisper.
    model_size: tiny, base, small, medium, large (higher = more accurate but slower)
    language: Language code (en, es, fr, ar, etc.) or None for auto-detect
    """
    try:
        audio_path = os.path.expanduser(audio_path)
        if not os.path.exists(audio_path):
            return ToolResult(False, "", f"Audio file not found: {audio_path}")

        from faster_whisper import WhisperModel

        # Determine compute type based on CUDA availability
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
        except Exception:
            device = "cpu"
            compute_type = "int8"

        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        segments, info = model.transcribe(
            audio_path,
            language=language if language != "auto" else None,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        transcription_parts = [f"Language: {info.language} (probability: {info.language_probability:.2f})"]
        transcription_parts.append(f"Duration: {info.duration:.1f}s")
        transcription_parts.append("")

        full_text = []
        for segment in segments:
            start = segment.start
            end = segment.end
            text = segment.text.strip()
            transcription_parts.append(f"[{start:.1f}s - {end:.1f}s] {text}")
            full_text.append(text)

        transcript = "\n".join(full_text)

        # Save to file if requested
        if output_file:
            output_file = os.path.expanduser(output_file)
            os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(transcript)
            transcription_parts.append(f"\nTranscript saved to: {output_file}")

        return ToolResult(True, "\n".join(transcription_parts))

    except ImportError:
        return ToolResult(False, "", "faster-whisper not installed. Install: pip install faster-whisper")
    except Exception as e:
        return ToolResult(False, "", f"Audio transcription failed: {str(e)}")


# ─── AUDIO GENERATE (TTS) ────────────────────────────────────────────────────
def tool_audio_generate(
    text: str,
    output_path: str = None,
    voice: str = "default",
    engine: str = "edge_tts",
    speed: str = "+0%"
) -> ToolResult:
    """
    Generate speech from text (Text-to-Speech).
    engine: 'edge_tts' (Microsoft Edge TTS - free, online), 'pyttsx3' (offline)
    voice: Voice name (edge_tts: 'en-US-AriaNeural', 'en-US-GuyNeural', etc.)
    speed: Speed adjustment ('+0%', '+10%', '-10%', etc.) for edge_tts
    """
    try:
        if output_path is None:
            output_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "audio")
            os.makedirs(output_dir, exist_ok=True)
            filename = f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
            output_path = os.path.join(output_dir, filename)
        else:
            output_path = os.path.expanduser(output_path)
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        if engine == "edge_tts":
            import edge_tts
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            communicate = edge_tts.Communicate(text, voice, rate=speed)
            loop.run_until_complete(communicate.save(output_path))
            loop.close()

        elif engine == "pyttsx3":
            import pyttsx3
            engine_obj = pyttsx3.init()
            # List available voices
            voices = engine_obj.getProperty('voices')
            if voice != "default":
                for v in voices:
                    if voice.lower() in v.name.lower() or voice.lower() in v.id.lower():
                        engine_obj.setProperty('voice', v.id)
                        break
            engine_obj.save_to_file(text, output_path)
            engine_obj.runAndWait()

        else:
            return ToolResult(False, "", f"Unknown TTS engine: {engine}. Use 'edge_tts' or 'pyttsx3'")

        size = os.path.getsize(output_path)
        return ToolResult(True, f"Audio generated: {output_path}\nSize: {size:,} bytes\nEngine: {engine}\nVoice: {voice}")

    except Exception as e:
        return ToolResult(False, "", f"Audio generation failed: {str(e)}")


# ─── AUDIO INFO ───────────────────────────────────────────────────────────────
def tool_audio_info(audio_path: str) -> ToolResult:
    """Get audio file information."""
    try:
        audio_path = os.path.expanduser(audio_path)
        if not os.path.exists(audio_path):
            return ToolResult(False, "", f"Audio not found: {audio_path}")

        from pydub import AudioSegment

        audio = AudioSegment.from_file(audio_path)
        file_size = os.path.getsize(audio_path)

        info = {
            "file": audio_path,
            "format": audio_path.split(".")[-1].upper(),
            "duration_seconds": len(audio) / 1000,
            "duration_formatted": f"{len(audio) // 60000}:{(len(audio) % 60000) // 1000:02d}",
            "channels": audio.channels,
            "sample_rate": f"{audio.frame_rate} Hz",
            "sample_width": f"{audio.sample_width * 8}-bit",
            "frame_count": audio.frame_count(),
            "file_size": f"{file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)",
            "dBFS": f"{audio.dBFS:.1f}" if hasattr(audio, 'dBFS') else "N/A",
        }

        return ToolResult(True, json.dumps(info, indent=2))

    except Exception as e:
        return ToolResult(False, "", f"Audio info failed: {str(e)}")


# ─── VIDEO ANALYZE ────────────────────────────────────────────────────────────
def tool_video_analyze(
    video_path: str,
    extract_frames: int = 5,
    output_dir: str = None
) -> ToolResult:
    """
    Analyze a video file: extract metadata and sample frames.
    extract_frames: Number of frames to extract from the video
    """
    try:
        video_path = os.path.expanduser(video_path)
        if not os.path.exists(video_path):
            return ToolResult(False, "", f"Video not found: {video_path}")

        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return ToolResult(False, "", "Failed to open video file")

        # Video metadata
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0

        metadata = {
            "file": video_path,
            "resolution": f"{width}x{height}",
            "fps": round(fps, 2),
            "frame_count": frame_count,
            "duration_seconds": round(duration, 2),
            "duration_formatted": f"{int(duration // 60)}:{int(duration % 60):02d}",
            "file_size": f"{os.path.getsize(video_path):,} bytes",
        }

        # Extract frames
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(__file__), "..", "outputs", "video_frames")
        os.makedirs(output_dir, exist_ok=True)

        frame_paths = []
        if extract_frames > 0 and frame_count > 0:
            interval = max(1, frame_count // extract_frames)
            for i in range(extract_frames):
                frame_num = i * interval
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if ret:
                    timestamp = frame_num / fps
                    frame_filename = f"frame_{i:03d}_{timestamp:.1f}s.jpg"
                    frame_path = os.path.join(output_dir, frame_filename)
                    cv2.imwrite(frame_path, frame)
                    frame_paths.append(frame_path)

        cap.release()

        result = json.dumps(metadata, indent=2)
        if frame_paths:
            result += f"\n\nExtracted {len(frame_paths)} frames:"
            for fp in frame_paths:
                result += f"\n  - {fp}"

        return ToolResult(True, result)

    except ImportError:
        return ToolResult(False, "", "OpenCV not installed. Install: pip install opencv-python")
    except Exception as e:
        return ToolResult(False, "", f"Video analysis failed: {str(e)}")


# ─── VIDEO INFO ───────────────────────────────────────────────────────────────
def tool_video_info(video_path: str) -> ToolResult:
    """Get video file metadata without extracting frames."""
    return tool_video_analyze(video_path, extract_frames=0)


# ─── AUDIO CONVERT ────────────────────────────────────────────────────────────
def tool_audio_convert(
    input_path: str,
    output_path: str,
    format: str = None,
    bitrate: str = "128k"
) -> ToolResult:
    """Convert audio file format using pydub."""
    try:
        input_path = os.path.expanduser(input_path)
        output_path = os.path.expanduser(output_path)

        if not os.path.exists(input_path):
            return ToolResult(False, "", f"Audio not found: {input_path}")

        from pydub import AudioSegment

        audio = AudioSegment.from_file(input_path)
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        if format:
            output_path = output_path.rsplit(".", 1)[0] + f".{format}"

        audio.export(output_path, format=format or output_path.split(".")[-1], bitrate=bitrate)

        size = os.path.getsize(output_path)
        return ToolResult(True, f"Audio converted: {input_path} -> {output_path}\nNew size: {size:,} bytes")

    except Exception as e:
        return ToolResult(False, "", f"Audio conversion failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_audio_video_tools(registry) -> None:
    """Register all audio/video tools with the existing ToolRegistry."""
    registry.register("audio_transcribe", tool_audio_transcribe, "Transcribe audio to text (Whisper). Args: audio_path, language, model_size")
    registry.register("audio_generate", tool_audio_generate, "Generate speech (TTS). Args: text, output_path, voice, engine (edge_tts/pyttsx3)")
    registry.register("audio_info", tool_audio_info, "Get audio file info. Args: audio_path")
    registry.register("audio_convert", tool_audio_convert, "Convert audio format. Args: input_path, output_path, format, bitrate")
    registry.register("video_analyze", tool_video_analyze, "Analyze video + extract frames. Args: video_path, extract_frames, output_dir")
    registry.register("video_info", tool_video_info, "Get video metadata. Args: video_path")

__all__ = [
    "register_audio_video_tools",
    "tool_audio_transcribe", "tool_audio_generate", "tool_audio_info",
    "tool_audio_convert", "tool_video_analyze", "tool_video_info",
]
