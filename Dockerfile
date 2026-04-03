FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only (jauh lebih kecil dari versi CUDA)
RUN pip install --upgrade pip && \
    pip install torch torchvision \
        --index-url https://download.pytorch.org/whl/cpu

# Install app dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy app
COPY . .

# Buat direktori upload/result
RUN mkdir -p uploads results

EXPOSE 8000

CMD uvicorn app:app --host 0.0.0.0 --port $PORT
