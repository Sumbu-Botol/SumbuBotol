"""
Sack Counting Detector
======================
Menggunakan YOLOv8 untuk mendeteksi dan menghitung karung dari gambar atau video.
Model dapat di-fine-tune menggunakan dataset karung, atau menggunakan kelas 'backpack'/'suitcase'
dari COCO sebagai baseline sampai dataset custom tersedia.
"""

import cv2
import numpy as np
import os
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


@dataclass
class DetectionResult:
    count: int
    annotated_frame: np.ndarray
    confidence_scores: list[float]
    bounding_boxes: list[tuple]


class SackDetector:
    """
    Detektor karung menggunakan YOLOv8.

    Modes:
      - 'pretrained'  : Pakai model COCO pretrained, deteksi kelas yg mirip karung
      - 'custom'      : Pakai model custom yang sudah di-train dengan data karung
    """

    # Kelas dari COCO yang bisa dipakai sebagai proxy karung sebelum model custom tersedia
    COCO_SACK_PROXY_CLASSES = {
        24: "backpack",
        26: "handbag",
        28: "suitcase",
        # Tambahkan kelas lain jika relevan
    }

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.40,
        custom_class_ids: Optional[list[int]] = None,
    ):
        """
        Args:
            model_path: Path ke file model YOLO (.pt).
                        'yolov8n.pt' akan auto-download jika belum ada.
                        Gunakan path custom model jika sudah punya data karung.
            confidence_threshold: Minimum confidence score (0.0 - 1.0)
            custom_class_ids: List ID kelas untuk dideteksi.
                              None = gunakan proxy COCO untuk karung.
        """
        if not YOLO_AVAILABLE:
            raise RuntimeError(
                "Ultralytics tidak terinstall. Jalankan: pip install ultralytics"
            )

        self.confidence_threshold = confidence_threshold
        self.model = YOLO(model_path)

        # Tentukan kelas yang akan dideteksi
        if custom_class_ids is not None:
            self.target_class_ids = custom_class_ids
        else:
            self.target_class_ids = list(self.COCO_SACK_PROXY_CLASSES.keys())

        # Cek apakah model custom (class 0 = sack)
        self.is_custom_model = self._check_custom_model()

    def _check_custom_model(self) -> bool:
        """Cek apakah model memiliki kelas 'sack' atau 'karung'."""
        names = self.model.names
        for name in names.values():
            if name.lower() in ("sack", "karung", "bag", "rice_bag", "rice_sack"):
                return True
        return False

    def detect_image(self, image: np.ndarray) -> DetectionResult:
        """
        Deteksi karung pada satu frame gambar.

        Args:
            image: Gambar dalam format BGR (OpenCV)

        Returns:
            DetectionResult dengan jumlah, frame teranotasi, scores, dan boxes
        """
        results = self.model(image, verbose=False)[0]

        count = 0
        confidence_scores = []
        bounding_boxes = []
        annotated = image.copy()

        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])

            # Filter berdasarkan kelas dan confidence
            if self._is_target_class(cls_id) and conf >= self.confidence_threshold:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                count += 1
                confidence_scores.append(round(conf, 3))
                bounding_boxes.append((x1, y1, x2, y2))

                # Gambar bounding box
                self._draw_box(annotated, x1, y1, x2, y2, conf, count)

        # Tampilkan total count di pojok kiri atas
        self._draw_count_overlay(annotated, count)

        return DetectionResult(
            count=count,
            annotated_frame=annotated,
            confidence_scores=confidence_scores,
            bounding_boxes=bounding_boxes,
        )

    def process_image_file(self, input_path: str, output_path: str) -> DetectionResult:
        """
        Proses file gambar dari disk.

        Args:
            input_path: Path gambar input
            output_path: Path untuk menyimpan gambar hasil anotasi
        """
        image = cv2.imread(input_path)
        if image is None:
            raise ValueError(f"Tidak bisa membaca gambar: {input_path}")

        result = self.detect_image(image)
        cv2.imwrite(output_path, result.annotated_frame)
        return result

    def process_video_file(
        self,
        input_path: str,
        output_path: str,
        progress_callback=None,
    ) -> dict:
        """
        Proses file video, anotasi setiap frame, dan simpan video hasil.

        Args:
            input_path: Path video input
            output_path: Path video output (MP4)
            progress_callback: Fungsi callback(frame_idx, total_frames, count)

        Returns:
            dict berisi statistik: total_frames, avg_count, max_count, min_count
        """
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"Tidak bisa membuka video: {input_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        frame_counts = []
        frame_idx = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                result = self.detect_image(frame)
                frame_counts.append(result.count)
                writer.write(result.annotated_frame)

                frame_idx += 1
                if progress_callback:
                    progress_callback(frame_idx, total_frames, result.count)
        finally:
            cap.release()
            writer.release()

        if not frame_counts:
            return {"total_frames": 0, "avg_count": 0, "max_count": 0, "min_count": 0}

        return {
            "total_frames": len(frame_counts),
            "avg_count": round(sum(frame_counts) / len(frame_counts), 1),
            "max_count": max(frame_counts),
            "min_count": min(frame_counts),
        }

    def _is_target_class(self, cls_id: int) -> bool:
        if self.is_custom_model:
            # Untuk custom model, semua kelas dianggap karung (atau sesuai mapping)
            return True
        return cls_id in self.target_class_ids

    def _draw_box(
        self,
        image: np.ndarray,
        x1: int, y1: int, x2: int, y2: int,
        conf: float,
        number: int,
    ):
        """Gambar bounding box + label pada frame."""
        color = (0, 200, 50)  # Hijau
        thickness = 2

        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)

        label = f"Karung #{number} ({conf:.0%})"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        (lw, lh), baseline = cv2.getTextSize(label, font, font_scale, 1)

        # Background label
        cv2.rectangle(
            image,
            (x1, y1 - lh - baseline - 4),
            (x1 + lw + 4, y1),
            color,
            -1,
        )
        cv2.putText(
            image,
            label,
            (x1 + 2, y1 - baseline - 2),
            font,
            font_scale,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    def _draw_count_overlay(self, image: np.ndarray, count: int):
        """Tampilkan total hitungan di pojok kiri atas frame."""
        text = f"Total Karung: {count}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 2
        color_bg = (0, 0, 0)
        color_text = (0, 255, 100)

        (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
        padding = 10

        cv2.rectangle(
            image,
            (0, 0),
            (tw + padding * 2, th + baseline + padding * 2),
            color_bg,
            -1,
        )
        cv2.putText(
            image,
            text,
            (padding, th + padding),
            font,
            font_scale,
            color_text,
            thickness,
            cv2.LINE_AA,
        )
