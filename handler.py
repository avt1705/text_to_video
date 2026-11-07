import os
import io
import time
import base64
import logging
import tempfile
import subprocess

import runpod
import numpy as np

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps
)

from moviepy.editor import (
    AudioFileClip,
    VideoClip
)


# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# =====================================================
# VIDEO CONFIGURATION
# =====================================================

WIDTH = 1920
HEIGHT = 1080

FPS = 30

VIDEO_BITRATE = "4000k"

ASSET_DIR = "/app"

AVATAR_WIDTH = 680
AVATAR_HEIGHT = 900


# =====================================================
# CHARACTER IMAGE FILES
# =====================================================

CHARACTER_FILES = {
    "neutral": "01_neutral.png",
    "mouth_slight": "02_mouth_slightly_open.png",
    "mouth_wide": "03_mouth_wide_open.png",
    "blink": "04_blinking.png",
    "smile": "05_smiling.png",
    "surprised": "06_surprised.png",
    "left_gesture": "07_left_hand_gesture.png",
    "right_gesture": "08_right_hand_gesture.png",
    "both_gesture": "09_both_hands_gesture.png"
}


# =====================================================
# LOAD CHARACTER IMAGES
# =====================================================

def load_character_images():

    logging.info("Loading character images...")

    characters = {}

    for pose, filename in CHARACTER_FILES.items():

        image_path = os.path.join(
            ASSET_DIR,
            filename
        )

        if not os.path.exists(image_path):

            raise FileNotFoundError(
                f"Character image not found: {image_path}"
            )

        image = Image.open(
            image_path
        ).convert("RGB")

        image = ImageOps.contain(
            image,
            (AVATAR_WIDTH, AVATAR_HEIGHT),
            Image.Resampling.LANCZOS
        )

        characters[pose] = image

        logging.info(
            f"Loaded character pose: {pose}"
        )

    logging.info("All character images loaded successfully.")

    return characters


CHARACTERS = load_character_images()


# =====================================================
# FONT CONFIGURATION
# =====================================================

def load_hindi_font(size):

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf"
    ]

    for path in font_paths:

        if os.path.exists(path):

            return ImageFont.truetype(
                path,
                size
            )

    logging.warning(
        "Hindi font not found. Using default font."
    )

    return ImageFont.load_default()


TITLE_FONT = load_hindi_font(48)
SCRIPT_FONT = load_hindi_font(48)
SMALL_FONT = load_hindi_font(25)


# =====================================================
# CONVERT MP3 TO WAV USING FFMPEG
# =====================================================

def convert_audio_to_wav(mp3_path, wav_path):

    logging.info("Converting incoming MP3 to WAV...")

    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        mp3_path,
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        wav_path
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE
    )

    if not os.path.exists(wav_path):

        raise RuntimeError(
            "FFmpeg failed to create WAV file."
        )

    logging.info("Audio conversion completed.")


# =====================================================
# AUDIO ANALYSIS USING FFMPEG
# =====================================================

def analyze_audio(audio_path):

    logging.info(
        "Analysing audio using FFmpeg..."
    )

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        audio_path,
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "8000",
        "pipe:1"
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True
    )

    audio_array = np.frombuffer(
        result.stdout,
        dtype=np.float32
    )

    chunk_size = int(8000 * 0.08)

    rms_values = []

    for start in range(
        0,
        len(audio_array),
        chunk_size
    ):

        chunk = audio_array[
            start:start + chunk_size
        ]

        if len(chunk) == 0:
            continue

        rms = np.sqrt(
            np.mean(chunk ** 2)
        )

        rms_values.append(rms)

    rms_values = np.array(
        rms_values,
        dtype=np.float32
    )

    if len(rms_values) == 0:

        return np.zeros(1), 0.001

    threshold = max(
        np.percentile(rms_values, 20) * 1.35,
        np.max(rms_values) * 0.06
    )

    logging.info(
        "Audio analysis completed."
    )

    return rms_values, threshold


# =====================================================
# GET AUDIO VOLUME AT CURRENT TIME
# =====================================================

def get_audio_volume(
    current_time,
    rms_values
):

    index = int(
        current_time / 0.08
    )

    index = max(
        0,
        min(
            index,
            len(rms_values) - 1
        )
    )

    return float(
        rms_values[index]
    )


# =====================================================
# ESTIMATE WORD TIMINGS
# =====================================================

def calculate_word_timings(
    script,
    duration
):

    words = script.split()

    if not words:
        return []

    weights = [
        max(len(word), 1)
        for word in words
    ]

    total_weight = sum(weights)

    timings = []

    current_time = 0.0

    for index, word in enumerate(words):

        word_duration = (
            duration *
            weights[index] /
            total_weight
        )

        start_time = current_time

        end_time = (
            current_time +
            word_duration
        )

        timings.append({
            "word": word,
            "start": start_time,
            "end": end_time
        })

        current_time = end_time

    return timings


# =====================================================
# GET CURRENT WORD INDEX
# =====================================================

def get_current_word(
    current_time,
    timings
):

    for index, item in enumerate(timings):

        if (
            item["start"]
            <= current_time
            < item["end"]
        ):

            return index

    if timings and current_time >= timings[-1]["end"]:

        return len(timings) - 1

    return 0


# =====================================================
# SELECT CHARACTER POSE
# =====================================================

def select_character_pose(
    current_time,
    volume,
    threshold,
    current_word
):

    # Periodic blinking

    blink_position = current_time % 4.8

    if blink_position < 0.16:

        return "blink"

    # Surprise expression for punctuation

    if (
        current_word
        and (
            "!" in current_word
            or "?" in current_word
        )
    ):

        return "surprised"

    # Periodic gestures while speaking

    gesture_position = current_time % 14

    if volume > threshold:

        if 6.0 <= gesture_position < 7.0:

            return "left_gesture"

        if 10.0 <= gesture_position < 11.0:

            return "right_gesture"

        if 12.0 <= gesture_position < 13.0:

            return "both_gesture"

    # Smiling expression

    if 3.0 <= current_time % 12 < 4.0:

        return "smile"

    # Mouth animation based on audio volume

    if volume > threshold * 2.5:

        return "mouth_wide"

    if volume > threshold:

        return "mouth_slight"

    return "neutral"


# =====================================================
# PREPARE WORD POSITIONS
# =====================================================

def build_word_layout(
    script,
    draw,
    font,
    max_width
):

    words = script.split()

    positions = []

    x = 0
    y = 0

    line_height = 82

    for index, word in enumerate(words):

        word_width = draw.textlength(
            word,
            font=font
        )

        space_width = draw.textlength(
            " ",
            font=font
        )

        if (
            x > 0
            and x + word_width > max_width
        ):

            x = 0
            y += line_height

        positions.append({
            "word": word,
            "index": index,
            "x": x,
            "y": y,
            "width": word_width
        })

        x += word_width + space_width

    return positions


# =====================================================
# RENDER HINDI TEXT PANEL
# =====================================================

def render_lyrics_panel(
    script,
    current_word_index
):

    panel = Image.new(
        "RGB",
        (1080, 820),
        (255, 255, 255)
    )

    draw = ImageDraw.Draw(panel)

    # Panel border

    draw.rounded_rectangle(
        (5, 5, 1075, 815),
        radius=30,
        fill=(255, 255, 255),
        outline=(225, 225, 225),
        width=3
    )

    # Heading

    draw.text(
        (45, 35),
        "गीत का मतलब",
        font=TITLE_FONT,
        fill=(25, 25, 25)
    )

    draw.line(
        (45, 110, 1035, 110),
        fill=(220, 220, 220),
        width=3
    )

    # Word layout

    layout = build_word_layout(
        script,
        draw,
        SCRIPT_FONT,
        970
    )

    # Display words

    for item in layout:

        word = item["word"]

        index = item["index"]

        x = 45 + item["x"]

        y = 155 + item["y"]

        word_width = item["width"]

        # Highlight current word

        if index == current_word_index:

            draw.rounded_rectangle(
                (
                    x - 8,
                    y - 5,
                    x + word_width + 12,
                    y + 65
                ),
                radius=12,
                fill=(255, 225, 110)
            )

            text_color = (25, 25, 25)

        elif index < current_word_index:

            text_color = (70, 70, 70)

        else:

            text_color = (155, 155, 155)

        draw.text(
            (x, y),
            word,
            font=SCRIPT_FONT,
            fill=text_color
        )

    return panel


# =====================================================
# CREATE VIDEO FRAME
# =====================================================

def create_video_frame(
    current_time,
    characters,
    timings,
    rms_values,
    threshold,
    script
):

    frame = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (255, 255, 255)
    )

    draw = ImageDraw.Draw(frame)

    # Current audio volume

    volume = get_audio_volume(
        current_time,
        rms_values
    )

    # Current word

    current_index = get_current_word(
        current_time,
        timings
    )

    current_word = ""

    if timings:

        current_word = timings[
            current_index
        ]["word"]

    # Select character

    pose = select_character_pose(
        current_time,
        volume,
        threshold,
        current_word
    )

    character = characters[pose]

    # Character placement

    character_x = 45

    character_y = 115

    frame.paste(
        character,
        (character_x, character_y)
    )

    # Character label

    draw.text(
        (80, 1015),
        "THE PTG GUY",
        font=SMALL_FONT,
        fill=(75, 75, 75)
    )

    # Render lyrics panel

    panel = render_lyrics_panel(
        script,
        current_index
    )

    frame.paste(
        panel,
        (790, 130)
    )

    # Bottom branding

    draw.text(
        (800, 1000),
        "Punjabi Lyrics Explained in Hindi",
        font=SMALL_FONT,
        fill=(110, 110, 110)
    )

    return np.array(frame)


# =====================================================
# GENERATE VIDEO
# =====================================================

def generate_video(
    script,
    audio_base64
):

    logging.info(
        "Starting video generation..."
    )

    with tempfile.TemporaryDirectory() as temp_dir:

        mp3_path = os.path.join(
            temp_dir,
            "narration.mp3"
        )

        wav_path = os.path.join(
            temp_dir,
            "narration.wav"
        )

        output_path = os.path.join(
            temp_dir,
            "output.mp4"
        )

        # Decode incoming audio

        audio_bytes = base64.b64decode(
            audio_base64
        )

        with open(
            mp3_path,
            "wb"
        ) as audio_file:

            audio_file.write(
                audio_bytes
            )

        logging.info(
            "Incoming audio saved."
        )

        # Convert MP3 to WAV

        convert_audio_to_wav(
            mp3_path,
            wav_path
        )

        # Analyse WAV using FFmpeg

        rms_values, threshold = analyze_audio(
            wav_path
        )

        # Open WAV using MoviePy

        audio_clip = AudioFileClip(
            wav_path
        )

        duration = audio_clip.duration

        logging.info(
            f"Audio duration: {duration:.2f} seconds"
        )

        # Estimate word timings

        timings = calculate_word_timings(
            script,
            duration
        )

        # Frame generator

        def make_frame(t):

            return create_video_frame(
                current_time=t,
                characters=CHARACTERS,
                timings=timings,
                rms_values=rms_values,
                threshold=threshold,
                script=script
            )

        # Create video

        video_clip = VideoClip(
            make_frame=make_frame,
            duration=duration
        )

        video_clip = video_clip.set_fps(
            FPS
        )

        # Attach audio

        final_video = video_clip.set_audio(
            audio_clip
        )

        logging.info(
            "Starting MP4 export..."
        )

        # Export video

        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=FPS,
            preset="medium",
            bitrate=VIDEO_BITRATE,
            threads=2,
            logger=None
        )

        logging.info(
            "MP4 export completed."
        )

        # Read generated MP4

        with open(
            output_path,
            "rb"
        ) as video_file:

            video_bytes = video_file.read()

        # Close clips only after export

        final_video.close()

        video_clip.close()

        audio_clip.close()

        # Encode MP4

        video_base64 = base64.b64encode(
            video_bytes
        ).decode("utf-8")

        logging.info(
            "Video generation completed successfully."
        )

        return {
            "video_base64": video_base64,
            "duration": round(duration, 2),
            "resolution": "1920x1080",
            "fps": FPS,
            "voice": "Sarvam Bulbul V3 - Shubh"
        }


# =====================================================
# RUNPOD SERVERLESS HANDLER
# =====================================================

def handler(job):

    logging.info(
        "Received new RunPod job."
    )

    job_input = job.get("input", {})

    script = job_input.get("script")

    audio_base64 = job_input.get("audio_base64")

    if not script:

        return {
            "error": "Hindi script is missing."
        }

    if not audio_base64:

        return {
            "error": "Audio data is missing."
        }

    try:

        result = generate_video(
            script,
            audio_base64
        )

        return result

    except Exception as e:

        logging.exception(
            "Video generation failed."
        )

        return {
            "error": str(e)
        }


# =====================================================
# START RUNPOD WORKER
# =====================================================

if __name__ == "__main__":

    logging.info(
        "Starting PTG Studio RunPod worker..."
    )

    runpod.serverless.start({
        "handler": handler
    })
