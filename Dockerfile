FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies and fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    git \
    curl \
    ca-certificates \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Download Google's Noto Sans Devanagari font for Hindi rendering
RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

RUN python3 -m pip install --upgrade pip setuptools wheel

COPY requirements.txt .

# Install PyTorch with CUDA 12.1 support for RunPod GPUs
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install remaining dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py .

CMD ["python3", "-u", "handler.py"]
