FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (ffmpeg is strictly required for moviepy video rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Pin setuptools below 70 to prevent the pkg_resources crash with imageio
RUN python3 -m pip install --upgrade pip "setuptools<70.0.0" wheel

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your handler.py and your assets (my_scene1.jpg, my_scene2.jpg)
COPY . /app/

CMD ["python3", "-u", "handler.py"]
