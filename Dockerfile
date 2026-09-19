FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install only the essential system packages (ffmpeg for video/audio, curl for font download)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download Google's Noto Sans Devanagari font directly into /app
RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

# Pin setuptools below version 70 to prevent gTTS crashes
RUN python3 -m pip install --upgrade pip "setuptools<70.0.0" wheel

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all repository files (frame1-4.png, handler.py, etc.) into /app
COPY . /app/

CMD ["python3", "-u", "handler.py"]
