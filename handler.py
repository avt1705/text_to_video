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

    workspace = "/runpod-volume"
    os.makedirs(workspace, exist_ok=True)

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

    # --- Step 6: Upload to RunPod S3 bucket ---
    bucket_name = "5pg6wyk843"         # e.g. 5pg6wyk843
    region_name = "eu-ro-1" # e.g. eu-ro-1
    endpoint_url = "https://s3api-eu-ro-1.runpod.io"   # hard-coded RunPod endpoint

    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=region_name,
        endpoint_url=endpoint_url
    )

    # Upload files
    s3.upload_file(output_path, bucket_name, "final_video.mp4")
    s3.upload_file(audio_path, bucket_name, "narration.mp3")

    # Generate presigned URLs (24h expiry)
    video_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": "final_video.mp4"},
        ExpiresIn=86400
    )
    audio_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": "narration.mp3"},
        ExpiresIn=86400
    )

    return {
        "output": {
            "video_url": video_url,
            "audio_url": audio_url
        }
    }

runpod.serverless.start({"handler": handler})
