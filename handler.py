import os
import re
import asyncio
import base64
import textwrap
import traceback
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import runpod
import moviepy.editor as mpy
from pydub import AudioSegment, silence
import edge_tts
from elevenlabs.client import ElevenLabs
from elevenlabs import save as el_save

pipe = None
FONT_PATH = "/app/NotoSansDevanagari.ttf"

def log(*args):
    print(*args, flush=True)

def ensure_model_loaded():
    global pipe
    if pipe is not None:
        return
    import torch
    from diffusers import StableDiffusionPipeline
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    load_kwargs = {}
    if device == "cuda":
        load_kwargs["torch_dtype"] = torch.float16
        
    pipe_local = StableDiffusionPipeline.from_pretrained("runwayml/stable-diffusion-v1-5", **load_kwargs)
    pipe_local.safety_checker = None
    if device == "cuda":
        pipe_local.enable_attention_slicing()
        
    pipe = pipe_local.to(device)

def generate_instructor_image(prompt: str, save_path: str):
    ensure_model_loaded()
    instructor_prompt = f"{prompt}, close up portrait, facing camera, looking directly at viewer, highly detailed"
    result = pipe(instructor_prompt, num_inference_steps=25, guidance_scale=7.5)
    img = result.images[0].resize((512, 512))
    img.save(save_path)

async def generate_edge_tts(text: str, output_path: str):
    # Free premium Indian neural voice
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural", rate="+0%")
    await communicate.save(output_path)

def generate_audio(script: str, output_path: str, api_key: str = None):
    if api_key:
        try:
            client = ElevenLabs(api_key=api_key)
            audio = client.generate(text=script, voice="Rachel", model="eleven_multilingual_v2")
            el_save(audio, output_path)
            return
        except Exception as e:
            log(f"ElevenLabs failed: {e}")
            
    asyncio.run(generate_edge_tts(script, output_path))

def run_wav2lip(face_path: str, audio_path: str, output_path: str):
    cmd = [
        "python3", "inference.py",
        "--checkpoint_path", "checkpoints/wav2lip_gan.pth",
        "--face", face_path,
        "--audio", audio_path,
        "--outfile", output_path,
        "--nosmooth",
        "--pads", "0", "20", "0", "0"  # Prevents chin cut-off
    ]
    subprocess.run(cmd, cwd="/app/Wav2Lip", check=True)

def split_sentences(text: str):
    parts = re.split(r'[।.!?\n]+', text)
    return [p.strip() for p in parts if p.strip()]

def create_subtitle_frame(text: str, width=1280, height=180):
    img = Image.new("RGBA", (width, height), (15, 23, 42, 220))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 36)
    except Exception:
        font = ImageFont.load_default()
        
    wrapped_text = "\n".join(textwrap.wrap(text, width=45))
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=8)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    pos_x = (width - text_w) // 2
    pos_y = (height - text_h) // 2
    
    draw.multiline_text((pos_x, pos_y), wrapped_text, font=font, fill=(255, 255, 255), align="center", spacing=8)
    return np.array(img)

def handler(event):
    try:
        input_data = event.get("input", {})
        script = input_data.get("script", "").strip()
        char_prompt = input_data.get("character_prompt", "Indian male teacher looking directly at camera, professional")
        elevenlabs_key = input_data.get("elevenlabs_key", "")
        
        if not script:
            return {"error": "Missing 'script' input."}
            
        workdir = "/tmp/runpod_job"
        os.makedirs(workdir, exist_ok=True)
        
        audio_path = os.path.join(workdir, "speech.wav")
        face_path = os.path.join(workdir, "face.png")
        animated_avatar_path = os.path.join(workdir, "avatar.mp4")
        final_video_path = os.path.join(workdir, "final.mp4")
        
        generate_audio(script, audio_path, elevenlabs_key)
        audio_segment = AudioSegment.from_file(audio_path)
        total_duration = audio_segment.duration_seconds
        
        generate_instructor_image(char_prompt, face_path)
        run_wav2lip(face_path, audio_path, animated_avatar_path)
        
        chunks = silence.split_on_silence(
            audio_segment, min_silence_len=400, silence_thresh=audio_segment.dBFS - 14, keep_silence=200
        )
        if not chunks:
            chunks = [audio_segment]
            
        sentences = split_sentences(script)
        
        bg_clip = mpy.ColorClip(size=(1280, 720), color=(15, 23, 42)).set_duration(total_duration)
        
        avatar_clip = (
            mpy.VideoFileClip(animated_avatar_path)
            .resize(width=500)
            .set_position((720, 80))
        )
        
        subtitle_clips = []
        current_time = 0.0
        for idx, chunk in enumerate(chunks):
            duration = chunk.duration_seconds
            subtitle_text = sentences[idx] if idx < len(sentences) else ""
            if subtitle_text:
                sub_frame = create_subtitle_frame(subtitle_text)
                sub_clip = mpy.ImageClip(sub_frame).set_duration(duration).set_start(current_time).set_position(("center", 560))
                subtitle_clips.append(sub_clip)
            current_time += duration
            
        final_video = mpy.CompositeVideoClip([bg_clip, avatar_clip, *subtitle_clips])
        final_video.write_videofile(final_video_path, fps=24, codec="libx264", audio_codec="aac", verbose=False, logger=None)
        
        with open(final_video_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            
        return {"output": {"video_base64": encoded}}
        
    except Exception as e:
        log("Error:", traceback.format_exc())
        return {"error": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
