FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl git libsm6 libxext6 libgl1-mesa-glx wget \
    && rm -rf /var/lib/apt/lists/*

# Download Hindi font
RUN curl -L -o /app/NotoSansDevanagari.ttf "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari-Bold.ttf"

# Clone the SadTalker animation repository
RUN git clone https://github.com/OpenTalker/SadTalker.git /app/SadTalker

# CRITICAL FIX: Pin setuptools below 70 to prevent pkg_resources crash
RUN python3 -m pip install --upgrade pip "setuptools<70.0.0" wheel

# Install the neural network dependencies
RUN pip install --no-cache-dir -r /app/SadTalker/requirements.txt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the pre-trained animation weights into the container
WORKDIR /app/SadTalker
RUN bash scripts/download_models.sh

WORKDIR /app
# Copy your handler and your single frame1.png
COPY . /app/

CMD ["python3", "-u", "handler.py"]
