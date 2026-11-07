import os
import re
import base64
import traceback
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import runpod
import moviepy.editor as mpy


# ==========================================
# CONFIGURATION
# ==========================================

SCENE1_PATH = "/app/my_scene1.png"
SCENE2_PATH = "/app/my_scene2.png"

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30

WORKDIR = "/tmp/runpod_job"

FONT_PATH = os.path.join(
    WORKDIR,
    "NotoSansDevanagari-Regular.ttf"
)


# ==========================================
# HINDI FONT
# ==========================================

def get_hindi_font(size=48):

    os.makedirs(WORKDIR, exist_ok=True)

    if not os.path.exists(FONT_PATH):

        print("Downloading Hindi font...", flush=True)

        url = (
            "https://raw.githubusercontent.com/"
            "google/fonts/main/ofl/notosansdevanagari/"
            "NotoSansDevanagari%5Bwght%5D.ttf"
        )

        urllib.request.urlretrieve(url, FONT_PATH)

    return ImageFont.truetype(FONT_PATH, size)


# ==========================================
# SPLIT SUBTITLES
# ==========================================

def split_script(script):

    sentences = [
        s.strip()
        for s in re.split(r"[।.!?\n]+", script)
        if s.strip()
    ]

    chunks = []

    for sentence in sentences:

        words = sentence.split()

        current_line = []

        for word in words:

            test_line = " ".join(current_line + [word])

            if len(test_line) > 38 and current_line:

                chunks.append(" ".join(current_line))

                current_line = [word]

            else:

                current_line.append(word)

        if current_line:

            chunks.append(" ".join(current_line))

    return chunks


# ==========================================
# CREATE SUBTITLE IMAGE
# ==========================================

def create_subtitle_image(text):

    width = 850
    height = 420

    img = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    # Rounded dark subtitle panel

    draw.rounded_rectangle(
        (15, 15, width - 15, height - 15),
        radius=35,
        fill=(10, 18, 35, 225)
    )

    font = get_hindi_font(48)

    words = text.split()

    lines = []
    current = ""

    for word in words:

        test = current + " " + word if current else word

        if len(test) > 25 and current:

            lines.append(current)
            current = word

        else:

            current = test

    if current:
        lines.append(current)

    final_text = "\n".join(lines)

    bbox = draw.multiline_textbbox(
        (0, 0),
        final_text,
        font=font,
        spacing=22,
        align="center"
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (width - text_width) // 2
    y = (height - text_height) // 2

    draw.multiline_text(
        (x, y),
        final_text,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=22,
        align="center",
        stroke_width=1,
        stroke_fill=(0, 0, 0)
    )

    return np.array(img)


# ==========================================
# CREATE SUBTITLE CLIPS
# ==========================================

def create_subtitles(script, total_duration):

    chunks = split_script(script)

    if not chunks:
        return []

    # Allocate duration proportionally to text length

    weights = [max(len(text), 1) for text in chunks]

    total_weight = sum(weights)

    subtitle_clips = []

    current_time = 0

    for text, weight in zip(chunks, weights):

        duration = total_duration * weight / total_weight

        subtitle_image = create_subtitle_image(text)

        clip = (
            mpy.ImageClip(subtitle_image)
            .set_duration(duration)
            .set_start(current_time)
            .set_position((1010, 330))
        )

        subtitle_clips.append(clip)

        current_time += duration

    return subtitle_clips


# ==========================================
# MAIN HANDLER
# ==========================================

def handler(event):

    try:

        os.makedirs(WORKDIR, exist_ok=True)

        final_video_path = os.path.join(
            WORKDIR,
            "final.mp4"
        )

        audio_path = os.path.join(
            WORKDIR,
            "input_speech.mp3"
        )

        input_data = event.get("input", {})

        # ----------------------------------
        # 1. LOAD AUDIO
        # ----------------------------------

        audio_b64 = input_data.get("audio_base64", "")

        if not audio_b64:

            return {
                "error": "Missing audio_base64"
            }

        with open(audio_path, "wb") as f:

            f.write(base64.b64decode(audio_b64))

        audio_clip = mpy.AudioFileClip(audio_path)

        total_duration = audio_clip.duration

        # ----------------------------------
        # 2. LOAD SCRIPT
        # ----------------------------------

        raw_script = input_data.get("script", "")

        if isinstance(raw_script, bytes):

            raw_script = raw_script.decode("utf-8")

        script = raw_script.strip()

        subtitle_clips = create_subtitles(
            script,
            total_duration
        )

        # ----------------------------------
        # 3. LOAD AVATAR FRAMES
        # ----------------------------------

        scene1 = (
            mpy.ImageClip(SCENE1_PATH)
            .resize(height=950)
            .get_frame(0)
        )

        scene2 = (
            mpy.ImageClip(SCENE2_PATH)
            .resize(height=950)
            .get_frame(0)
        )

        # ----------------------------------
        # 4. ANALYZE AUDIO
        # ----------------------------------

        print(
            "Analyzing audio for avatar animation...",
            flush=True
        )

        audio_array = audio_clip.to_soundarray()

        if audio_array.ndim == 2:

            audio_array = np.mean(
                audio_array,
                axis=1
            )

        audio_array = np.abs(audio_array)

        samples_per_frame = int(
            audio_clip.fps / VIDEO_FPS
        )

        def make_frame(t):

            sample_idx = int(
                t * audio_clip.fps
            )

            start_idx = max(
                0,
                sample_idx - samples_per_frame // 2
            )

            end_idx = min(
                len(audio_array),
                sample_idx + samples_per_frame // 2
            )

            if start_idx >= end_idx:

                return scene1

            segment = audio_array[
                start_idx:end_idx
            ]

            rms = np.sqrt(
                np.mean(segment ** 2)
            )

            if rms > 0.025:

                return scene2

            return scene1

        # ----------------------------------
        # 5. CREATE BACKGROUND
        # ----------------------------------

        bg_clip = mpy.ColorClip(
            size=(VIDEO_WIDTH, VIDEO_HEIGHT),
            color=(15, 23, 42),
            duration=total_duration
        )

        # ----------------------------------
        # 6. CREATE AVATAR
        # ----------------------------------

        avatar_clip = (
            mpy.VideoClip(
                make_frame,
                duration=total_duration
            )
            .set_position((40, 65))
        )

        # ----------------------------------
        # 7. COMBINE EVERYTHING
        # ----------------------------------

        final_clip = mpy.CompositeVideoClip(
            [
                bg_clip,
                avatar_clip,
                *subtitle_clips
            ],
            size=(VIDEO_WIDTH, VIDEO_HEIGHT)
        ).set_audio(audio_clip)

        # ----------------------------------
        # 8. EXPORT VIDEO
        # ----------------------------------

        print(
            "Rendering final video...",
            flush=True
        )

        final_clip.write_videofile(
            final_video_path,
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            bitrate="6000k",
            logger=None,
            verbose=False
        )

        # ----------------------------------
        # 9. RETURN VIDEO
        # ----------------------------------

        with open(final_video_path, "rb") as f:

            encoded_video = base64.b64encode(
                f.read()
            ).decode("utf-8")

        final_clip.close()
        audio_clip.close()

        return {
            "output": {
                "video_base64": encoded_video,
                "duration": total_duration,
                "resolution": "1920x1080",
                "fps": VIDEO_FPS
            }
        }

    except Exception as e:

        print(
            f"Execution Error: {e}",
            flush=True
        )

        return {
            "error": str(e),
            "trace": traceback.format_exc()
        }


if __name__ == "__main__":

    runpod.serverless.start({
        "handler": handler
    })
