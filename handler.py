import os
import base64
import traceback
import runpod
import numpy as np

from gtts import gTTS

from PIL import Image, ImageDraw, ImageFont

from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip
)


# ================= CONFIGURATION =================

WIDTH = 1920
HEIGHT = 1080
FPS = 30

SCENE1_PATH = "/app/my_scene1.png"
SCENE2_PATH = "/app/my_scene2.png"

AUDIO_PATH = "/tmp/narration.mp3"
OUTPUT_PATH = "/tmp/final_video.mp4"


# ================= HINDI FONT =================

def get_hindi_font():

    paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf"
    ]

    for path in paths:

        if os.path.exists(path):
            return path

    raise RuntimeError("Hindi font not found.")


# ================= SUBTITLE IMAGE =================

def create_subtitle_image(text):

    image = Image.new(
        "RGBA",
        (960, HEIGHT),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    font = ImageFont.truetype(
        get_hindi_font(),
        54
    )

    draw.rounded_rectangle(
        (50, 300, 910, 780),
        radius=35,
        fill=(15, 23, 42, 235)
    )

    words = text.split()

    lines = []
    current = ""

    for word in words:

        test = (current + " " + word).strip()

        if draw.textlength(test, font=font) < 750:

            current = test

        else:

            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    line_height = 85

    total_height = len(lines) * line_height

    y = (HEIGHT - total_height) // 2

    for line in lines:

        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font
        )

        text_width = bbox[2] - bbox[0]

        x = (960 - text_width) // 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill="white"
        )

        y += line_height

    return np.array(image)


# ================= AUDIO ANALYSIS =================

def analyze_audio(audio_clip):

    sample_rate = 8000

    audio = audio_clip.to_soundarray(
        fps=sample_rate
    )

    if audio.ndim == 2:
        audio = np.mean(audio, axis=1)

    samples_per_frame = max(
        1,
        int(sample_rate / FPS)
    )

    envelope = []

    for start in range(
        0,
        len(audio),
        samples_per_frame
    ):

        chunk = audio[start:start + samples_per_frame]

        if len(chunk):

            rms = np.sqrt(
                np.mean(chunk ** 2)
            )

            envelope.append(rms)

    return envelope


# ================= AVATAR ANIMATION =================

def create_avatar(envelope, duration):

    closed = Image.open(
        SCENE1_PATH
    ).convert("RGBA")

    opened = Image.open(
        SCENE2_PATH
    ).convert("RGBA")

    closed.thumbnail((900, 950))

    opened = opened.resize(
        closed.size,
        Image.Resampling.LANCZOS
    )

    closed_array = np.array(closed)
    opened_array = np.array(opened)

    avatar_width, avatar_height = closed.size

    x = (960 - avatar_width) // 2
    y = (HEIGHT - avatar_height) // 2

    clips = []

    current_state = None
    segment_start = 0

    frame_count = min(
        len(envelope),
        int(duration * FPS) + 1
    )

    for frame in range(frame_count):

        state = (
            "open"
            if envelope[frame] > 0.015
            else "closed"
        )

        if current_state is None:

            current_state = state
            segment_start = frame

        elif state != current_state:

            image = (
                opened_array
                if current_state == "open"
                else closed_array
            )

            start = segment_start / FPS
            end = frame / FPS

            clip = (
                ImageClip(image)
                .set_start(start)
                .set_duration(end - start)
                .set_position((x, y))
            )

            clips.append(clip)

            current_state = state
            segment_start = frame

    if current_state is not None:

        image = (
            opened_array
            if current_state == "open"
            else closed_array
        )

        start = segment_start / FPS

        clip = (
            ImageClip(image)
            .set_start(start)
            .set_duration(max(0.01, duration - start))
            .set_position((x, y))
        )

        clips.append(clip)

    return clips


# ================= MAIN HANDLER =================

def handler(event):

    audio_clip = None
    final_video = None

    try:

        input_data = event.get("input", {})

        script = input_data.get("script")

        if not script or not script.strip():

            return {"error": "No script provided."}

        if not os.path.exists(SCENE1_PATH):
            return {"error": "Closed-mouth avatar image missing."}

        if not os.path.exists(SCENE2_PATH):
            return {"error": "Open-mouth avatar image missing."}

        # STEP 1: Generate Hindi voice

        tts = gTTS(
            text=script,
            lang="hi",
            slow=False
        )

        tts.save(AUDIO_PATH)

        # STEP 2: Load audio

        audio_clip = AudioFileClip(AUDIO_PATH)

        duration = audio_clip.duration

        if duration <= 0:
            raise RuntimeError("Invalid audio duration.")

        # STEP 3: Analyze voice

        envelope = analyze_audio(audio_clip)

        # STEP 4: Background

        background = ColorClip(
            size=(WIDTH, HEIGHT),
            color=(15, 23, 42)
        ).set_duration(duration)

        # STEP 5: Avatar

        avatar_clips = create_avatar(
            envelope,
            duration
        )

        # STEP 6: Subtitles

        lines = [
            line.strip()
            for line in script.splitlines()
            if line.strip()
        ]

        if not lines:
            lines = [script.strip()]

        total_chars = sum(
            len(line)
            for line in lines
        )

        subtitle_clips = []

        current_time = 0

        for line in lines:

            line_duration = (
                duration * len(line) / total_chars
            )

            subtitle_image = create_subtitle_image(line)

            subtitle = (
                ImageClip(subtitle_image)
                .set_start(current_time)
                .set_duration(line_duration)
                .set_position((960, 0))
            )

            subtitle_clips.append(subtitle)

            current_time += line_duration

        # STEP 7: Combine

        final_video = CompositeVideoClip(
            [
                background,
                *avatar_clips,
                *subtitle_clips
            ],
            size=(WIDTH, HEIGHT)
        )

        final_video = final_video.set_audio(audio_clip)

        # STEP 8: Render

        final_video.write_videofile(
            OUTPUT_PATH,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="1800k",
            preset="ultrafast",
            threads=4,
            logger=None
        )

        # STEP 9: Return video to frontend

        with open(OUTPUT_PATH, "rb") as f:

            video_base64 = base64.b64encode(
                f.read()
            ).decode("utf-8")

        return {
            "video_base64": video_base64,
            "duration": duration,
            "resolution": "1920x1080",
            "fps": FPS
        }

    except Exception as e:

        traceback.print_exc()

        return {
            "error": str(e)
        }

    finally:

        if final_video:
            final_video.close()

        if audio_clip:
            audio_clip.close()


# ================= RUNPOD START =================

runpod.serverless.start({
    "handler": handler
})
