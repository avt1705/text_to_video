import os
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
SPRITE_SHEET_PATH = "/app/sprite_sheet.png"

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
    xtts_model.tts_to_file(
        text=script, 
        speaker_wav=VOICE_SAMPLE_PATH, 
        language="hi", 
        file_path=output_path
    )

def get_speaking_intervals(audio_path: str):
    audio = AudioSegment.from_file(audio_path)
    nonsilent = silence.detect_nonsilent(audio, min_silence_len=150, silence_thresh=-40)
    return [(s / 1000.0, e / 1000.0) for s, e in nonsilent], audio.duration_seconds

def split_sprite_sheet(sheet_path, output_dir):
    """Slices the 1x5 grid with safe margins to avoid borders and text."""
    img = Image.open(sheet_path)
    w, h = img.size
    panel_w = w // 5
    
    # Crop higher up (bottom 40% removed) to ensure the text is completely gone
    panel_h = int(h * 0.60) 
    
    # Shave 5% off the top to remove the top white margin
    top_margin = int(h * 0.05)

    frames = []
    for i in range(5):
        raw_left = i * panel_w
        raw_right = (i + 1) * panel_w
        
        # Shave 5% off the left and right sides of each panel to avoid black divider lines
        horizontal_margin = int(panel_w * 0.05)
        
        left = raw_left + horizontal_margin
        right = raw_right - horizontal_margin
        upper = top_margin
        lower = panel_h
        
        cropped = img.crop((left, upper, right, lower))
        out_path = os.path.join(output_dir, f"frame_{i}.png")
        cropped.save(out_path)
        frames.append(out_path)
    return frames

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
    # Place subtitles higher up from the bottom for YouTube Shorts UI
    pos_y = height - text_h - 300 

    # Draw text with a thick black stroke for readability
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

        log("Step 2: Processing Frames (Vertical Format)")
        frame_paths = split_sprite_sheet(SPRITE_SHEET_PATH, workdir)
        
        # Scale frames to fit a 1080p vertical width
        clips = [mpy.ImageClip(f).resize(width=1080) for f in frame_paths]
        idle_clip = clips[0]
        talk_clips = clips[1:] 

        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if is_speaking:
                gesture_idx = int(t / 1.5) % len(talk_clips)
                return talk_clips[gesture_idx].get_frame(0)
            return idle_clip.get_frame(0)

        # Center character in a 1080x1920 frame
        char_h = idle_clip.h
        base_y = (1920 - char_h) // 2
        char_clip = mpy.VideoClip(make_frame, duration=total_dur).set_position(("center", base_y))
        
        # Dark studio background
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
