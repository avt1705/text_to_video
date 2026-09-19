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

def create_subtitle_frame(text: str, width=1280, height=180):
    img = Image.new("RGBA", (width, height), (15, 23, 42, 220))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, 36)
    except Exception:
        font = ImageFont.load_default()

    wrapped_text = "\n".join(textwrap.wrap(text, width=45))
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=8)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pos_x = (width - text_w) // 2
    pos_y = (height - text_h) // 2

    draw.multiline_text(
        (pos_x, pos_y),
        wrapped_text,
        font=font,
        fill=(255, 255, 255),
        align="center",
        spacing=8
    )
    return np.array(img)

def ensure_avatar_frames(workdir):
    """
    Creates a simulated set of frames to mimic talking if custom frames aren't provided.
    In a full production environment, replace these with actual avatar mouth frames.
    """
    idle_path = os.path.join(workdir, "idle.png")
    talk_path_1 = os.path.join(workdir, "talk1.png")
    talk_path_2 = os.path.join(workdir, "talk2.png")
    
    # Generate basic placeholder avatar frames for the demonstration
    base_img = Image.new("RGB", (720, 720), color=(30, 41, 59))
    draw = ImageDraw.Draw(base_img)
    try:
        font = ImageFont.truetype(FONT_PATH, 40)
    except:
        font = ImageFont.load_default()
        
    draw.text((260, 320), "AI Instructor", font=font, fill=(255, 255, 255))
    base_img.save(idle_path)
    
    # Simulate movement for talk frames by shifting pixels slightly
    base_img.crop((0, 10, 720, 720)).resize((720, 720)).save(talk_path_1)
    base_img.crop((0, 20, 720, 720)).resize((720, 720)).save(talk_path_2)
    
    return idle_path, [talk_path_1, talk_path_2]

def handler(event):
    try:
        input_data = event.get("input", {})
        script = input_data.get("script", "").strip()
        audio_b64 = input_data.get("audio_base64", "")

        if not script or not audio_b64:
            return {"error": "Missing 'script' or 'audio_base64' input."}

        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        audio_path = os.path.join(workdir, "speech.mp3")
        video_output_path = os.path.join(workdir, "final.mp4")

        # 1. Save injected audio
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_b64))

        audio_segment = AudioSegment.from_file(audio_path)
        total_duration = audio_segment.duration_seconds

        # 2. Extract speaking intervals for audio-reactive logic
        # Find non-silent chunks to know exactly when the AI is speaking
        non_silent_ranges = silence.detect_nonsilent(
            audio_segment,
            min_silence_len=300,
            silence_thresh=audio_segment.dBFS - 14
        )
        # Convert ms to seconds
        speaking_intervals = [(start / 1000.0, end / 1000.0) for start, end in non_silent_ranges]

        # 3. Prepare Image Clips
        idle_img, talk_imgs = ensure_avatar_frames(workdir)
        idle_clip = mpy.ImageClip(idle_img)
        talk_clips = [mpy.ImageClip(img) for img in talk_imgs]

        # 4. Auto-Adjusting Audio-Reactive Frame Generator
        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if not is_speaking:
                return idle_clip.get_frame(0)
                
            ms = int(t * 1000)
            chunk = audio_segment[max(0, ms-50) : ms+50]
            volume = chunk.rms 
            
            # Dynamic interval switching based on loudness
            if volume > 3500:       
                dynamic_interval = 0.2  # Fast
            elif volume > 1000:     
                dynamic_interval = 0.4  # Medium
            else:                   
                dynamic_interval = 0.7  # Slow
                
            frame_idx = int((t / dynamic_interval) % len(talk_clips))
            return talk_clips[frame_idx].get_frame(0)

        # Apply custom frame generator to a base VideoClip
        avatar_video = mpy.VideoClip(make_frame, duration=total_duration).set_position(("center", "center"))

        # 5. Build Subtitles
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
                    .set_position(("center", 520))
                )
                subtitle_clips.append(sub_clip)
            current_time += duration

        # 6. Compose and Render
        bg_clip = mpy.ColorClip(size=(1280, 720), color=(15, 23, 42)).set_duration(total_duration)
        final_video = mpy.CompositeVideoClip([bg_clip, avatar_video, *subtitle_clips])
        final_video = final_video.set_audio(mpy.AudioFileClip(audio_path))

        log("Encoding output MP4...")
        final_video.write_videofile(
            video_output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            ffmpeg_params=["-crf", "26", "-preset", "fast"],
            verbose=False,
            logger=None
        )

        with open(video_output_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return {"output": {"video_base64": encoded}}

    except Exception as e:
        log("Error in handler execution:", traceback.format_exc())
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
