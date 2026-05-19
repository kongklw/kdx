import os
import json
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from datetime import datetime
from loguru import logger

import cv2
import numpy as np
from scipy.spatial.distance import cosine

try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False
    logger.warning("InsightFace not installed, face recognition will be disabled")


class FaceService:
    def __init__(self, data_dir: str = "data/faces"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化 InsightFace
        self.face_app = None
        if INSIGHTFACE_AVAILABLE:
            try:
                self.face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
                self.face_app.prepare(ctx_id=-1, det_size=(640, 640))
                logger.info("InsightFace initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize InsightFace: {e}")
        
        # 人脸特征存储
        self.features: Dict[str, np.ndarray] = {}
        self.load_features()
    
    def load_features(self):
        """加载已保存的人脸特征"""
        features_file = self.data_dir / "features.json"
        if features_file.exists():
            try:
                with open(features_file, 'r') as f:
                    data = json.load(f)
                    for user_id, embedding_list in data.items():
                        if embedding_list:
                            self.features[user_id] = np.array(embedding_list)
            except Exception as e:
                logger.error(f"Failed to load features: {e}")
    
    def save_features(self):
        """保存人脸特征到文件"""
        features_file = self.data_dir / "features.json"
        try:
            data = {user_id: embedding.tolist() for user_id, embedding in self.features.items()}
            with open(features_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to save features: {e}")
    
    def detect_faces(self, image_data: bytes) -> Tuple[bool, List[dict]]:
        """检测图片中的人脸"""
        if not self.face_app:
            return False, []
        
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return False, []
            
            faces = self.face_app.get(img)
            result = []
            
            for face in faces:
                result.append({
                    'bbox': face.bbox.tolist(),
                    'confidence': float(face.det_score),
                    'landmarks': face.kps.tolist()
                })
            
            return True, result
        
        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return False, []
    
    def extract_feature(self, image_data: bytes) -> Optional[np.ndarray]:
        """提取人脸特征"""
        if not self.face_app:
            return None
        
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return None
            
            faces = self.face_app.get(img)
            if len(faces) == 0:
                return None
            
            # 返回第一张人脸的特征
            return faces[0].embedding
        
        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return None
    
    def upload_face(self, user_id: str, image_data: bytes) -> Tuple[bool, str, Optional[str]]:
        """上传用户人脸照片"""
        if not self.face_app:
            return False, "人脸识别服务未初始化", None
        
        embedding = self.extract_feature(image_data)
        if embedding is None:
            return False, "未检测到人脸", None
        
        # 保存特征
        self.features[user_id] = embedding
        self.save_features()
        
        # 保存原始图片（可选）
        face_dir = self.data_dir / user_id
        face_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        face_id = f"{user_id}_{timestamp}"
        
        # 保存图片
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        img_path = face_dir / f"{face_id}.jpg"
        cv2.imwrite(str(img_path), img)
        
        logger.info(f"Face uploaded for user {user_id}, face_id: {face_id}")
        return True, "人脸照片上传成功", face_id
    
    def get_face_info(self, user_id: str) -> Dict[str, Optional[str]]:
        """获取用户人脸信息"""
        if user_id in self.features:
            return {
                'has_face': True,
                'face_id': user_id,
                'uploaded_at': self._get_upload_time(user_id)
            }
        return {
            'has_face': False,
            'face_id': None,
            'uploaded_at': None
        }
    
    def _get_upload_time(self, user_id: str) -> Optional[str]:
        """获取上传时间"""
        face_dir = self.data_dir / user_id
        if face_dir.exists():
            files = list(face_dir.glob("*.jpg"))
            if files:
                latest = max(files, key=lambda f: f.stat().st_mtime)
                timestamp = latest.stem.split("_")[-1]
                return datetime.strptime(timestamp, "%Y%m%d_%H%M%S").isoformat()
        return None
    
    def match_face(self, user_id: str, image_data: bytes) -> Tuple[bool, float, str]:
        """识别人脸是否匹配"""
        if not self.face_app:
            return False, 0.0, "人脸识别服务未初始化"
        
        if user_id not in self.features:
            return False, 0.0, "用户未上传人脸照片"
        
        embedding = self.extract_feature(image_data)
        if embedding is None:
            return False, 0.0, "未检测到人脸"
        
        # 计算相似度
        stored_embedding = self.features[user_id]
        similarity = 1 - cosine(embedding, stored_embedding)
        
        # 阈值判断
        threshold = 0.5
        if similarity >= threshold:
            return True, similarity, "人脸识别成功"
        else:
            return False, similarity, "人脸识别失败"


# 单例模式
face_service = FaceService()