import runpod
import moviepy.editor as mpy
from gtts import gTTS
from pydub import AudioSegment, silence
from PIL import Image, ImageDraw, ImageFont
import numpy as np

print(">>> handler.py loaded successfully")

def make_text_clip(text, duration, start):
    """Create a subtitle clip using Pillow instead of ImageMagick."""
    # Create a blank image for subtitle bar
    img = Image.new("RGB", (1280, 200), color="black")
    draw = ImageDraw.Draw(img)

    # Use a system font (DejaVuSans is installed via Dockerfile)
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    draw.text((50, 50), text, font=font, fill="white")

    # Convert to numpy array for MoviePy
    frame = np.array(img)
    clip = mpy.ImageClip(frame).set_duration(duration).set_start(start).set_position(("center", "bottom"))
    return clip

def handler(event):
    print(">>> Handler received event:", event)

    script = event.get("input", {}).get("script", None)
    if not script:
        print(">>> No script provided")
        return {"error": "No script provided."}

    # --- Step 1: Generate narration ---
    audio_path = "/tmp/narration.mp3"
    print(">>> Generating TTS audio")
    tts = gTTS(text=script, lang='hi')
    tts.save(audio_path)

    audio = AudioSegment.from_mp3(audio_path)
    print(">>> Audio loaded, duration:", audio.duration_seconds)

    # --- Step 2: Detect speech segments ---
    chunks = silence.split_on_silence(
        audio,
        min_silence_len=500,
        silence_thresh=audio.dBFS - 14,
        keep_silence=250
    )
    print(">>> Split into", len(chunks), "chunks")

    # --- Step 3: Background video ---
    total_duration = audio.duration_seconds
    print(">>> Creating background video for", total_duration, "seconds")
    clip = mpy.ColorClip(size=(1280, 720), color=(0, 0, 0)) \
              .set_duration(total_duration) \
              .set_fps(24)

    # --- Step 4: Map script lines to audio chunks ---
    lines = script.split("\n")
    subtitles = []
    current_time = 0

    for i, chunk in enumerate(chunks):
        line = lines[i] if i < len(lines) else ""
        print(f">>> Subtitle {i}: '{line}' ({chunk.duration_seconds}s)")
        chunk_duration = chunk.duration_seconds

        txt_clip = make_text_clip(line, chunk_duration, current_time)
        subtitles.append(txt_clip)

        current_time += chunk_duration

    # --- Step 5: Combine video + subtitles + audio ---
    print(">>> Combining video + audio")
    final = mpy.CompositeVideoClip([clip, *subtitles])
    final = final.set_audio(mpy.AudioFileClip(audio_path))

    output_path = "/tmp/final_video.mp4"
    print(">>> Writing final video:", output_path)
    final.write_videofile(output_path, fps=24)

    print(">>> Handler finished successfully")
    return {"output": output_path}

runpod.serverless.start({"handler": handler})
