import os
import base64
import textwrap
import traceback
import subprocess
import numpy as np
import PIL.Image
from PIL import Image, ImageDraw, ImageFont

# Compatibility Patch for MoviePy 1.0.3
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

import runpod
import moviepy.editor as mpy
from pydub import AudioSegment, silence

FONT_PATH = "/app/NotoSansDevanagari.ttf"
VOICE_SAMPLE_PATH = "/app/my_voice.wav"

xtts_model = None

def log(*args):
    print(*args, flush=True)

def ensure_tts_loaded():
    global xtts_model
    if xtts_model is None:
        log("Loading XTTSv2 Voice Cloning Model...")
        from TTS.api import TTS
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        xtts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

def generate_audio(script: str, output_path: str):
    ensure_tts_loaded()
    raw_audio_path = output_path.replace(".wav", "_raw.wav")
    
    # 1. Generate normal slow audio
    xtts_model.tts_to_file(
        text=script, 
        speaker_wav=VOICE_SAMPLE_PATH, 
        language="hi", 
        file_path=raw_audio_path
    )
    
    # 2. Speed up audio by 25% (1.25x) using FFmpeg without altering pitch
    log("Applying FFmpeg atempo filter to increase audio speed...")
    subprocess.run([
        "ffmpeg", "-y", "-i", raw_audio_path, 
        "-filter:a", "atempo=1.25", output_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_speaking_intervals(audio_path: str):
    audio = AudioSegment.from_file(audio_path)
    nonsilent = silence.detect_nonsilent(audio, min_silence_len=150, silence_thresh=-40)
    return [(s / 1000.0, e / 1000.0) for s, e in nonsilent], audio.duration_seconds

def create_subtitle_file(text: str, filepath: str, width=980, height=1920):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 65)
    except Exception:
        font = ImageFont.load_default()

    wrapped_text = "\n".join(textwrap.wrap(text, width=28))
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=15)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pos_x = (width - text_w) // 2
    pos_y = height - text_h - 300 

    draw.multiline_text(
        (pos_x, pos_y), wrapped_text, font=font, fill=(255, 223, 0),
        stroke_width=8, stroke_fill=(0, 0, 0), align="center", spacing=15
    )
    img.save(filepath)

def handler(event):
    try:
        script = event.get("input", {}).get("script", "").strip()
        if not script: return {"error": "Missing script"}

        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        audio_path = os.path.join(workdir, "speech.wav")
        final_video_path = os.path.join(workdir, "final.mp4")

        log("Step 1: Audio & Intervals")
        generate_audio(script, audio_path)
        speaking_intervals, total_dur = get_speaking_intervals(audio_path)

        log("Step 2: Loading Individual Frames")
        # Load the specific 4 frames requested
        frame_paths = [
            "/app/frame1.png",
            "/app/frame2.png",
            "/app/frame3.png",
            "/app/frame4.png"
        ]
        
        clips = [mpy.ImageClip(f).resize(width=1080) for f in frame_paths]
        idle_clip = clips[0]
        talk_clips = clips[1:] 

        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if is_speaking:
                gesture_idx = int(t / 1.5) % len(talk_clips)
                return talk_clips[gesture_idx].get_frame(0)
            return idle_clip.get_frame(0)

        char_h = idle_clip.h
        base_y = (1920 - char_h) // 2
        char_clip = mpy.VideoClip(make_frame, duration=total_dur).set_position(("center", base_y))
        bg_clip = mpy.ColorClip(size=(1080, 1920), color=(18, 18, 24)).set_duration(total_dur)

        log("Step 3: Subtitles")
        words = script.split()
        text_clips = []
        current_time = 0.0
        for i in range(0, len(words), 6):
            chunk_words = words[i:i + 6]
            chunk_dur = (len(chunk_words) / len(words)) * total_dur
            sub_path = os.path.join(workdir, f"sub_{i}.png")
            create_subtitle_file(" ".join(chunk_words), sub_path)
            text_clips.append(mpy.ImageClip(sub_path).set_duration(chunk_dur).set_start(current_time).set_position(("center", "center")))
            current_time += chunk_dur

        log("Step 4: Compositing")
        final_video = mpy.CompositeVideoClip([bg_clip, char_clip, *text_clips]).set_audio(mpy.AudioFileClip(audio_path))
        final_video.write_videofile(final_video_path, fps=24, codec="libx264", audio_codec="aac", verbose=False, logger=None)

        with open(final_video_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return {"output": {"video_base64": encoded}}

    except Exception as e:
        log("Error:", traceback.format_exc())
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
