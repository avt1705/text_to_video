import os
import re
import urllib.request
import base64
import textwrap
import traceback
import asyncio
import edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy

SCENE1_PATH = "/app/my_scene1.png" 
SCENE2_PATH = "/app/my_scene2.png" 

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

        audio_path = os.path.join(workdir, "speech.wav") 
        final_video_path = os.path.join(workdir, "final.mp4")

        input_data = event.get("input", {})
        audio_base64 = input_data.get("audio_base64", "")
        
        raw_script = input_data.get("script", "")
        if isinstance(raw_script, bytes):
            raw_script = raw_script.decode("utf-8")
        
        script = raw_script.strip()
        
        if not script and not audio_base64:
            return {"error": "No script or audio provided."}

        subtitle_clips = []
        audio_clips = []

        if audio_base64:
            temp_mp3 = os.path.join(workdir, "uploaded.mp3")
            with open(temp_mp3, "wb") as f:
                f.write(base64.b64decode(audio_base64))
            
            mpy.AudioFileClip(temp_mp3).write_audiofile(audio_path, logger=None)
            audio_dur = mpy.AudioFileClip(audio_path).duration
            
            if script:
                subtitle_clips.append(create_right_side_subtitle(script, audio_dur, 0.0))
        else:
            sentences = [s.strip() for s in re.split(r'[।.\n]+', script) if s.strip()]
            current_time = 0.0
            
            print("Generating human-like line-by-line audio...", flush=True)
            for i, sentence in enumerate(sentences):
                chunk_path = os.path.join(workdir, f"chunk_{i}.mp3")
                
                async def generate_tts():
                    communicate = edge_tts.Communicate(sentence, "hi-IN-MadhurNeural")
                    await communicate.save(chunk_path)
                
                asyncio.run(generate_tts())
                
                audio_chunk = mpy.AudioFileClip(chunk_path)
                dur = audio_chunk.duration
                audio_clips.append(audio_chunk)
                
                subtitle_clips.append(create_right_side_subtitle(sentence, dur, current_time))
                current_time += dur
                
            final_audio = mpy.concatenate_audioclips(audio_clips)
            final_audio.write_audiofile(audio_path, logger=None) 

        for path in [SCENE1_PATH, SCENE2_PATH]:
            if not os.path.exists(path):
                return {"error": f"Missing frame asset. Checked {path}"}

        print("Analyzing audio volume for 2-frame lip-sync...", flush=True)
        audio_clip = mpy.AudioFileClip(audio_path)
        total_dur = audio_clip.duration
        audio_fps = audio_clip.fps # Get the native audio sample rate (e.g., 24000 or 44100)
        
        # Load the array without forcing the broken 24Hz reading
        audio_array = audio_clip.to_soundarray()
        
        if audio_array.ndim == 2:
            audio_array = np.max(np.abs(audio_array), axis=1) 
        else:
            audio_array = np.abs(audio_array)

        f1 = mpy.ImageClip(SCENE1_PATH).resize(height=1080).get_frame(0)
        f2 = mpy.ImageClip(SCENE2_PATH).resize(height=1080).get_frame(0)

        # Calculate how many audio samples correspond to one video frame (1/24th of a second)
        samples_per_frame = int(audio_fps / 24)

        def make_frame(t):
            sample_idx = int(t * audio_fps)
            
            # Create a window to capture the peak volume around this exact timestamp
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

        print("Compositing 1920x1080 final layout...", flush=True)
        bg_clip = mpy.ColorClip(size=(1920, 1080), color=(15, 23, 42), duration=total_dur)
        
        final_clip = mpy.CompositeVideoClip([bg_clip, avatar_clip, *subtitle_clips], size=(1920, 1080))
        final_clip = final_clip.set_audio(audio_clip)

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
    print("Starting 2-Frame Animation Worker...", flush=True)
    runpod.serverless.start({"handler": handler})
