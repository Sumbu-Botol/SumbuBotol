FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Download model YOLOv8n ONNX saat build (bukan saat startup)
RUN python -c "\
import urllib.request; \
print('Downloading yolov8n.onnx...'); \
urllib.request.urlretrieve(\
  'https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.onnx', \
  'yolov8n.onnx'); \
print('Done.')"

COPY . .
RUN mkdir -p uploads results

EXPOSE 8000
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
