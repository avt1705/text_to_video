FROM python:3.10-slim

# Install system dependencies required for video rendering and fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    fonts-noto \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your avatar frames and the handler script
COPY my_scene1.png /app/my_scene1.png
COPY my_scene2.png /app/my_scene2.png
COPY handler.py /app/handler.py

# Start the RunPod serverless handler
CMD ["python", "-u", "/app/handler.py"]
