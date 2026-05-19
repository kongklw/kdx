from fastapi import APIRouter, File, UploadFile, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger

from ..core.config import Settings
from ..schemas.face import (
    FaceUploadResponse,
    FaceInfoResponse,
    FaceMatchResult,
    FaceDetectResult
)
from ..services.face_service import face_service
from ..api.deps import resolve_user_id


def create_face_router(settings: Settings):
    router = APIRouter(prefix="/face", tags=["face"])

    @router.get("/info", response_model=FaceInfoResponse)
    async def get_face_info(request: Request):
        """获取用户人脸信息"""
        user_id = resolve_user_id(request, settings)
        result = face_service.get_face_info(user_id)
        return JSONResponse(result)

    @router.post("/upload", response_model=FaceUploadResponse)
    async def upload_face(request: Request, file: UploadFile = File(...)):
        """上传人脸照片"""
        user_id = resolve_user_id(request, settings)
        
        try:
            image_data = await file.read()
            success, message, face_id = face_service.upload_face(user_id, image_data)
            return JSONResponse({
                "success": success,
                "message": message,
                "face_id": face_id
            })
        except Exception as e:
            logger.error(f"Face upload failed: {e}")
            return JSONResponse({
                "success": False,
                "message": f"上传失败: {str(e)}",
                "face_id": None
            })

    @router.post("/match", response_model=FaceMatchResult)
    async def match_face(request: Request, file: UploadFile = File(...)):
        """人脸识别（比对）"""
        user_id = resolve_user_id(request, settings)
        
        try:
            image_data = await file.read()
            matched, confidence, message = face_service.match_face(user_id, image_data)
            return JSONResponse({
                "matched": matched,
                "confidence": confidence,
                "message": message
            })
        except Exception as e:
            logger.error(f"Face match failed: {e}")
            return JSONResponse({
                "matched": False,
                "confidence": 0.0,
                "message": f"识别失败: {str(e)}"
            })

    @router.post("/detect", response_model=FaceDetectResult)
    async def detect_faces(file: UploadFile = File(...)):
        """检测图片中的人脸"""
        try:
            image_data = await file.read()
            success, faces = face_service.detect_faces(image_data)
            return JSONResponse({
                "detected": success,
                "face_count": len(faces),
                "faces": faces
            })
        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return JSONResponse({
                "detected": False,
                "face_count": 0,
                "faces": []
            })

    return router