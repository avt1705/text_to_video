import os
import re
import urllib.request
import base64
import textwrap
import traceback
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy

SCENE1_PATH = "/app/my_scene1.png"  # Closed mouth (Silence)
SCENE2_PATH = "/app/my_scene2.png"  # Open mouth (Talking)

# ================= CREDENTIALS (SECURE) =================
# Automatically reads from RunPod Environment Variables
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
# ========================================================

def get_hindi_font(size=46):
    font_path = "/tmp/runpod_job/NotoSansDevanagari-Regular.ttf"
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 50000:
        print("Downloading Hindi font...", flush=True)
        url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
        urllib.request.urlretrieve(url, font_path)
    return ImageFont.truetype(font_path, size)

def create_right_side_subtitle(text, duration, start_time):
    width, height = 960, 1080
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = get_hindi_font(46)
    wrapped = "\n".join(textwrap.wrap(text, width=35))
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=15)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.multiline_text(
        ((width - text_w) // 2, (height - text_h) // 2),
        wrapped, font=font, fill=(255, 255, 255), align="center", spacing=15
    )
    return (mpy.ImageClip(np.array(img))
            .set_duration(duration)
            .set_start(start_time)
            .set_position(("right", "center")))

def handler(event):
    try:
        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        final_video_path = os.path.join(workdir, "final.mp4")

        input_data = event.get("input", {})
        raw_script = input_data.get("script", "")
        if isinstance(raw_script, bytes):
            raw_script = raw_script.decode("utf-8")
        script = raw_script.strip()
        
        if not script:
            return {"error": "No script provided."}

        # Allow overriding via payload, otherwise fall back to environment variable
        api_key = input_data.get("api_key") or ELEVENLABS_API_KEY
        voice_id = input_data.get("voice_id") or VOICE_ID

        if not api_key:
            return {"error": "ELEVENLABS_API_KEY not configured in RunPod Environment Variables or input payload."}
        if not voice_id:
            return {"error": "ELEVENLABS_VOICE_ID not configured in RunPod Environment Variables or input payload."}

        subtitle_clips = []
        audio_clips = []
        
        sentences = [s.strip() for s in re.split(r'[।.\n]+', script) if s.strip()]
        current_time = 0.0

        print(f"Generating ElevenLabs audio for {len(sentences)} lines...", flush=True)
        audio_path = os.path.join(workdir, "speech.wav")
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key
        }

        for i, sentence in enumerate(sentences):
            chunk_path = os.path.join(workdir, f"chunk_{i}.mp3")
            
            payload = {
                "text": sentence,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            resp = requests.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                return {"error": f"ElevenLabs API Error: {resp.status_code} - {resp.text}"}
                
            with open(chunk_path, "wb") as f:
                f.write(resp.content)
            
            audio_chunk = mpy.AudioFileClip(chunk_path)
            dur = audio_chunk.duration
            audio_clips.append(audio_chunk)
            
            subtitle_clips.append(create_right_side_subtitle(sentence, dur, current_time))
            current_time += dur

        final_audio = mpy.concatenate_audioclips(audio_clips)
        final_audio.write_audiofile(audio_path, logger=None)
        audio_clip = mpy.AudioFileClip(audio_path)
        total_dur = audio_clip.duration
        audio_fps = audio_clip.fps

        print("Analyzing audio volume for lip-sync...", flush=True)
        audio_array = audio_clip.to_soundarray()
        if audio_array.ndim == 2:
            audio_array = np.max(np.abs(audio_array), axis=1)
        else:
            audio_array = np.abs(audio_array)

        f1 = mpy.ImageClip(SCENE1_PATH).resize(height=1080).get_frame(0)
        f2 = mpy.ImageClip(SCENE2_PATH).resize(height=1080).get_frame(0)
        samples_per_frame = int(audio_fps / 24)

        def make_frame(t):
            sample_idx = int(t * audio_fps)
            start_idx = max(0, sample_idx - (samples_per_frame // 2))
            end_idx = min(len(audio_array), sample_idx + (samples_per_frame // 2))
            if start_idx >= end_idx:
                return f1
            vol = np.max(audio_array[start_idx:end_idx])
            return f2 if vol >= 0.04 else f1

        avatar_clip = mpy.VideoClip(make_frame, duration=total_dur).set_position(("left", "center"))
        bg_clip = mpy.ColorClip(size=(1920, 1080), color=(15, 23, 42), duration=total_dur)
        
        final_clip = mpy.CompositeVideoClip(
            [bg_clip, avatar_clip, *subtitle_clips],
            size=(1920, 1080)
        ).set_audio(audio_clip)

        final_clip.write_videofile(
            final_video_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
            verbose=False
        )

        with open(final_video_path, "rb") as f:
            encoded_video = base64.b64encode(f.read()).decode("utf-8")

        return {"output": {"video_base64": encoded_video}}

    except Exception as e:
        print(f"Execution Error: {e}", flush=True)
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
