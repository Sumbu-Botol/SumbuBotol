# Sack Counting Detection

Sistem AI untuk mendeteksi dan menghitung jumlah **karung** secara otomatis dari foto maupun video, menggunakan **YOLOv8** dan **FastAPI**.

---

## Fitur

| Fitur | Keterangan |
|-------|-----------|
| Deteksi foto | Upload JPG/PNG/BMP/WEBP, dapatkan hasil dengan bounding box |
| Deteksi video | Upload MP4/AVI/MOV, setiap frame dianotasi, tampil statistik |
| Web UI | Antarmuka drag & drop yang mudah digunakan |
| REST API | Endpoint JSON untuk integrasi sistem lain |
| Custom model | Dukung fine-tuning model khusus karung |

---

## Cara Cepat Menjalankan

### 1. Install dependensi

```bash
cd sack_counter
pip install -r requirements.txt
```

### 2. Jalankan server

```bash
python app.py
# atau
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Buka browser

```
http://localhost:8000
```

---

## Struktur Project

```
sack_counter/
├── app.py              # FastAPI web application
├── detector.py         # YOLOv8 detection logic
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI
├── static/
│   ├── css/style.css
│   └── js/main.js
├── uploads/            # Temporary upload directory (auto-created)
└── results/            # Temporary result directory (auto-created)
```

---

## API Endpoints

### `POST /detect/image`
Upload gambar dan dapatkan jumlah karung.

**Request:** `multipart/form-data` — field `file`

**Response:**
```json
{
  "count": 12,
  "confidence_scores": [0.92, 0.87, 0.81],
  "bounding_boxes": [[x1, y1, x2, y2], ...],
  "result_url": "/results/result_abc123.jpg"
}
```

---

### `POST /detect/video`
Upload video dan dapatkan statistik hitungan karung per frame.

**Request:** `multipart/form-data` — field `file`

**Response:**
```json
{
  "total_frames": 300,
  "avg_count": 8.5,
  "max_count": 12,
  "min_count": 5,
  "result_url": "/results/result_abc123.mp4"
}
```

---

### `GET /results/{filename}`
Ambil file hasil (gambar/video). File akan dihapus otomatis setelah diunduh.

---

## Environment Variables

| Variabel | Default | Keterangan |
|----------|---------|-----------|
| `SACK_MODEL_PATH` | `yolov8n.pt` | Path ke file model YOLO |
| `CONFIDENCE_THRESHOLD` | `0.40` | Minimum confidence score |
| `PORT` | `8000` | Port server |

---

## Menggunakan Model Custom

Untuk akurasi terbaik dalam mendeteksi karung, disarankan melatih model khusus:

### 1. Siapkan dataset

Kumpulkan foto karung dan beri label menggunakan [Label Studio](https://labelstud.io/) atau [Roboflow](https://roboflow.com/) dengan format YOLO.

### 2. Struktur dataset

```
dataset/
├── images/
│   ├── train/
│   └── val/
├── labels/
│   ├── train/
│   └── val/
└── dataset.yaml
```

**Isi `dataset.yaml`:**
```yaml
path: ./dataset
train: images/train
val: images/val
nc: 1
names: ['karung']
```

### 3. Training

```python
from ultralytics import YOLO

model = YOLO("yolov8n.pt")   # mulai dari pretrained
model.train(data="dataset.yaml", epochs=100, imgsz=640)
```

### 4. Gunakan model hasil training

```bash
export SACK_MODEL_PATH=runs/detect/train/weights/best.pt
python app.py
```

---

## Teknologi

- **YOLOv8** (Ultralytics) — state-of-the-art object detection
- **OpenCV** — pemrosesan gambar dan video
- **FastAPI** — high-performance web framework
- **Python 3.10+**
