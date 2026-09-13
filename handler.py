import runpod
import moviepy.editor as mpy
from gtts import gTTS
from pydub import AudioSegment, silence

def handler(event):
    script = event.get("input", {}).get("script", None)
    if not script:
        return {"error": "No script provided."}

    # --- Step 1: Generate Hindi narration ---
    audio_path = "/tmp/narration.mp3"
    tts = gTTS(text=script, lang='hi')
    tts.save(audio_path)

    audio = AudioSegment.from_mp3(audio_path)

    # --- Step 2: Detect speech segments ---
    # Split audio into chunks based on silence
    chunks = silence.split_on_silence(
        audio,
        min_silence_len=500,  # ms
        silence_thresh=audio.dBFS - 14,
        keep_silence=250
    )

    # --- Step 3: Background video (static image loop for demo) ---
    total_duration = audio.duration_seconds
    clip = mpy.ImageClip("background.jpg").set_duration(total_duration).set_fps(24)

    # --- Step 4: Map script lines to audio chunks ---
    lines = script.split("\n")
    subtitles = []
    current_time = 0

    for i, chunk in enumerate(chunks):
        line = lines[i] if i < len(lines) else ""
        chunk_duration = chunk.duration_seconds

        txt_clip = mpy.TextClip(line, fontsize=40, color='white', bg_color='black')
        txt_clip = txt_clip.set_position(('center','bottom')) \
                           .set_duration(chunk_duration) \
                           .set_start(current_time)
        subtitles.append(txt_clip)

        current_time += chunk_duration

    # --- Step 5: Combine video + subtitles + audio ---
    final = mpy.CompositeVideoClip([clip, *subtitles])
    final = final.set_audio(mpy.AudioFileClip(audio_path))

    output_path = "/tmp/final_video.mp4"
    final.write_videofile(output_path, fps=24)

    return {"output": output_path}

runpod.serverless.start({"handler": handler})
