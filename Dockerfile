# Use slim Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies: ffmpeg, ImageMagick, fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    imagemagick \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Patch ImageMagick security policy to allow MoviePy TextClip
RUN sed -i 's/<policy domain="path" rights="none" pattern="@.*"\/>/<policy domain="path" rights="read|write" pattern="@.*"\/>/g' /etc/ImageMagick-6/policy.xml || true

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY handler.py .

# Force container to run your handler
ENTRYPOINT ["python", "handler.py"]
