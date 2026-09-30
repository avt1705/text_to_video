FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for video rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Pin setuptools below 70 to prevent the pkg_resources crash
RUN python3 -m pip install --upgrade pip "setuptools<70.0.0" wheel

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your handler script and PNG assets
COPY . /app/

CMD ["python3", "-u", "handler.py"]
