FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# This creates the /app folder inside RunPod
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsm6 libxext6 git curl ca-certificates fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Download Hindi font
RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

RUN python3 -m pip install --upgrade pip setuptools wheel
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir -r requirements.txt

# This copies handler.py AND frame1.png, frame2.png etc. from GitHub into the /app folder in RunPod
COPY handler.py .
COPY *.png ./

CMD ["python3", "-u", "handler.py"]
