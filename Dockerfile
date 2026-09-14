# Use slim Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies: ffmpeg + fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY handler.py .

# Run handler directly
ENTRYPOINT ["python", "handler.py"]
