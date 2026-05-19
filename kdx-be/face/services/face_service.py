import os
import logging
import threading
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path

# 设置环境变量禁用 CPU 优化，解决某些 CPU 不支持高级指令集的问题
os.environ.setdefault('ORT_DISABLE_CPU_OPTIMIZATION', '1')
os.environ.setdefault('ONNXRUNTIME_DISABLE_OPTIMIZATION', '1')

# 必须在设置环境变量后再导入 InsightFace
from insightface.app import FaceAnalysis
import cv2
import numpy as np
import requests
from scipy.spatial.distance import cosine

logger = logging.getLogger(__name__)


class FaceRecognitionService:
    """人脸识别服务 - 基于 InsightFace 实现的单例服务类"""

    _instance: Optional['FaceRecognitionService'] = None
    _face_app: Optional[FaceAnalysis] = None
    _lock = threading.Lock()
    _init_successful: bool = False

    def __new__(cls) -> 'FaceRecognitionService':
        """线程安全的单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_initialized(self) -> bool:
        """确保 InsightFace 已初始化（懒加载 + 线程安全）"""
        if self._face_app is None and not self._init_successful:
            with self._lock:
                if self._face_app is None and not self._init_successful:
                    self._init_face_analysis()
        return self._init_successful

    def _init_face_analysis(self) -> None:
        """初始化 InsightFace FaceAnalysis 引擎"""
        try:
            logger.info("Initializing InsightFace...")
            self._face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self._face_app.prepare(ctx_id=-1, det_size=(640, 640))
            self._init_successful = True
            logger.info("InsightFace initialized successfully")
        except Exception as e:
            logger.exception('Failed to initialize InsightFace')
            self._init_successful = False

    def download_image_from_url(self, url: str) -> Optional[np.ndarray]:
        """从 URL 下载图片并转换为 OpenCV BGR 格式"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            image_array = np.frombuffer(response.content, dtype=np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

            if image is None:
                logger.error("Failed to decode image: invalid image format")
                return None

            return image

        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading image from {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading image from {url}: {e}")
            return None

    def detect_faces(self, image: np.ndarray) -> Tuple[bool, List[Dict[str, Any]]]:
        """检测图片中的所有人脸"""
        if not self._ensure_initialized():
            return False, []

        try:
            faces = self._face_app.get(image)
            results = []

            for face in faces:
                results.append({
                    'bbox': face.bbox.tolist(),
                    'confidence': float(face.det_score),
                    'landmarks': face.kps.tolist() if hasattr(face, 'kps') else [],
                    'embedding': face.embedding.tolist() if hasattr(face, 'embedding') else []
                })

            logger.debug(f"Detected {len(results)} face(s) in image")
            return True, results

        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return False, []

    def extract_embedding(self, image: np.ndarray) -> Optional[np.ndarray]:
        """提取图片中最清晰人脸的特征向量"""
        if not self._ensure_initialized():
            return None

        try:
            faces = self._face_app.get(image)

            if len(faces) == 0:
                logger.warning("No face detected in image")
                return None

            if len(faces) > 1:
                logger.warning(f"Multiple faces ({len(faces)}) detected, using the one with highest confidence")
                faces.sort(key=lambda f: f.det_score, reverse=True)

            return faces[0].embedding

        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return None

    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """计算两个人脸特征的余弦相似度（范围 0-1，值越大越相似）"""
        try:
            if embedding1.shape != embedding2.shape:
                logger.error(f"Embedding shape mismatch: {embedding1.shape} vs {embedding2.shape}")
                return 0.0

            similarity = 1 - cosine(embedding1, embedding2)
            return float(max(0.0, min(1.0, similarity)))
        except Exception as e:
            logger.error(f"Similarity computation failed: {e}")
            return 0.0

    def match_face(self, stored_embedding: np.ndarray, test_image_url: str, threshold: float = 0.5) -> Tuple[
        bool, float, str]:
        """
        比对两张人脸是否匹配

        Args:
            stored_embedding: 已存储的人脸特征向量
            test_image_url: 测试图片的 URL
            threshold: 相似度阈值，默认 0.5（建议使用 0.6-0.7 作为严格匹配阈值）

        Returns:
            (is_match, confidence, message)
        """
        if not self._ensure_initialized():
            return False, 0.0, "人脸识别服务未初始化"

        test_image = self.download_image_from_url(test_image_url)
        if test_image is None:
            return False, 0.0, "无法下载测试图片"

        test_embedding = self.extract_embedding(test_image)
        if test_embedding is None:
            return False, 0.0, "图片中未检测到人脸"

        confidence = self.compute_similarity(stored_embedding, test_embedding)

        if confidence >= threshold:
            return True, confidence, "人脸识别成功"
        else:
            return False, confidence, "人脸不匹配"


face_service = FaceRecognitionService()


