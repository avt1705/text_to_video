FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for moviepy + OpenCV
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (from requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your project files
COPY . .

# Run your handler directly (matches your SDK version)
CMD ["python", "handler.py"]
