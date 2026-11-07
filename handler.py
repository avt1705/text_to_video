import os
import glob
import base64
import traceback

import numpy as np
import runpod

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

OUTPUT_PATH = "/tmp/final_video.mp4"
AUDIO_PATH = "/tmp/narration.mp3"

# =================================================


# ================= HINDI FONT =================

def get_hindi_font():

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf"
    ]

    for path in font_paths:

        if os.path.exists(path):
            return path

    matches = glob.glob(
        "/usr/share/fonts/**/*Devanagari*.ttf",
        recursive=True
    )

    if matches:
        return matches[0]

    raise RuntimeError(
        "Hindi font not found. Please check fonts-noto in Dockerfile."
    )


# ================= SUBTITLE IMAGE =================

def create_subtitle_image(text):

    image = Image.new(
        "RGBA",
        (960, HEIGHT),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    font_path = get_hindi_font()

    font = ImageFont.truetype(
        font_path,
        58
    )

    # Subtitle card

    draw.rounded_rectangle(
        (60, 320, 900, 760),
        radius=35,
        fill=(15, 23, 42, 235)
    )

    # Wrap subtitle according to available width

    words = text.split()

    lines = []
    current_line = ""

    for word in words:

        test_line = (
            current_line + " " + word
        ).strip()

        if draw.textlength(test_line, font=font) < 740:

            current_line = test_line

        else:

            if current_line:
                lines.append(current_line)

            current_line = word

    if current_line:
        lines.append(current_line)

    # Draw text

    line_height = 85

    total_height = len(lines) * line_height

    start_y = (
        HEIGHT // 2 - total_height // 2
    )

    for line in lines:

        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font
        )

        text_width = bbox[2] - bbox[0]

        x = (960 - text_width) // 2

        draw.text(
            (x, start_y),
            line,
            font=font,
            fill="white"
        )

        start_y += line_height

    return np.array(image)


# ================= AUDIO ANALYSIS =================

def get_audio_envelope(audio_clip):

    duration = audio_clip.duration

    sample_rate = 8000

    audio_array = audio_clip.to_soundarray(
        fps=sample_rate
    )

    if audio_array.ndim == 2:

        audio_array = np.mean(
            audio_array,
            axis=1
        )

    samples_per_frame = max(
        1,
        int(sample_rate / FPS)
    )

    frame_count = int(duration * FPS) + 1

    envelope = []

    for i in range(frame_count):

        start = i * samples_per_frame

        end = start + samples_per_frame

        chunk = audio_array[start:end]

        if len(chunk) == 0:
            envelope.append(0)
        else:
            rms = np.sqrt(
                np.mean(chunk ** 2)
            )

            envelope.append(rms)

    return envelope


# ================= AVATAR ANIMATION =================

def create_avatar_clips(envelope, duration):

    closed = Image.open(
        SCENE1_PATH
    ).convert("RGBA")

    opened = Image.open(
        SCENE2_PATH
    ).convert("RGBA")

    # Resize avatar to fit left side

    closed.thumbnail((900, 950))

    opened = opened.resize(
        closed.size,
        Image.Resampling.LANCZOS
    )

    avatar_width, avatar_height = closed.size

    x_position = (960 - avatar_width) // 2

    y_position = (HEIGHT - avatar_height) // 2

    closed_array = np.array(closed)

    opened_array = np.array(opened)

    clips = []

    # Group consecutive frames with the same mouth state

    current_state = None
    segment_start = 0

    frame_count = min(
        len(envelope),
        int(duration * FPS) + 1
    )

    for frame in range(frame_count):

        # Adjust this threshold if mouth movement is too frequent.

        mouth_open = envelope[frame] > 0.015

        state = "open" if mouth_open else "closed"

        if current_state is None:

            current_state = state
            segment_start = frame

        elif state != current_state:

            start_time = segment_start / FPS

            end_time = frame / FPS

            image_array = (
                opened_array
                if current_state == "open"
                else closed_array
            )

            clip = (
                ImageClip(image_array)
                .set_start(start_time)
                .set_duration(end_time - start_time)
                .set_position((x_position, y_position))
            )

            clips.append(clip)

            current_state = state

            segment_start = frame

    # Add final segment

    if current_state is not None:

        start_time = segment_start / FPS

        image_array = (
            opened_array
            if current_state == "open"
            else closed_array
        )

        clip = (
            ImageClip(image_array)
            .set_start(start_time)
            .set_duration(max(0.01, duration - start_time))
            .set_position((x_position, y_position))
        )

        clips.append(clip)

    return clips


# ================= MAIN HANDLER =================

def handler(event):

    try:

        input_data = event.get("input", {})

        script = input_data.get("script")

        audio_base64 = input_data.get("audio_base64")

        if not script:

            return {
                "error": "No script provided."
            }

        if not audio_base64:

            return {
                "error": "No audio_base64 provided."
            }

        if not os.path.exists(SCENE1_PATH):

            return {
                "error": "Closed-mouth avatar image not found."
            }

        if not os.path.exists(SCENE2_PATH):

            return {
                "error": "Open-mouth avatar image not found."
            }

        # STEP 1: Decode ElevenLabs audio

        audio_bytes = base64.b64decode(
            audio_base64,
            validate=True
        )

        with open(AUDIO_PATH, "wb") as f:

            f.write(audio_bytes)

        audio_clip = AudioFileClip(
            AUDIO_PATH
        )

        duration = audio_clip.duration

        if duration <= 0:

            raise RuntimeError("Audio duration is invalid.")

        # STEP 2: Analyze audio

        envelope = get_audio_envelope(
            audio_clip
        )

        # STEP 3: Create background

        background = ColorClip(
            size=(WIDTH, HEIGHT),
            color=(15, 23, 42)
        ).set_duration(duration)

        # STEP 4: Create avatar animation

        avatar_clips = create_avatar_clips(
            envelope,
            duration
        )

        # STEP 5: Create subtitles

        lines = [
            line.strip()
            for line in script.splitlines()
            if line.strip()
        ]

        if not lines:
            lines = [script.strip()]

        total_characters = sum(
            max(1, len(line))
            for line in lines
        )

        subtitle_clips = []

        current_time = 0

        for line in lines:

            line_duration = (
                duration * len(line) / total_characters
            )

            subtitle_image = create_subtitle_image(
                line
            )

            subtitle_clip = (
                ImageClip(subtitle_image)
                .set_start(current_time)
                .set_duration(line_duration)
                .set_position((960, 0))
            )

            subtitle_clips.append(
                subtitle_clip
            )

            current_time += line_duration

        # STEP 6: Combine video and audio

        final_video = CompositeVideoClip(
            [
                background,
                *avatar_clips,
                *subtitle_clips
            ],
            size=(WIDTH, HEIGHT)
        )

        final_video = final_video.set_audio(
            audio_clip
        )

        # STEP 7: Render MP4

        final_video.write_videofile(
            OUTPUT_PATH,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="6000k",
            preset="ultrafast",
            threads=4,
            logger=None
        )

        # STEP 8: Return Base64 video

        with open(OUTPUT_PATH, "rb") as f:

            video_base64 = base64.b64encode(
                f.read()
            ).decode("utf-8")

        # Cleanup

        final_video.close()

        audio_clip.close()

        for clip in avatar_clips:
            clip.close()

        for clip in subtitle_clips:
            clip.close()

        background.close()

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


# ================= START RUNPOD =================

runpod.serverless.start({
    "handler": handler
})
