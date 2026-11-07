import os
import re
import base64
import tempfile
import logging

import runpod
import numpy as np

from PIL import Image, ImageDraw, ImageFont, ImageOps

from moviepy.editor import (
    AudioFileClip,
    VideoClip
)

# =====================================================
# CONFIGURATION
# =====================================================

logging.basicConfig(level=logging.INFO)

WIDTH = 1920
HEIGHT = 1080
FPS = 30

ASSET_DIR = "/app"

# =====================================================
# CHARACTER IMAGE FILES
# =====================================================

AVATAR_FILES = {
    "neutral": "01_neutral.png",
    "mouth_slight": "02_mouth_slightly_open.png",
    "mouth_wide": "03_mouth_wide_open.png",
    "blink": "04_blinking.png",
    "smile": "05_smiling.png",
    "surprised": "06_surprised.png",
    "left": "07_left_hand_gesture.png",
    "right": "08_right_hand_gesture.png",
    "both": "09_both_hands_gesture.png"
}

# =====================================================
# LOAD CHARACTER IMAGES
# =====================================================

def load_character_assets():

    assets = {}

    for name, filename in AVATAR_FILES.items():

        path = os.path.join(ASSET_DIR, filename)

        if not os.path.exists(path):

            raise FileNotFoundError(
                f"Character image missing: {path}"
            )

        image = Image.open(path).convert("RGB")

        # Resize while maintaining original proportions
        image = ImageOps.contain(
            image,
            (720, 960),
            method=Image.Resampling.LANCZOS
        )

        assets[name] = image

        logging.info(
            f"Loaded character image: {filename}"
        )

    return assets


# =====================================================
# HINDI FONT
# =====================================================

def load_hindi_font(size):

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagariUI-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in font_paths:

        if os.path.exists(path):

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# =====================================================
# AUDIO ANALYSIS
# =====================================================

def analyze_audio(audio_clip):

    logging.info("Analysing audio...")

    audio_array = audio_clip.to_soundarray(
        fps=8000
    )

    if audio_array.ndim > 1:

        audio_array = np.mean(
            audio_array,
            axis=1
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

    rms_values = np.array(rms_values)

    if len(rms_values) == 0:

        return np.zeros(1), 0.001

    threshold = max(
        np.percentile(rms_values, 20) * 1.35,
        np.max(rms_values) * 0.06
    )

    logging.info("Audio analysis completed.")

    return rms_values, threshold


# =====================================================
# GET CURRENT AUDIO LEVEL
# =====================================================

def get_audio_level(t, rms_values):

    index = int(t / 0.08)

    index = min(
        index,
        len(rms_values) - 1
    )

    return rms_values[index]


# =====================================================
# CHARACTER ANIMATION
# =====================================================

def select_character_pose(
    t,
    rms_values,
    threshold,
    assets,
    words,
    word_index
):

    audio_level = get_audio_level(
        t,
        rms_values
    )

    speaking = audio_level > threshold

    # ---------------------------------------------
    # 1. Eye blinking
    # ---------------------------------------------

    blink_phase = t % 4.8

    if t > 1 and blink_phase < 0.16:

        return assets["blink"]

    # ---------------------------------------------
    # 2. Hand gestures
    # ---------------------------------------------

    gesture_phase = t % 10.0

    if speaking and 5.0 <= gesture_phase < 6.3:

        gesture_cycle = int(t // 10) % 3

        if gesture_cycle == 0:

            return assets["left"]

        elif gesture_cycle == 1:

            return assets["right"]

        else:

            return assets["both"]

    # ---------------------------------------------
    # 3. Surprised expression
    # ---------------------------------------------

    if words and word_index < len(words):

        current_word = words[word_index]

        if (
            speaking
            and re.search(r"[!?]", current_word)
        ):

            return assets["surprised"]

    # ---------------------------------------------
    # 4. Smiling expression
    # ---------------------------------------------

    smile_phase = t % 18.0

    if speaking and 14.0 <= smile_phase < 15.2:

        return assets["smile"]

    # ---------------------------------------------
    # 5. Mouth animation
    # ---------------------------------------------

    if speaking:

        wide_threshold = np.percentile(
            rms_values,
            75
        )

        if audio_level > wide_threshold:

            return assets["mouth_wide"]

        return assets["mouth_slight"]

    # ---------------------------------------------
    # 6. Neutral expression
    # ---------------------------------------------

    return assets["neutral"]


# =====================================================
# WORD TIMING
# =====================================================

def calculate_word_timings(
    script,
    duration
):

    words = script.split()

    if not words:

        return [], []

    weights = []

    for word in words:

        weight = max(
            len(word),
            2
        )

        if re.search(r"[।.!?]", word):

            weight += 3

        weights.append(weight)

    total_weight = sum(weights)

    timings = []

    current_time = 0

    for weight in weights:

        word_duration = (
            duration * weight / total_weight
        )

        timings.append(
            (
                current_time,
                current_time + word_duration
            )
        )

        current_time += word_duration

    return words, timings


# =====================================================
# IDENTIFY CURRENT WORD
# =====================================================

def get_current_word(t, timings):

    for index, (start, end) in enumerate(timings):

        if start <= t < end:

            return index

    if timings and t >= timings[-1][1]:

        return len(timings) - 1

    return 0


# =====================================================
# RENDER WORD-BY-WORD HIGHLIGHTING
# =====================================================

def render_lyrics_panel(
    script,
    current_word,
    width=1120,
    height=1080
):

    image = Image.new(
        "RGB",
        (width, height),
        "white"
    )

    draw = ImageDraw.Draw(image)

    heading_font = load_hindi_font(34)

    text_font = load_hindi_font(52)

    # Heading
    draw.text(
        (65, 90),
        "HINDI EXPLANATION",
        font=heading_font,
        fill=(120, 120, 120)
    )

    words = script.split()

    # Moving word window
    start_index = max(
        0,
        current_word - 12
    )

    end_index = min(
        len(words),
        current_word + 19
    )

    visible_words = words[
        start_index:end_index
    ]

    x = 65
    y = 300

    max_width = width - 110

    line_height = 100

    space_width = 22

    for local_index, word in enumerate(
        visible_words
    ):

        actual_index = (
            start_index + local_index
        )

        bbox = draw.textbbox(
            (0, 0),
            word,
            font=text_font
        )

        word_width = (
            bbox[2] - bbox[0]
        )

        # Move to next line
        if x + word_width > max_width:

            x = 65

            y += line_height

        # Determine word colour
        if actual_index == current_word:

            color = (255, 180, 0)

        elif actual_index < current_word:

            color = (45, 45, 45)

        else:

            color = (170, 170, 170)

        draw.text(
            (x, y),
            word,
            font=text_font,
            fill=color
        )

        x += (
            word_width + space_width
        )

    return image


# =====================================================
# GENERATE FINAL VIDEO
# =====================================================

def generate_video(
    script,
    audio_path
):

    logging.info(
        "Starting video generation..."
    )

    # Load all nine character images
    assets = load_character_assets()

    # Load Sarvam narration
    audio = AudioFileClip(audio_path)

    duration = audio.duration

    logging.info(
        f"Audio duration: {duration:.2f} seconds"
    )

    # Analyse audio
    rms_values, threshold = analyze_audio(
        audio
    )

    # Calculate word timings
    words, timings = calculate_word_timings(
        script,
        duration
    )

    logging.info(
        f"Total words: {len(words)}"
    )

    # Character position
    avatar_x = 20
    avatar_y = 60

    # Cache the lyrics panel so it is only
    # redrawn when the highlighted word changes.
    panel_cache = {
        "word": None,
        "image": None
    }

    def make_frame(t):

        # Create white background
        frame = Image.new(
            "RGB",
            (WIDTH, HEIGHT),
            "white"
        )

        # Identify current word
        current_word = get_current_word(
            t,
            timings
        )

        # Select character expression
        character = select_character_pose(
            t,
            rms_values,
            threshold,
            assets,
            words,
            current_word
        )

        # Centre character in left section
        x = avatar_x + (
            720 - character.width
        ) // 2

        y = avatar_y + (
            960 - character.height
        ) // 2

        frame.paste(
            character,
            (x, y)
        )

        # Render lyrics panel only when needed
        if panel_cache["word"] != current_word:

            panel_cache["image"] = (
                render_lyrics_panel(
                    script,
                    current_word
                )
            )

            panel_cache["word"] = current_word

        frame.paste(
            panel_cache["image"],
            (800, 0)
        )

        return np.array(frame)

    logging.info(
        "Rendering final video..."
    )

    video = VideoClip(
        make_frame,
        duration=duration
    )

    video = video.set_audio(audio)

    output_path = "/tmp/final_video.mp4"

    video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="4000k",
        threads=4,
        logger=None
    )

    video.close()

    audio.close()

    logging.info(
        "Video generation completed successfully."
    )

    return output_path, duration


# =====================================================
# RUNPOD SERVERLESS HANDLER
# =====================================================

def handler(job):

    try:

        job_input = job["input"]

        script = job_input.get(
            "script",
            ""
        )

        audio_base64 = job_input.get(
            "audio_base64"
        )

        if not script:

            raise ValueError(
                "Script is missing."
            )

        if not audio_base64:

            raise ValueError(
                "Audio is missing."
            )

        # Remove data URL prefix if present
        if "," in audio_base64:

            audio_base64 = audio_base64.split(
                ",",
                1
            )[1]

        logging.info(
            "Decoding Sarvam audio..."
        )

        audio_bytes = base64.b64decode(
            audio_base64
        )

        with tempfile.TemporaryDirectory() as temp_dir:

            audio_path = os.path.join(
                temp_dir,
                "narration.mp3"
            )

            with open(
                audio_path,
                "wb"
            ) as f:

                f.write(audio_bytes)

            # Generate video
            output_path, duration = generate_video(
                script,
                audio_path
            )

            logging.info(
                "Encoding final MP4..."
            )

            with open(
                output_path,
                "rb"
            ) as f:

                video_base64 = base64.b64encode(
                    f.read()
                ).decode("utf-8")

            file_size = (
                os.path.getsize(output_path)
                / (1024 * 1024)
            )

            return {

                "video_base64": video_base64,

                "duration": round(
                    duration,
                    2
                ),

                "resolution": "1920x1080",

                "fps": FPS,

                "voice": "Sarvam Bulbul Shubh",

                "layout": (
                    "Animated Sikh Presenter "
                    "+ Word Highlighting"
                ),

                "file_size_mb": round(
                    file_size,
                    2
                )

            }

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

runpod.serverless.start({
    "handler": handler
})
