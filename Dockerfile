FROM python:3.10-slim

# Install system utilities, ffmpeg, and base fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    fonts-noto \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bundle avatar frames and handler
COPY my_scene1.png /app/my_scene1.png
COPY my_scene2.png /app/my_scene2.png
COPY handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
