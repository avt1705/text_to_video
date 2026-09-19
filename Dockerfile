FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV COQUI_TOS_AGREED=1 

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    curl \
    ca-certificates \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

RUN python3 -m pip install --upgrade pip wheel
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir transformers==4.36.2

# Copy the pre-cropped individual frames
COPY frame1.png /app/frame1.png
COPY frame2.png /app/frame2.png
COPY frame3.png /app/frame3.png
COPY frame4.png /app/frame4.png

# Copy and sanitize the voice sample
COPY my_voice.wav /app/raw_voice.wav
RUN ffmpeg -i /app/raw_voice.wav -acodec pcm_s16le -ar 22050 -ac 1 /app/my_voice.wav

COPY handler.py .

CMD ["python3", "-u", "handler.py"]
