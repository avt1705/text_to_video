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
    VideoClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip
)


# =====================================================
# VIDEO SETTINGS
# =====================================================

WIDTH = 1920
HEIGHT = 1080
FPS = 30

AVATAR_WIDTH = 750
AVATAR_HEIGHT = 900

SCENE1_PATH = "/app/my_scene1.png"  # Mouth closed
SCENE2_PATH = "/app/my_scene2.png"  # Mouth open

AUDIO_PATH = "/tmp/narration.mp3"
OUTPUT_PATH = "/tmp/final_video.mp4"
RAW_AUDIO_PATH = "/tmp/audio_analysis.raw"

SAMPLE_RATE = 16000

# Analyze audio every 0.05 seconds
CHUNK_DURATION = 0.05

# Audio sensitivity
OPEN_THRESHOLD = 0.012
CLOSE_THRESHOLD = 0.007

# Subtitle position
SUBTITLE_Y = 820


# =====================================================
# HINDI FONT
# =====================================================

def get_hindi_font(size=50):

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"
    ]

    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# =====================================================
# LOAD AVATAR IMAGES
# =====================================================

def prepare_avatar_images():

    if not os.path.exists(SCENE1_PATH):
        raise FileNotFoundError("my_scene1.png not found")

    if not os.path.exists(SCENE2_PATH):
        raise FileNotFoundError("my_scene2.png not found")

    closed = Image.open(SCENE1_PATH).convert("RGB")
    opened = Image.open(SCENE2_PATH).convert("RGB")

    try:
        resampling = Image.Resampling.LANCZOS
    except AttributeError:
        resampling = Image.LANCZOS

    closed = closed.resize(
        (AVATAR_WIDTH, AVATAR_HEIGHT),
        resampling
    )

    opened = opened.resize(
        (AVATAR_WIDTH, AVATAR_HEIGHT),
        resampling
    )

    return (
        np.array(closed),
        np.array(opened)
    )


# =====================================================
# ANALYZE AUDIO
# =====================================================

def analyze_audio(audio_clip):

    duration = audio_clip.duration

    print("Analyzing narration audio...")

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

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    audio_data = np.fromfile(
        RAW_AUDIO_PATH,
        dtype=np.float32
    )

    samples_per_chunk = int(
        SAMPLE_RATE * CHUNK_DURATION
    )

    total_chunks = int(
        np.ceil(duration / CHUNK_DURATION)
    )

    envelope = []

    for i in range(total_chunks):

        start = i * samples_per_chunk
        end = start + samples_per_chunk

        chunk = audio_data[start:end]

        if len(chunk) == 0:
            rms = 0
        else:
            rms = np.sqrt(
                np.mean(chunk ** 2)
            )

        envelope.append(rms)

    envelope = np.array(envelope)

    # Smooth audio volume to reduce rapid mouth switching
    if len(envelope) >= 3:

        envelope = np.convolve(
            envelope,
            np.ones(3) / 3,
            mode="same"
        )

    # Adaptive sensitivity
    peak_volume = float(np.max(envelope)) if len(envelope) else 0

    open_threshold = max(
        OPEN_THRESHOLD,
        peak_volume * 0.12
    )

    close_threshold = max(
        CLOSE_THRESHOLD,
        peak_volume * 0.07
    )

    print("Audio analysis completed.")
    print("Peak volume:", peak_volume)
    print("Open threshold:", open_threshold)
    print("Close threshold:", close_threshold)

    return envelope, open_threshold, close_threshold


# =====================================================
# CREATE CONTINUOUS AVATAR ANIMATION
# =====================================================

def create_avatar(
    closed_image,
    open_image,
    envelope,
    open_threshold,
    close_threshold,
    duration
):

    print("Creating continuous avatar animation...")

    # Precalculate mouth states.
    # True = mouth open
    # False = mouth closed

    mouth_states = []

    is_open = False

    for volume in envelope:

        if not is_open and volume >= open_threshold:
            is_open = True

        elif is_open and volume <= close_threshold:
            is_open = False

        mouth_states.append(is_open)

    mouth_states = np.array(mouth_states)

    # Continuous frame generator
    def make_frame(t):

        index = int(t / CHUNK_DURATION)

        index = min(
            index,
            len(mouth_states) - 1
        )

        if mouth_states[index]:
            return open_image

        return closed_image

    avatar_clip = VideoClip(
        make_frame=make_frame,
        duration=duration
    )

    avatar_clip = avatar_clip.set_position(
        ("center", "center")
    )

    print("Avatar animation created.")

    return avatar_clip


# =====================================================
# CREATE SUBTITLE IMAGE
# =====================================================

def create_subtitle_image(text):

    image_width = 1600
    image_height = 190

    image = Image.new(
        "RGBA",
        (image_width, image_height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    # Black subtitle background
    draw.rounded_rectangle(
        (10, 10, image_width - 10, image_height - 10),
        radius=25,
        fill=(0, 0, 0, 220)
    )

    font = get_hindi_font(48)

    # Wrap long subtitle lines
    words = text.split()
    lines = []
    current_line = ""

    for word in words:

        test_line = (
            current_line + " " + word
        ).strip()

        if len(test_line) > 42 and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test_line

    if current_line:
        lines.append(current_line)

    lines = lines[:2]

    text_to_draw = "\n".join(lines)

    draw.multiline_text(
        (image_width // 2, image_height // 2),
        text_to_draw,
        font=font,
        fill=(255, 255, 255, 255),
        anchor="mm",
        align="center",
        spacing=12
    )

    return np.array(image)


# =====================================================
# CREATE SUBTITLE CLIPS
# =====================================================

def create_subtitles(script, duration):

    print("Creating subtitles...")

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

    current_time = 0
    subtitle_clips = []

    for line in lines:

        if total_characters > 0:
            line_duration = (
                len(line) / total_characters
            ) * duration
        else:
            line_duration = duration / len(lines)

        subtitle_image = create_subtitle_image(line)

        subtitle_clip = (
            ImageClip(subtitle_image)
            .set_start(current_time)
            .set_duration(line_duration)
            .set_position(("center", SUBTITLE_Y))
        )

        subtitle_clips.append(subtitle_clip)

        current_time += line_duration

    return subtitle_clips


# =====================================================
# MAIN RUNPOD HANDLER
# =====================================================

def handler(event):

    audio_clip = None
    background = None
    avatar_clip = None
    final_video = None

    subtitle_clips = []

    try:

        print("Starting video generation...")

        # Get input script
        job_input = event.get("input", {})

        script = job_input.get("script", "").strip()

        if not script:
            return {
                "error": "Please provide a Hindi script."
            }

        # Check avatar files
        if not os.path.exists(SCENE1_PATH):
            return {
                "error": "Avatar image my_scene1.png is missing."
            }

        if not os.path.exists(SCENE2_PATH):
            return {
                "error": "Avatar image my_scene2.png is missing."
            }

        # ---------------------------------------------
        # STEP 1: GENERATE HINDI VOICE
        # ---------------------------------------------

        print("Generating Hindi narration using gTTS...")

        tts = gTTS(
            text=script,
            lang="hi",
            slow=False
        )

        tts.save(AUDIO_PATH)

        # ---------------------------------------------
        # STEP 2: LOAD AUDIO
        # ---------------------------------------------

        audio_clip = AudioFileClip(AUDIO_PATH)

        duration = audio_clip.duration

        print("Audio duration:", duration)

        # ---------------------------------------------
        # STEP 3: ANALYZE AUDIO
        # ---------------------------------------------

        envelope, open_threshold, close_threshold = analyze_audio(
            audio_clip
        )

        # ---------------------------------------------
        # STEP 4: LOAD AVATAR IMAGES
        # ---------------------------------------------

        closed_image, open_image = prepare_avatar_images()

        # ---------------------------------------------
        # STEP 5: CREATE CONTINUOUS AVATAR
        # ---------------------------------------------

        avatar_clip = create_avatar(
            closed_image,
            open_image,
            envelope,
            open_threshold,
            close_threshold,
            duration
        )

        # ---------------------------------------------
        # STEP 6: CREATE WHITE BACKGROUND
        # ---------------------------------------------

        background = ColorClip(
            size=(WIDTH, HEIGHT),
            color=(255, 255, 255),
            duration=duration
        )

        # ---------------------------------------------
        # STEP 7: CREATE SUBTITLES
        # ---------------------------------------------

        subtitle_clips = create_subtitles(
            script,
            duration
        )

        # ---------------------------------------------
        # STEP 8: COMBINE VIDEO
        # ---------------------------------------------

        print("Combining video layers...")

        all_clips = [
            background,
            avatar_clip
        ] + subtitle_clips

        final_video = CompositeVideoClip(
            all_clips,
            size=(WIDTH, HEIGHT)
        )

        final_video = final_video.set_audio(
            audio_clip
        )

        # ---------------------------------------------
        # STEP 9: EXPORT VIDEO
        # ---------------------------------------------

        print("Rendering final video...")

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

        # ---------------------------------------------
        # STEP 10: CHECK OUTPUT
        # ---------------------------------------------

        if not os.path.exists(OUTPUT_PATH):
            raise Exception("Video file was not created.")

        file_size = os.path.getsize(OUTPUT_PATH)

        if file_size == 0:
            raise Exception("Generated video is empty.")

        # ---------------------------------------------
        # STEP 11: CONVERT VIDEO TO BASE64
        # ---------------------------------------------

        print("Encoding video to Base64...")

        with open(OUTPUT_PATH, "rb") as video_file:

            video_base64 = base64.b64encode(
                video_file.read()
            ).decode("utf-8")

        print("Video generation successful.")

        return {
            "video_base64": video_base64,
            "duration": round(duration, 2),
            "resolution": "1920x1080",
            "fps": FPS,
            "file_size_mb": round(
                file_size / (1024 * 1024),
                2
            )
        }

    except Exception as e:

        print("VIDEO GENERATION ERROR:")
        print(traceback.format_exc())

        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

    finally:

        # ---------------------------------------------
        # CLEANUP
        # ---------------------------------------------

        print("Cleaning temporary resources...")

        clips_to_close = (
            [final_video, background, avatar_clip]
            + subtitle_clips
            + [audio_clip]
        )

        for clip in clips_to_close:

            if clip is not None:

                try:
                    clip.close()
                except Exception:
                    pass

        temporary_files = [
            AUDIO_PATH,
            OUTPUT_PATH,
            RAW_AUDIO_PATH
        ]

        for path in temporary_files:

            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


# =====================================================
# START RUNPOD SERVERLESS
# =====================================================

runpod.serverless.start({
    "handler": handler
})
