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
from gtts import gTTS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def find_file(filename):
    """Searches multiple paths so assets are located regardless of mount location."""
    search_paths = [
        os.path.join(BASE_DIR, filename),
        os.path.join("/app", filename),
        os.path.join(os.getcwd(), filename)
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return None


def get_speaking_intervals(audio_path):
    """Detects speaking vs silence intervals in the audio using pydub."""
    audio = AudioSegment.from_file(audio_path)
    total_dur = len(audio) / 1000.0
    nonsilent_ranges = silence.detect_nonsilent(
        audio,
        min_silence_len=200,
        silence_thresh=audio.dBFS - 16
    )
    if not nonsilent_ranges:
        return [(0.0, total_dur)], total_dur
    intervals = [(start / 1000.0, end / 1000.0) for start, end in nonsilent_ranges]
    return intervals, total_dur


def create_subtitle_clip(text, duration, font_path):
    """Renders wrapped Hindi Devanagari text on a semi-transparent slate banner."""
    width, height = 1080, 180
    img = Image.new("RGBA", (width, height), (15, 23, 42, 220))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    wrapped = "\n".join(textwrap.wrap(text, width=42))
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=6)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    draw.multiline_text(
        ((width - text_w) // 2, (height - text_h) // 2),
        wrapped,
        font=font,
        fill=(255, 255, 255),
        align="center",
        spacing=6
    )
    return mpy.ImageClip(np.array(img)).set_duration(duration).set_position(("center", "bottom"))


def handler(event):
    try:
        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)

        audio_path = os.path.join(workdir, "speech.mp3")
        final_video_path = os.path.join(workdir, "final.mp4")

        input_data = event.get("input", {})
        audio_base64 = input_data.get("audio_base64", "")
        script = input_data.get("script", "").strip()

        # Step 1: Obtain Audio (via Base64 or gTTS synthesis)
        if audio_base64:
            with open(audio_path, "wb") as f:
                f.write(base64.b64decode(audio_base64))
        elif script:
            print("Synthesizing Hindi TTS from script...", flush=True)
            tts = gTTS(text=script, lang="hi", slow=False)
            tts.save(audio_path)
        else:
            default_voice = find_file("my_voice.wav")
            if default_voice:
                audio_path = default_voice
            else:
                return {"error": "No 'script' or 'audio_base64' provided, and my_voice.wav is missing."}

        # Step 2: Detect Speech Intervals
        speaking_intervals, total_dur = get_speaking_intervals(audio_path)

        # Step 3: Locate Frame Assets
        frame_files = ["frame1.png", "frame2.png", "frame3.png", "frame4.png"]
        resolved_frames = []
        for name in frame_files:
            resolved = find_file(name)
            if not resolved:
                return {"error": f"Missing frame asset: {name}"}
            resolved_frames.append(resolved)

        clips = [mpy.ImageClip(f).resize(width=1080) for f in resolved_frames]
        idle_clip = clips[0]
        talk_clips = clips[1:]

        # Step 4: Animate Avatar Based on Speech
        def make_frame(t):
            is_speaking = any(start <= t <= end for start, end in speaking_intervals)
            if is_speaking:
                # Slower animation interval (0.4) applied here to stop rapid frame switching
                frame_idx = int((t / 0.4) % len(talk_clips))
                return talk_clips[frame_idx].get_frame(0)
            return idle_clip.get_frame(0)

        avatar_clip = mpy.VideoClip(make_frame, duration=total_dur)

        # Step 5: Optional Subtitle Overlay
        font_path = find_file("NotoSansDevanagari.ttf")
        if script and font_path:
            sub_clip = create_subtitle_clip(script, total_dur, font_path)
            final_clip = mpy.CompositeVideoClip([avatar_clip, sub_clip])
        else:
            final_clip = avatar_clip

        # Step 6: Render and Encode Output
        final_video = final_clip.set_audio(mpy.AudioFileClip(audio_path))
        final_video.write_videofile(
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
        print("Execution Error:", traceback.format_exc(), flush=True)
        return {"error": str(e), "trace": traceback.format_exc()}


if __name__ == "__main__":
    print("Starting RunPod Serverless Handler...", flush=True)
    runpod.serverless.start({"handler": handler})
