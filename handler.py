import os
import re
import urllib.request
import base64
import textwrap
import traceback
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy
from gtts import gTTS

SOURCE_IMAGE_PATH = "/app/frame1.png"

def get_hindi_font(size=38):
    font_path = "/tmp/runpod_job/NotoSansDevanagari-Regular.ttf"
    
    # Download strictly if missing or suspiciously small to guarantee a clean binary
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 50000:
        print("Downloading clean Hindi font...", flush=True)
        url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
        urllib.request.urlretrieve(url, font_path)
            
    # Force TrueType load. No default fallback, as the default font causes latin-1 crashes on Hindi text.
    return ImageFont.truetype(font_path, size)

def create_subtitle_clip(text, duration, start_time):
    width, height = 1080, 180
    img = Image.new("RGBA", (width, height), (15, 23, 42, 220))
    draw = ImageDraw.Draw(img)

    font = get_hindi_font(38)

    wrapped = "\n".join(textwrap.wrap(text, width=45))
    
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=6)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    draw.multiline_text(
        ((width - text_w) // 2, (height - text_h) // 2),
        wrapped,
        font=font,
        fill=(255, 255, 255),
        align="center",
        spacing=6
    )
    
    # Apply precise start timing for line-by-line sync
    return (mpy.ImageClip(np.array(img))
            .set_duration(duration)
            .set_start(start_time)
            .set_position(("center", "bottom")))

def handler(event):
    try:
        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)

        audio_path = os.path.join(workdir, "speech.mp3")
        final_video_path = os.path.join(workdir, "final.mp4")

        input_data = event.get("input", {})
        audio_base64 = input_data.get("audio_base64", "")
        
        raw_script = input_data.get("script", "")
        if isinstance(raw_script, bytes):
            raw_script = raw_script.decode("utf-8")
        
        script = raw_script.strip()
        
        if not script and not audio_base64:
            return {"error": "No script or audio provided."}

        subtitle_clips = []

        # 1. Obtain Audio & Generate Timed Subtitles
        if audio_base64:
            # If pre-recorded audio is provided, fallback to a static whole-script subtitle
            with open(audio_path, "wb") as f:
                f.write(base64.b64decode(audio_base64))
                
            audio_dur = mpy.AudioFileClip(audio_path).duration
            if script:
                subtitle_clips.append(create_subtitle_clip(script, audio_dur, 0.0))
                
        else:
            # Process pure TTS line-by-line
            sentences = [s.strip() for s in re.split(r'[।.\n]+', script) if s.strip()]
            audio_clips = []
            current_time = 0.0
            
            print("Generating line-by-line audio and subtitles...", flush=True)
            for i, sentence in enumerate(sentences):
                chunk_path = os.path.join(workdir, f"chunk_{i}.mp3")
                
                tts = gTTS(text=sentence, lang="hi", slow=False)
                tts.save(chunk_path)
                
                audio_chunk = mpy.AudioFileClip(chunk_path)
                dur = audio_chunk.duration
                audio_clips.append(audio_chunk)
                
                subtitle_clips.append(create_subtitle_clip(sentence, dur, current_time))
                current_time += dur
                
            # Combine all chunks into the final audio track for SadTalker
            final_audio = mpy.concatenate_audioclips(audio_clips)
            final_audio.write_audiofile(audio_path, logger=None)

        # 2. Verify Single Image Source
        if not os.path.exists(SOURCE_IMAGE_PATH):
            return {"error": f"Missing frame1.png. Checked {SOURCE_IMAGE_PATH}"}

        # 3. Execute SadTalker AI Animation
        print("Starting SadTalker facial animation...", flush=True)
        sadtalker_cmd = [
            "python3", "inference.py",
            "--driven_audio", audio_path,
            "--source_image", SOURCE_IMAGE_PATH,
            "--result_dir", workdir,
            "--still",
            "--enhancer", "gfpgan"
        ]
        
        try:
            result = subprocess.run(sadtalker_cmd, check=True, capture_output=True, text=True, cwd="/app/SadTalker")
            print(result.stdout, flush=True)
        except subprocess.CalledProcessError as e:
            print(f"--- SADTALKER STDOUT ---\n{e.stdout}", flush=True)
            print(f"--- SADTALKER STDERR ---\n{e.stderr}", flush=True)
            return {"error": "SadTalker crashed.", "trace": e.stderr}

        # 4. Locate the AI-generated video
        generated_video_path = None
        for root, dirs, files in os.walk(workdir):
            for file in files:
                if file.endswith(".mp4") and file != "final.mp4":
                    generated_video_path = os.path.join(root, file)
                    break
                    
        if not generated_video_path:
            return {"error": "SadTalker failed to output an MP4 file."}

        # 5. Overlay Subtitles & Encode
        print("Applying timed subtitles and encoding...", flush=True)
        avatar_clip = mpy.VideoFileClip(generated_video_path).resize(width=1080)
        
        if subtitle_clips:
            final_clip = mpy.CompositeVideoClip([avatar_clip, *subtitle_clips])
        else:
            final_clip = avatar_clip

        final_clip.write_videofile(
            final_video_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
            verbose=False
        )

        with open(final_video_path, "rb") as f:
            encoded_video = base64.b64encode(f.read()).decode("utf-8")

        return {"output": {"video_base64": encoded_video}}

    except Exception as e:
        print(f"Execution Error Occurred: {e}", flush=True)
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    print("Starting AI Animation Worker...", flush=True)
    runpod.serverless.start({"handler": handler})
