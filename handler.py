import os
import math
import base64
import textwrap
import traceback
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

# Global variable to hold the AI voice model in GPU memory
xtts_model = None

def log(*args):
    print(*args, flush=True)

# ==========================================
# 1. LOCAL VOICE CLONING (XTTSv2)
# ==========================================
def ensure_tts_loaded():
    """Lazy loads the Coqui XTTSv2 model onto the GPU."""
    global xtts_model
    if xtts_model is None:
        log("Loading XTTSv2 Voice Cloning Model (this takes a moment on first boot)...")
        from TTS.api import TTS
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # Download and load the multilingual model
        xtts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        log(f"Voice model successfully loaded onto {device}.")

def generate_audio(script: str, output_path: str):
    """Generates cloned voice audio entirely locally."""
    try:
        ensure_tts_loaded()
        log("Generating local cloned speech...")
        
        # Generate speech using your baked-in WAV file and specify Hindi ("hi")
        xtts_model.tts_to_file(
            text=script, 
            speaker_wav=VOICE_SAMPLE_PATH, 
            language="hi", 
            file_path=output_path
        )
        log("Audio generated successfully.")
    except Exception as e:
        log("Voice generation failed:", traceback.format_exc())
        raise e

def get_speaking_intervals(audio_path: str):
    audio = AudioSegment.from_file(audio_path)
    nonsilent_ranges = silence.detect_nonsilent(audio, min_silence_len=150, silence_thresh=-40)
    return [(start / 1000.0, end / 1000.0) for start, end in nonsilent_ranges], audio.duration_seconds

# ==========================================
# 2. SUBTITLE GENERATION
# ==========================================
def create_subtitle_file(text: str, filepath: str, width=1280, height=720):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 55)
    except Exception:
        font = ImageFont.load_default()

    wrapped_text = "\n".join(textwrap.wrap(text, width=38))
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=10)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pos_x = (width - text_w) // 2
    pos_y = height - text_h - 60

    draw.multiline_text(
        (pos_x, pos_y), wrapped_text, font=font, fill=(255, 223, 0),
        stroke_width=6, stroke_fill=(0, 0, 0), align="center", spacing=10
    )
    img.save(filepath)

# ==========================================
# 3. RUNPOD HANDLER
# ==========================================
def handler(event):
    try:
        input_data = event.get("input", {})
        script = input_data.get("script", "").strip()

        if not script:
            return {"error": "Missing 'script' input."}

        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        audio_path = os.path.join(workdir, "speech.wav")
        final_video_path = os.path.join(workdir, "final.mp4")

        log("Step 1: Generating Audio...")
        generate_audio(script, audio_path)
        speaking_intervals, total_duration = get_speaking_intervals(audio_path)

        log("Step 2: Preparing Animation...")
        def load_and_scale(path, target_h=600):
            im = Image.open(path).convert("RGBA")
            aspect = im.width / im.height
            target_w = int(target_h * aspect)
            return im.resize((target_w, target_h), Image.Resampling.LANCZOS)

        temp_idle = os.path.join(workdir, "scaled_idle.png")
        temp_talk1 = os.path.join(workdir, "scaled_talk1.png")
        
        load_and_scale("/app/my_scene1.png").save(temp_idle)
        load_and_scale("/app/my_scene2.png").save(temp_talk1)
        
        idle_clip = mpy.ImageClip(temp_idle)
        talk1_clip = mpy.ImageClip(temp_talk1)

        char_w, char_h = idle_clip.size
        base_x = (1280 - char_w) // 2
        base_y = 720 - char_h

        def get_mask_frame(clip):
            if clip.mask is not None:
                return clip.mask.get_frame(0)
            return np.ones((clip.h, clip.w))

        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if is_speaking:
                return talk1_clip.get_frame(0) if int(t / 0.2) % 2 == 0 else idle_clip.get_frame(0)
            return idle_clip.get_frame(0)

        def make_mask(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if is_speaking:
                active_clip = talk1_clip if int(t / 0.2) % 2 == 0 else idle_clip
                return get_mask_frame(active_clip)
            return get_mask_frame(idle_clip)

        def animated_position(t):
            y_offset = math.sin(t * 3) * 6
            return (base_x, base_y + y_offset)

        char_clip = mpy.VideoClip(make_frame, duration=total_duration)
        mask_clip = mpy.VideoClip(make_mask, duration=total_duration, ismask=True)
        char_clip = char_clip.set_mask(mask_clip).set_position(animated_position)
        bg_clip = mpy.ColorClip(size=(1280, 720), color=(18, 18, 24)).set_duration(total_duration)

        log("Step 3: Syncing Subtitles...")
        words = script.split()
        total_words = len(words)
        chunk_size = 7 
        
        text_clips = []
        current_time = 0.0
        
        for i in range(0, total_words, chunk_size):
            chunk_words = words[i:i + chunk_size]
            chunk_text = " ".join(chunk_words)
            chunk_duration = (len(chunk_words) / total_words) * total_duration
            
            sub_path = os.path.join(workdir, f"sub_{i}.png")
            create_subtitle_file(chunk_text, sub_path)
            
            txt_clip = mpy.ImageClip(sub_path).set_duration(chunk_duration).set_start(current_time)
            text_clips.append(txt_clip)
            current_time += chunk_duration

        log("Step 4: Compositing final video...")
        final_video = mpy.CompositeVideoClip([bg_clip, char_clip, *text_clips])
        final_video = final_video.set_audio(mpy.AudioFileClip(audio_path))
        final_video.write_videofile(final_video_path, fps=24, codec="libx264", audio_codec="aac", verbose=False, logger=None)

        with open(final_video_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return {"output": {"video_base64": encoded}}

    except Exception as e:
        log("Error:", traceback.format_exc())
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
