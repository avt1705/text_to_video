import runpod
import moviepy.editor as mpy
from gtts import gTTS
from pydub import AudioSegment, silence
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os
import boto3

def make_text_clip(text, duration, start):
    img = Image.new("RGB", (1280, 200), color="black")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    draw.text((50, 50), text, font=font, fill="white")
    frame = np.array(img)
    return mpy.ImageClip(frame).set_duration(duration).set_start(start).set_position(("center", "bottom"))

def handler(event):
    script = event.get("input", {}).get("script", None)
    if not script:
        return {"error": "No script provided."}

    # --- Ensure runpod-volume exists and clean it ---
    workspace = "/runpod-volume"
    os.makedirs(workspace, exist_ok=True)
    for f in os.listdir(workspace):
        try:
            os.remove(os.path.join(workspace, f))
        except Exception:
            pass

    # --- Step 1: Generate narration ---
    audio_path = os.path.join(workspace, "narration.mp3")
    tts = gTTS(text=script, lang='hi')
    tts.save(audio_path)

    audio = AudioSegment.from_mp3(audio_path)

    # --- Step 2: Detect speech segments ---
    chunks = silence.split_on_silence(
        audio,
        min_silence_len=500,
        silence_thresh=audio.dBFS - 14,
        keep_silence=250
    )

    # --- Step 3: Background video ---
    total_duration = audio.duration_seconds
    clip = mpy.ColorClip(size=(1280, 720), color=(0, 0, 0)).set_duration(total_duration).set_fps(24)

    # --- Step 4: Map script lines to audio chunks ---
    lines = script.split("\n")
    subtitles = []
    current_time = 0
    for i, chunk in enumerate(chunks):
        line = lines[i] if i < len(lines) else ""
        txt_clip = make_text_clip(line, chunk.duration_seconds, current_time)
        subtitles.append(txt_clip)
        current_time += chunk.duration_seconds

    # --- Step 5: Combine video + subtitles + audio ---
    final = mpy.CompositeVideoClip([clip, *subtitles])
    final = final.set_audio(mpy.AudioFileClip(audio_path))

    output_path = os.path.join(workspace, "final_video.mp4")
    final.write_videofile(output_path, fps=24)

    # --- Step 6: Generate pre-signed S3 URL ---
    # Assumes your network volume is backed by S3 and credentials are available
    bucket_name = os.environ.get("S3_BUCKET")  # set this in your endpoint environment
    s3_key_video = "final_video.mp4"
    s3_key_audio = "narration.mp3"

    s3 = boto3.client("s3")

    # Upload files to S3
    s3.upload_file(output_path, bucket_name, s3_key_video)
    s3.upload_file(audio_path, bucket_name, s3_key_audio)

    # Generate presigned URLs
    video_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": s3_key_video},
        ExpiresIn=3600  # 1 hour expiry
    )
    audio_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": s3_key_audio},
        ExpiresIn=3600
    )

    return {
        "output": {
            "video_url": video_url,
            "audio_url": audio_url
        }
    }

runpod.serverless.start({"handler": handler})
