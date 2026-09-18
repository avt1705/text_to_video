FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    git \
    curl \
    ca-certificates \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

# Pin setuptools to bypass the missing pkg_resources error
RUN python3 -m pip install --upgrade pip "setuptools<70.0.0" wheel

# Clone Wav2Lip and download pretrained checkpoints
RUN git clone https://github.com/Rudrabha/Wav2Lip.git /app/Wav2Lip

RUN mkdir -p /app/Wav2Lip/face_detection/detection/sfd && \
    curl -L -o /app/Wav2Lip/face_detection/detection/sfd/s3fd.pth "https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth"

RUN mkdir -p /app/Wav2Lip/checkpoints && \
    curl -L -o /app/Wav2Lip/checkpoints/wav2lip_gan.pth "https://huggingface.co/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth"

COPY requirements.txt .

RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py .

CMD ["python3", "-u", "handler.py"]
