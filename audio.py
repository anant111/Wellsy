"""audio.py - Synthesize per-scene narration with Gemini TTS, then mix into final video.

API: gemini-2.5-flash-preview-tts, invoked via the generateContent endpoint with
response_modalities=['AUDIO']. Audio is returned as inline base64 (WAV or MP3).

We:
  1. Synthesize one narration clip per scene
  2. Pad (or trim) each clip to exactly 6s so they concat cleanly
  3. Concatenate into one full-track WAV
  4. Mux the audio into the final video with ffmpeg

Failure mode: if TTS fails for a scene, the audio stage is marked failed and
the job fails. The video (without audio) is left on disk so the user can
inspect it.
"""
import base64
import os
import subprocess
from typing import Optional

import requests
from dotenv import load_dotenv

# env loading
def _find_and_load_dotenv():
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            load_dotenv(dotenv_path=candidate)
            return
        here = os.path.dirname(here)
    load_dotenv()


_find_and_load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
TTS_MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "Kore")  # clear, neutral female default

# Fallback voice list (Gemini TTS voices)
FALLBACK_VOICES = ["Kore", "Aoede", "Leda", "Orus", "Puck"]


def _tts_request(text: str, voice: str) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{TTS_MODEL}:generateContent?key={API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }
    return body, url


def _extract_audio_bytes(payload: dict) -> Optional[bytes]:
    """Pull the base64 audio out of a generateContent response."""
    candidates = payload.get("candidates", [])
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData")
        if not inline:
            continue
        mime = (inline.get("mimeType") or "").lower()
        if mime.startswith("audio"):
            return base64.b64decode(inline["data"])
    return None


def _wrap_raw_pcm_as_wav(raw_pcm: bytes, output_path: str) -> None:
    """TTS returns raw 16-bit PCM (mime audio/L16;codec=pcm;rate=24000).
    Wrap with a WAV header so anything that reads the file gets a real wav."""
    import struct
    sample_rate = 24000
    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(raw_pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,                # PCM fmt chunk size
        1,                 # PCM format
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    with open(output_path, "wb") as f:
        f.write(header)
        f.write(raw_pcm)


def synthesize_narration(
    text: str,
    output_path: str,
    voice: str = TTS_VOICE,
) -> bool:
    """Generate a narration WAV file for `text`. Returns True on success.

    Tries `voice` first, then falls back through FALLBACK_VOICES if it 404s.
    The TTS API returns raw 16-bit PCM at 24kHz (no header); we wrap it
    with a WAV header on the way out.
    """
    if not text or not text.strip():
        print("[audio] ❌ Empty narration text")
        return False

    voices_to_try = [voice] + [v for v in FALLBACK_VOICES if v != voice]
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    for v in voices_to_try:
        body, url = _tts_request(text, v)
        try:
            resp = requests.post(url, json=body, timeout=60)
        except requests.RequestException as e:
            print(f"[audio] Network error with voice {v}: {e}")
            continue
        if resp.status_code == 404:
            print(f"[audio] Voice {v} not supported, trying next...")
            continue
        if resp.status_code != 200:
            print(f"[audio] Voice {v} failed: {resp.status_code} {resp.text[:200]}")
            continue
        raw_pcm = _extract_audio_bytes(resp.json())
        if not raw_pcm:
            print(f"[audio] Voice {v} returned no audio data")
            continue
        _wrap_raw_pcm_as_wav(raw_pcm, output_path)
        size_kb = os.path.getsize(output_path) / 1024
        print(f"[audio] ✅ Synthesized {size_kb:.1f} KB with voice {v} -> {output_path}")
        return True

    print(f"[audio] ❌ All voices failed for narration: {text[:50]}...")
    return False


def pad_to_duration(wav_path: str, seconds: float) -> None:
    """Pad with silence, then trim, to exactly `seconds`. Idempotent."""
    tmp = wav_path + ".tmp.wav"
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-af", f"apad=pad_dur={seconds},atrim=0:{seconds}",
        "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1",
        tmp,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg pad failed: {r.stderr}")
    os.replace(tmp, wav_path)


def concat_audio(audio_paths: list, output_path: str) -> str:
    """Concatenate WAVs (assumed same codec/sample rate) into one file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    list_path = output_path + ".concat.txt"
    with open(list_path, "w") as f:
        for p in audio_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy", output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"audio concat failed: {r.stderr}")
    return output_path


def mux_audio_into_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Replace a video's (silent) track with the narration track via ffmpeg."""
    tmp = output_path + ".tmp.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        tmp,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mux failed: {r.stderr}")
    os.replace(tmp, output_path)
    return output_path


if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "Imagine a quiet morning, free of noise."
    out = "/tmp/test_narration.wav"
    if synthesize_narration(text, out):
        pad_to_duration(out, 6.0)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", out],
            capture_output=True, text=True,
        )
        print(f"Padded to: {probe.stdout.strip()}s, file size: {os.path.getsize(out)} bytes")
