import os
import base64
import traceback
import subprocess

import numpy as np
import runpod

from gtts import gTTS

from PIL import Image, ImageDraw, ImageFont

from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip
)


# =====================================================
# CONFIGURATION
# =====================================================

WIDTH = 1920
HEIGHT = 1080
FPS = 30

AVATAR_WIDTH = 750
AVATAR_HEIGHT = 900

SCENE1_PATH = "/app/my_scene1.png"
SCENE2_PATH = "/app/my_scene2.png"

AUDIO_PATH = "/tmp/narration.mp3"
OUTPUT_PATH = "/tmp/final_video.mp4"
RAW_AUDIO_PATH = "/tmp/audio_analysis.raw"

CHUNK_DURATION = 0.1
SAMPLE_RATE = 8000

# Adjust this threshold if mouth movement is too frequent.
MOUTH_THRESHOLD = 0.015


# =====================================================
# HINDI FONT
# =====================================================

def get_hindi_font(size=55):

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"
    ]

    for path in font_paths:

        if os.path.exists(path):

            return ImageFont.truetype(
                path,
                size
            )

    raise FileNotFoundError(
        "Hindi font not found. Check fonts-noto installation."
    )


# =====================================================
# CREATE SUBTITLE IMAGE
# =====================================================

def create_subtitle_image(text):

    subtitle_width = 1600
    subtitle_height = 220

    image = Image.new(
        "RGBA",
        (subtitle_width, subtitle_height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    font = get_hindi_font(55)

    draw.rounded_rectangle(
        (10, 10, subtitle_width - 10, subtitle_height - 10),
        radius=25,
        fill=(0, 0, 0, 190)
    )

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (subtitle_width - text_width) // 2
    y = (subtitle_height - text_height) // 2 - bbox[1]

    draw.text(
        (x, y),
        text,
        font=font,
        fill=(255, 255, 255, 255)
    )

    return np.array(image)


# =====================================================
# AUDIO ANALYSIS USING FFMPEG
# =====================================================

def analyze_audio(audio_clip):

    """
    Extract audio independently through FFmpeg.

    This avoids MoviePy audio-reader conflicts.
    """

    duration = audio_clip.duration

    command = [
        "ffmpeg",
        "-y",
        "-i", AUDIO_PATH,
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-f", "f32le",
        RAW_AUDIO_PATH
    ]

    try:

        print("Extracting audio waveform using FFmpeg...")

        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120
        )

        audio = np.fromfile(
            RAW_AUDIO_PATH,
            dtype=np.float32
        )

        if audio.size == 0:

            raise ValueError(
                "FFmpeg extracted an empty audio waveform."
            )

        samples_per_chunk = int(
            SAMPLE_RATE * CHUNK_DURATION
        )

        envelope = []

        for start in range(
            0,
            len(audio),
            samples_per_chunk
        ):

            chunk = audio[
                start:start + samples_per_chunk
            ]

            if len(chunk) == 0:

                envelope.append(0)
                continue

            rms = np.sqrt(
                np.mean(np.square(chunk))
            )

            envelope.append(float(rms))

        expected_chunks = int(
            np.ceil(duration / CHUNK_DURATION)
        )

        # Ensure animation covers the complete video.
        if len(envelope) < expected_chunks:

            envelope.extend(
                [0] * (expected_chunks - len(envelope))
            )

        envelope = envelope[:expected_chunks]

        print(
            "Audio analysis completed. Chunks:",
            len(envelope)
        )

        return envelope

    except subprocess.CalledProcessError as error:

        error_message = error.stderr.decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            "FFmpeg audio analysis failed: " + error_message[-2000:]
        )

    finally:

        if os.path.exists(RAW_AUDIO_PATH):

            os.remove(RAW_AUDIO_PATH)


# =====================================================
# LOAD AND PREPARE AVATAR IMAGES
# =====================================================

def prepare_avatar_images():

    if not os.path.exists(SCENE1_PATH):

        raise FileNotFoundError(
            "Missing avatar image: my_scene1.png"
        )

    if not os.path.exists(SCENE2_PATH):

        raise FileNotFoundError(
            "Missing avatar image: my_scene2.png"
        )

    scene1 = Image.open(
        SCENE1_PATH
    ).convert("RGBA")

    scene2 = Image.open(
        SCENE2_PATH
    ).convert("RGBA")

    scene1 = scene1.resize(
        (AVATAR_WIDTH, AVATAR_HEIGHT),
        Image.Resampling.LANCZOS
    )

    scene2 = scene2.resize(
        (AVATAR_WIDTH, AVATAR_HEIGHT),
        Image.Resampling.LANCZOS
    )

    scene1_path = "/tmp/avatar_closed.png"
    scene2_path = "/tmp/avatar_open.png"

    scene1.save(scene1_path)
    scene2.save(scene2_path)

    return scene1_path, scene2_path


# =====================================================
# CREATE AVATAR ANIMATION
# =====================================================

def create_avatar(envelope, duration):

    scene1_path, scene2_path = prepare_avatar_images()

    avatar_clips = []

    for index, volume in enumerate(envelope):

        start = index * CHUNK_DURATION

        if start >= duration:

            break

        clip_duration = min(
            CHUNK_DURATION,
            duration - start
        )

        if volume > MOUTH_THRESHOLD:

            image_path = scene2_path

        else:

            image_path = scene1_path

        clip = (
            ImageClip(image_path)
            .set_duration(clip_duration)
            .set_start(start)
            .set_position(("center", "center"))
        )

        avatar_clips.append(clip)

    if not avatar_clips:

        raise RuntimeError(
            "Avatar animation could not be created."
        )

    return avatar_clips


# =====================================================
# CREATE SUBTITLES
# =====================================================

def create_subtitles(script, duration):

    lines = [
        line.strip()
        for line in script.splitlines()
        if line.strip()
    ]

    if not lines:

        return []

    total_characters = sum(
        len(line) for line in lines
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

        clip = (
            ImageClip(subtitle_image)
            .set_duration(line_duration)
            .set_start(current_time)
            .set_position(("center", 820))
        )

        subtitle_clips.append(clip)

        current_time += line_duration

    return subtitle_clips


# =====================================================
# MAIN HANDLER
# =====================================================

def handler(event):

    audio_clip = None
    final_video = None

    background = None
    avatar_clips = []
    subtitle_clips = []

    try:

        print("Starting video generation...")

        # ---------------------------------------------
        # GET SCRIPT
        # ---------------------------------------------

        job_input = event.get(
            "input",
            {}
        )

        script = job_input.get(
            "script",
            ""
        ).strip()

        if not script:

            raise ValueError(
                "Hindi script is empty."
            )

        print("Script received successfully.")

        # ---------------------------------------------
        # GENERATE HINDI VOICE
        # ---------------------------------------------

        print("Generating Hindi narration using gTTS...")

        tts = gTTS(
            text=script,
            lang="hi",
            slow=False
        )

        tts.save(AUDIO_PATH)

        print("Hindi narration generated successfully.")

        # ---------------------------------------------
        # LOAD AUDIO
        # ---------------------------------------------

        print("Loading audio...")

        audio_clip = AudioFileClip(
            AUDIO_PATH
        )

        duration = audio_clip.duration

        print(
            "Audio duration:",
            duration
        )

        if duration <= 0:

            raise ValueError(
                "Generated audio has zero duration."
            )

        # ---------------------------------------------
        # ANALYZE AUDIO
        # ---------------------------------------------

        print("Analyzing audio...")

        envelope = analyze_audio(
            audio_clip
        )

        print("Audio analysis completed.")

        # ---------------------------------------------
        # CREATE BACKGROUND
        # ---------------------------------------------

        print("Creating background...")

        background = ColorClip(
            size=(WIDTH, HEIGHT),
            color=(255, 255, 255)
        ).set_duration(duration)

        # ---------------------------------------------
        # CREATE AVATAR
        # ---------------------------------------------

        print("Creating avatar animation...")

        avatar_clips = create_avatar(
            envelope,
            duration
        )

        # ---------------------------------------------
        # CREATE SUBTITLES
        # ---------------------------------------------

        print("Creating subtitles...")

        subtitle_clips = create_subtitles(
            script,
            duration
        )

        # ---------------------------------------------
        # COMBINE VIDEO
        # ---------------------------------------------

        print("Combining video elements...")

        all_clips = [
            background
        ]

        all_clips.extend(
            avatar_clips
        )

        all_clips.extend(
            subtitle_clips
        )

        final_video = CompositeVideoClip(
            all_clips,
            size=(WIDTH, HEIGHT)
        ).set_duration(duration)

        final_video = final_video.set_audio(
            audio_clip
        )

        # ---------------------------------------------
        # EXPORT VIDEO
        # ---------------------------------------------

        print("Exporting final MP4...")

        final_video.write_videofile(
            OUTPUT_PATH,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="3000k",
            preset="ultrafast",
            threads=4,
            logger=None
        )

        if not os.path.exists(OUTPUT_PATH):

            raise RuntimeError(
                "MP4 export failed: output file not found."
            )

        file_size = os.path.getsize(
            OUTPUT_PATH
        )

        if file_size == 0:

            raise RuntimeError(
                "MP4 export failed: output file is empty."
            )

        print(
            "Video exported successfully. Size:",
            round(file_size / (1024 * 1024), 2),
            "MB"
        )

        # ---------------------------------------------
        # CONVERT VIDEO TO BASE64
        # ---------------------------------------------

        print("Converting video to Base64...")

        with open(
            OUTPUT_PATH,
            "rb"
        ) as video_file:

            video_base64 = base64.b64encode(
                video_file.read()
            ).decode("utf-8")

        print("Video converted successfully.")

        # ---------------------------------------------
        # RETURN RESULT
        # ---------------------------------------------

        print("Returning video to RunPod...")

        return {

            "video_base64": video_base64,

            "duration": round(
                duration,
                2
            ),

            "resolution": "1920x1080",

            "fps": FPS,

            "file_size_mb": round(
                file_size / (1024 * 1024),
                2
            )

        }

    except Exception as error:

        print("VIDEO GENERATION ERROR:")

        traceback.print_exc()

        return {

            "error": str(error),

            "traceback": traceback.format_exc()

        }

    finally:

        print("Cleaning up worker resources...")

        if final_video is not None:

            try:
                final_video.close()
            except Exception:
                pass

        if background is not None:

            try:
                background.close()
            except Exception:
                pass

        for clip in avatar_clips:

            try:
                clip.close()
            except Exception:
                pass

        for clip in subtitle_clips:

            try:
                clip.close()
            except Exception:
                pass

        if audio_clip is not None:

            try:
                audio_clip.close()
            except Exception:
                pass

        # Remove temporary files
        for path in [
            AUDIO_PATH,
            OUTPUT_PATH,
            RAW_AUDIO_PATH,
            "/tmp/avatar_closed.png",
            "/tmp/avatar_open.png"
        ]:

            try:

                if os.path.exists(path):
                    os.remove(path)

            except Exception:
                pass

        print("Worker job cleanup completed.")


# =====================================================
# START RUNPOD SERVERLESS
# =====================================================

runpod.serverless.start({
    "handler": handler
})
