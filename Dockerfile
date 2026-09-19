FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Auto-agree to the open-source TTS terms of service
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

# Install PyTorch for GPU acceleration
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your visual sprites and your voice sample
COPY my_scene1.png /app/my_scene1.png
COPY my_scene2.png /app/my_scene2.png
COPY my_scene3.png /app/my_scene3.png
COPY my_voice.wav /app/my_voice.wav

COPY handler.py .

CMD ["python3", "-u", "handler.py"]
