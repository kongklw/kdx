from pydantic import BaseModel
from typing import Optional, List


class FaceUploadResponse(BaseModel):
    success: bool
    message: str
    face_id: Optional[str] = None


class FaceInfoResponse(BaseModel):
    has_face: bool
    face_id: Optional[str] = None
    uploaded_at: Optional[str] = None


class FaceMatchResult(BaseModel):
    matched: bool
    confidence: float
    message: str


class FaceDetectResult(BaseModel):
    detected: bool
    face_count: int
    faces: List[dict] = []