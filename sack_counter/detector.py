"""
Karung Detector — OpenCV DNN (tanpa library ML eksternal)
Menggunakan cv2.dnn untuk inference YOLOv8n ONNX.
Tidak butuh onnxruntime, torch, atau ultralytics.
"""

import cv2
import numpy as np
import os
import urllib.request
from dataclasses import dataclass

ONNX_MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.onnx"
DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(__file__), "yolov8n.onnx")

# Kelas COCO proxy untuk karung
TARGET_CLASSES = {24, 26, 28}  # backpack, handbag, suitcase
INPUT_SIZE = 640


@dataclass
class DetectionResult:
    count: int
    annotated_frame: np.ndarray
    confidence_scores: list
    bounding_boxes: list


class SackDetector:
    def __init__(self, model_path=DEFAULT_MODEL_PATH, confidence_threshold=0.40):
        self.confidence_threshold = confidence_threshold

        if not os.path.exists(model_path):
            print(f"[detector] Downloading model...")
            urllib.request.urlretrieve(ONNX_MODEL_URL, model_path)
            print("[detector] Download selesai.")

        self.net = cv2.dnn.readNetFromONNX(model_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        print("[detector] Model siap.")

    def detect_image(self, image: np.ndarray) -> DetectionResult:
        orig_h, orig_w = image.shape[:2]

        # Letterbox resize
        img_resized, scale, pad_x, pad_y = self._letterbox(image)

        # Buat blob
        blob = cv2.dnn.blobFromImage(
            img_resized, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE),
            swapRB=True, crop=False
        )
        self.net.setInput(blob)
        outputs = self.net.forward()  # shape: [1, 84, 8400]

        boxes, confs = self._postprocess(
            outputs, orig_w, orig_h, scale, pad_x, pad_y
        )

        annotated = image.copy()
        for i, (x1, y1, x2, y2) in enumerate(boxes):
            self._draw_box(annotated, x1, y1, x2, y2, confs[i], i + 1)
        self._draw_overlay(annotated, len(boxes))

        return DetectionResult(
            count=len(boxes),
            annotated_frame=annotated,
            confidence_scores=[round(c, 3) for c in confs],
            bounding_boxes=list(boxes),
        )

    def process_image_file(self, input_path: str, output_path: str) -> DetectionResult:
        image = cv2.imread(input_path)
        if image is None:
            raise ValueError(f"Tidak bisa membaca gambar: {input_path}")
        result = self.detect_image(image)
        cv2.imwrite(output_path, result.annotated_frame)
        return result

    def process_video_file(self, input_path: str, output_path: str, progress_callback=None) -> dict:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"Tidak bisa membuka video: {input_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        counts, idx = [], 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                r = self.detect_image(frame)
                counts.append(r.count)
                writer.write(r.annotated_frame)
                idx += 1
                if progress_callback:
                    progress_callback(idx, total, r.count)
        finally:
            cap.release()
            writer.release()

        if not counts:
            return {"total_frames": 0, "avg_count": 0, "max_count": 0, "min_count": 0}
        return {
            "total_frames": len(counts),
            "avg_count": round(sum(counts) / len(counts), 1),
            "max_count": max(counts),
            "min_count": min(counts),
        }

    def _letterbox(self, image):
        h, w = image.shape[:2]
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        padded[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
        return padded, scale, pad_x, pad_y

    def _postprocess(self, outputs, orig_w, orig_h, scale, pad_x, pad_y):
        preds = outputs[0].T  # [8400, 84]
        scores = preds[:, 4:]
        class_ids = np.argmax(scores, axis=1)
        confidences = np.max(scores, axis=1)

        mask = np.isin(class_ids, list(TARGET_CLASSES)) & (confidences >= self.confidence_threshold)
        preds_f = preds[mask]
        confs_f = confidences[mask]

        if len(preds_f) == 0:
            return [], []

        cx, cy, bw, bh = preds_f[:, 0], preds_f[:, 1], preds_f[:, 2], preds_f[:, 3]
        x1 = np.clip(((cx - bw / 2 - pad_x) / scale), 0, orig_w).astype(int)
        y1 = np.clip(((cy - bh / 2 - pad_y) / scale), 0, orig_h).astype(int)
        x2 = np.clip(((cx + bw / 2 - pad_x) / scale), 0, orig_w).astype(int)
        y2 = np.clip(((cy + bh / 2 - pad_y) / scale), 0, orig_h).astype(int)

        nms_boxes = [[int(x1[i]), int(y1[i]), int(x2[i] - x1[i]), int(y2[i] - y1[i])] for i in range(len(x1))]
        indices = cv2.dnn.NMSBoxes(nms_boxes, confs_f.tolist(), self.confidence_threshold, 0.45)

        if len(indices) == 0:
            return [], []

        idx = indices.flatten()
        boxes = [(x1[i], y1[i], x2[i], y2[i]) for i in idx]
        confs = [float(confs_f[i]) for i in idx]
        return boxes, confs

    def _draw_box(self, img, x1, y1, x2, y2, conf, n):
        color = (0, 200, 50)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"Karung #{n} ({conf:.0%})"
        (lw, lh), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(img, (x1, y1 - lh - bl - 4), (x1 + lw + 4, y1), color, -1)
        cv2.putText(img, label, (x1 + 2, y1 - bl - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)

    def _draw_overlay(self, img, count):
        text = f"Total Karung: {count}"
        (tw, th), bl = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)
        p = 10
        cv2.rectangle(img, (0, 0), (tw + p * 2, th + bl + p * 2), (0, 0, 0), -1)
        cv2.putText(img, text, (p, th + p), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 100), 2, cv2.LINE_AA)
