FROM python:3.10-slim

# Install FFmpeg and Hindi fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-noto-core \
    fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy avatar images
COPY my_scene1.png /app/my_scene1.png
COPY my_scene2.png /app/my_scene2.png

# Copy RunPod handler
COPY handler.py /app/handler.py

# Start serverless worker
CMD ["python", "-u", "/app/handler.py"]
