FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for audio/video
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files into container
COPY . .

# Quick check to confirm handler.py is present
RUN ls -l /app

# Run handler directly
CMD ["python", "handler.py"]
