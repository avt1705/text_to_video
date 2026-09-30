import os
import re
import urllib.request
import base64
import textwrap
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy

SCENE1_PATH = "/app/my_scene1.png" # Closed mouth (Silence)
SCENE2_PATH = "/app/my_scene2.png" # Open mouth (Talking)

def get_hindi_font(size=46):
    font_path = "/tmp/runpod_job/NotoSansDevanagari-Regular.ttf"
    
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 50000:
        print("Downloading clean Hindi font...", flush=True)
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
        wrapped,
        font=font,
        fill=(255, 255, 255),
        align="center",
        spacing=15
    )
    
    return (mpy.ImageClip(np.array(img))
            .set_duration(duration)
            .set_start(start_time)
            .set_position(("right", "center")))

def handler(event):
    try:
        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)

        audio_path = os.path.join(workdir, "raw_voice.wav") 
        final_video_path = os.path.join(workdir, "final.mp4")

        input_data = event.get("input", {})
        audio_base64 = input_data.get("audio_base64", "")
        
        raw_script = input_data.get("script", "")
        if isinstance(raw_script, bytes):
            raw_script = raw_script.decode("utf-8")
        
        script = raw_script.strip()
        
        if not script or not audio_base64:
            return {"error": "Both script and audio_base64 are required."}

        # 1. Load Custom Audio WITHOUT Re-encoding
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_base64))
            
        audio_clip = mpy.AudioFileClip(audio_path)
        total_dur = audio_clip.duration
        audio_fps = audio_clip.fps 
        
        # 2. Proportional Line-by-Line Subtitle Sync
        subtitle_clips = []
        sentences = [s.strip() for s in re.split(r'[।.\n]+', script) if s.strip()]
        current_time = 0.0
        
        total_chars = sum(len(s) for s in sentences)
        
        for sentence in sentences:
            if total_chars == 0:
                break
            # Mathematically divide the screen time based on sentence length
            dur = (len(sentence) / total_chars) * total_dur
            subtitle_clips.append(create_right_side_subtitle(sentence, dur, current_time))
            current_time += dur

        # 3. Verify Frame Assets
        for path in [SCENE1_PATH, SCENE2_PATH]:
            if not os.path.exists(path):
                return {"error": f"Missing frame asset. Checked {path}"}

        # 4. Audio Volume Analysis for 2-Frame Animation
        print("Analyzing raw audio volume for 2-frame lip-sync...", flush=True)
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
            
            if vol < 0.04:  
                return f1
            else:             
                return f2

        avatar_clip = (mpy.VideoClip(make_frame, duration=total_dur)
                       .set_position(("left", "center")))

        # 5. Composite 1920x1080 Final Layout
        print("Compositing 1920x1080 final layout...", flush=True)
        bg_clip = mpy.ColorClip(size=(1920, 1080), color=(15, 23, 42), duration=total_dur)
        
        final_clip = mpy.CompositeVideoClip([bg_clip, avatar_clip, *subtitle_clips], size=(1920, 1080))
        final_clip = final_clip.set_audio(audio_clip)

        # 6. Render and Encode
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
        print(f"Execution Error Occurred: {e}", flush=True)
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    print("Starting Raw Audio Video Worker...", flush=True)
    runpod.serverless.start({"handler": handler})
