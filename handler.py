import os
import base64
import traceback
import numpy as np
import runpod

from gtts import gTTS

from PIL import Image, ImageDraw, ImageFont

from moviepy.editor import (
    AudioFileClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip,
    concatenate_videoclips
)


# =====================================================
# VIDEO SETTINGS
# =====================================================

WIDTH = 1920
HEIGHT = 1080
FPS = 30

SCENE1_PATH = "/app/my_scene1.png"
SCENE2_PATH = "/app/my_scene2.png"

AUDIO_PATH = "/tmp/narration.mp3"
OUTPUT_PATH = "/tmp/final_video.mp4"


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
            return ImageFont.truetype(path, size)

    raise FileNotFoundError(
        "Hindi font not found. Please install fonts-noto in Dockerfile."
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
# AUDIO ANALYSIS
# =====================================================

def analyze_audio(audio_clip):

    """
    Analyze audio in small chunks.

    This avoids MoviePy's full-audio to_soundarray()
    buffer indexing problem.
    """

    duration = audio_clip.duration

    sample_rate = 8000
    chunk_duration = 0.1

    envelope = []

    for start in np.arange(0, duration, chunk_duration):

        end = min(start + chunk_duration, duration)

        try:

            chunk = audio_clip.subclip(start, end)

            audio = chunk.to_soundarray(
                fps=sample_rate
            )

            chunk.close()

            if audio.size == 0:

                envelope.append(0)
                continue

            rms = np.sqrt(
                np.mean(np.square(audio))
            )

            envelope.append(float(rms))

        except Exception:

            envelope.append(0)

    return envelope


# =====================================================
# AVATAR ANIMATION
# =====================================================

def create_avatar(envelope, duration):

    scene1 = Image.open(
        SCENE1_PATH
    ).convert("RGBA")

    scene2 = Image.open(
        SCENE2_PATH
    ).convert("RGBA")

    # Resize both images to identical dimensions
    avatar_width = 750
    avatar_height = 900

    scene1 = scene1.resize(
        (avatar_width, avatar_height),
        Image.Resampling.LANCZOS
    )

    scene2 = scene2.resize(
        (avatar_width, avatar_height),
        Image.Resampling.LANCZOS
    )

    scene1_path = "/tmp/avatar_closed.png"
    scene2_path = "/tmp/avatar_open.png"

    scene1.save(scene1_path)
    scene2.save(scene2_path)

    # Generate mouth animation clips
    avatar_clips = []

    chunk_duration = 0.1

    for index, volume in enumerate(envelope):

        start = index * chunk_duration

        if start >= duration:
            break

        clip_duration = min(
            chunk_duration,
            duration - start
        )

        if volume > 0.015:

            image_path = scene2_path

        else:

            image_path = scene1_path

        clip = (
            ImageClip(image_path)
            .set_duration(clip_duration)
            .set_position(("center", "center"))
            .set_start(start)
        )

        avatar_clips.append(clip)

    return avatar_clips


# =====================================================
# SUBTITLE TIMING
# =====================================================

def create_subtitles(script, duration):

    lines = [
        line.strip()
        for line in script.split("\n")
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

        subtitle_image = create_subtitle_image(line)

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
# MAIN RUNPOD HANDLER
# =====================================================

def handler(event):

    audio_clip = None
    final_video = None

    try:

        print("Starting video generation...")

        # ---------------------------------------------
        # GET INPUT
        # ---------------------------------------------

        job_input = event.get("input", {})

        script = job_input.get("script", "").strip()

        if not script:

            return {
                "error": "Hindi script is empty."
            }

        # ---------------------------------------------
        # CHECK AVATAR IMAGES
        # ---------------------------------------------

        if not os.path.exists(SCENE1_PATH):

            return {
                "error": "Avatar image not found: my_scene1.png"
            }

        if not os.path.exists(SCENE2_PATH):

            return {
                "error": "Avatar image not found: my_scene2.png"
            }

        # ---------------------------------------------
        # GENERATE HINDI AUDIO
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

        audio_clip = AudioFileClip(AUDIO_PATH)

        duration = audio_clip.duration

        print("Audio duration:", duration)

        if duration <= 0:

            raise ValueError("Generated audio has zero duration.")

        # ---------------------------------------------
        # ANALYZE AUDIO
        # ---------------------------------------------

        print("Analyzing audio...")

        envelope = analyze_audio(audio_clip)

        print("Audio analysis completed.")

        # ---------------------------------------------
        # BACKGROUND
        # ---------------------------------------------

        background = ColorClip(
            size=(WIDTH, HEIGHT),
            color=(255, 255, 255)
        ).set_duration(duration)

        # ---------------------------------------------
        # AVATAR
        # ---------------------------------------------

        print("Creating avatar animation...")

        avatar_clips = create_avatar(
            envelope,
            duration
        )

        # ---------------------------------------------
        # SUBTITLES
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

        all_clips.extend(avatar_clips)

        all_clips.extend(subtitle_clips)

        final_video = CompositeVideoClip(
            all_clips,
            size=(WIDTH, HEIGHT)
        )

        final_video = final_video.set_audio(
            audio_clip
        )

        # ---------------------------------------------
        # EXPORT MP4
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

        print("Video exported successfully.")

        # ---------------------------------------------
        # CONVERT VIDEO TO BASE64
        # ---------------------------------------------

        with open(OUTPUT_PATH, "rb") as video_file:

            video_base64 = base64.b64encode(
                video_file.read()
            ).decode("utf-8")

        print("Video converted to Base64.")

        # ---------------------------------------------
        # RETURN RESULT
        # ---------------------------------------------

        return {

            "video_base64": video_base64,

            "duration": round(duration, 2),

            "resolution": "1920x1080",

            "fps": FPS

        }

    except Exception as error:

        print("VIDEO GENERATION ERROR:")

        traceback.print_exc()

        return {

            "error": str(error)

        }

    finally:

        if final_video is not None:

            try:
                final_video.close()
            except Exception:
                pass

        if audio_clip is not None:

            try:
                audio_clip.close()
            except Exception:
                pass

        print("Worker job cleanup completed.")


# =====================================================
# START RUNPOD SERVERLESS
# =====================================================

runpod.serverless.start({

    "handler": handler

})
