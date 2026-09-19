import os
import re
import base64
import textwrap
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy
from pydub import AudioSegment, silence

FONT_PATH = "/app/NotoSansDevanagari.ttf"

def log(*args):
    print(*args, flush=True)

def split_sentences(text: str):
    parts = re.split(r'[।.!?\n]+', text)
    return [p.strip() for p in parts if p.strip()]

def create_subtitle_frame(text: str, width=1280, height=200):
    img = Image.new("RGBA", (width, height), (10, 15, 25, 230))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 42)
    except Exception:
        font = ImageFont.load_default()

    wrapped_text = "\n".join(textwrap.wrap(text, width=45))
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=10)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pos_x = (width - text_w) // 2
    pos_y = (height - text_h) // 2

    draw.multiline_text((pos_x, pos_y), wrapped_text, font=font, fill=(255, 255, 255), align="center", spacing=10)
    return np.array(img)

def handler(event):
    try:
        input_data = event.get("input", {})
        script = input_data.get("script", "").strip()
        audio_b64 = input_data.get("audio_base64", "")

        if not script or not audio_b64:
            return {"error": "Missing script or audio inputs."}

        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        
        audio_path = os.path.join(workdir, "speech.mp3")
        video_output_path = os.path.join(workdir, "final.mp4")

        # 1. Decode & Save Audio
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_b64))
            
        audio_segment = AudioSegment.from_file(audio_path)
        total_duration = audio_segment.duration_seconds

        # 2. Setup Avatar Clips (Loading from the Docker /app/ folder)
        # We explicitly look for frame1.png as the idle/silent frame
        idle_path = "/app/frame1.png"
        
        if not os.path.exists(idle_path):
            return {"error": f"Could not find {idle_path} inside the container. Check that the file on GitHub is exactly named 'frame1.png' (lowercase)."}

        idle_clip = mpy.ImageClip(idle_path).resize(height=720)
        
        # Look for frame2.png, frame3.png, frame4.png for talking animations
        talk_paths = []
        for i in range(2, 6): 
            f_path = f"/app/frame{i}.png"
            if os.path.exists(f_path):
                talk_paths.append(f_path)
                
        # If no other frames are found, make a fake talking frame by shifting frame1
        if not talk_paths:
            base_img = Image.open(idle_path)
            shifted = base_img.crop((0, 10, base_img.width, base_img.height)).resize((base_img.width, base_img.height))
            shifted_path = os.path.join(workdir, "shifted.png")
            shifted.save(shifted_path)
            talk_clips = [idle_clip, mpy.ImageClip(shifted_path).resize(height=720)]
        else:
            talk_clips = [mpy.ImageClip(p).resize(height=720) for p in talk_paths]

        # 3. Extract Speaking Intervals
        non_silent_ranges = silence.detect_nonsilent(
            audio_segment, min_silence_len=300, silence_thresh=audio_segment.dBFS - 14
        )
        speaking_intervals = [(start / 1000.0, end / 1000.0) for start, end in non_silent_ranges]

        # 4. Audio-Reactive Logic
        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if not is_speaking:
                return idle_clip.get_frame(0)
                
            ms = int(t * 1000)
            chunk = audio_segment[max(0, ms-50) : ms+50]
            volume = chunk.rms 
            
            if volume > 3500:       
                dynamic_interval = 0.2
            elif volume > 1000:     
                dynamic_interval = 0.4
            else:                   
                dynamic_interval = 0.7
                
            frame_idx = int((t / dynamic_interval) % len(talk_clips))
            return talk_clips[frame_idx].get_frame(0)

        avatar_clip = mpy.VideoClip(make_frame, duration=total_duration).set_position(("center", "center"))
        bg_clip = mpy.ColorClip(size=(1280, 720), color=(0, 0, 0)).set_duration(total_duration)

        # 5. Process Subtitles
        chunks = silence.split_on_silence(
            audio_segment, min_silence_len=400, silence_thresh=audio_segment.dBFS - 14, keep_silence=200
        )
        if not chunks:
            chunks = [audio_segment]

        sentences = split_sentences(script)
        subtitle_clips = []
        current_time = 0.0
        
        for idx, chunk in enumerate(chunks):
            duration = chunk.duration_seconds
            subtitle_text = sentences[idx] if idx < len(sentences) else ""
            
            if subtitle_text:
                sub_frame = create_subtitle_frame(subtitle_text)
                sub_clip = (
                    mpy.ImageClip(sub_frame)
                    .set_duration(duration)
                    .set_start(current_time)
                    .set_position(("center", "bottom"))
                )
                subtitle_clips.append(sub_clip)
            current_time += duration

        # 6. Compose & Render
        final_video = mpy.CompositeVideoClip([bg_clip, avatar_clip, *subtitle_clips])
        final_video = final_video.set_audio(mpy.AudioFileClip(audio_path))

        log("Encoding output MP4...")
        final_video.write_videofile(
            video_output_path, fps=24, codec="libx264", audio_codec="aac",
            ffmpeg_params=["-crf", "26", "-preset", "fast"], verbose=False, logger=None
        )

        with open(video_output_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return {"output": {"video_base64": encoded}}

    except Exception as e:
        log("Error in handler execution:", traceback.format_exc())
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
