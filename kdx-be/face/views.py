import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import FaceRecord, FaceRecognitionLog
from .serializers import (
    FaceRecordSerializer,
    FaceUploadSerializer,
    FaceMatchResultSerializer,
    FaceInfoSerializer
)

logger = logging.getLogger(__name__)


def _get_face_service():
    from .services.face_service import face_service
    return face_service


class FaceInfoView(APIView):
    """获取用户人脸信息"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取当前用户的人脸信息"""
        try:
            face_record = FaceRecord.objects.filter(user=request.user).first()

            if face_record:
                data = {
                    'has_face': True,
                    'face_url': face_record.face_url,
                    'created_at': face_record.created_at
                }
            else:
                data = {
                    'has_face': False,
                    'face_url': None,
                    'created_at': None
                }

            serializer = FaceInfoSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            return Response({'code': 200, 'data': serializer.data, 'msg': 'ok'})

        except Exception as e:
            logger.error(f"Failed to get face info: {e}")
            return Response({'code': 500, 'data': None, 'msg': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FaceUploadView(APIView):
    """上传人脸照片"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """上传人脸照片并提取特征"""
        try:
            face_service = _get_face_service()
            serializer = FaceUploadSerializer(data=request.data)

            if not serializer.is_valid():
                return Response({'code': 400, 'data': None, 'msg': serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)
            print(f'111111 {serializer.data}')
            face_url = serializer.validated_data['face_url']

            image = face_service.download_image_from_url(face_url)
            if image is None:
                return Response({'code': 400, 'data': None, 'msg': '无法下载图片'}, status=status.HTTP_400_BAD_REQUEST)

            embedding = face_service.extract_embedding(image)
            if embedding is None:
                return Response({'code': 400, 'data': None, 'msg': '图片中未检测到人脸，请上传清晰的人脸照片'},
                                status=status.HTTP_400_BAD_REQUEST)

            face_record, created = FaceRecord.objects.update_or_create(
                user=request.user,
                defaults={
                    'face_url': face_url,
                    'embedding': embedding.tolist()
                }
            )

            action = '创建' if created else '更新'
            return Response({
                'code': 200,
                'data': FaceRecordSerializer(face_record).data,
                'msg': f'人脸照片{action}成功'
            })

        except Exception as e:
            logger.error(f"Failed to upload face: {e}")
            return Response({'code': 500, 'data': None, 'msg': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FaceMatchView(APIView):
    """人脸识别（比对）"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """识别人脸是否匹配"""
        try:
            face_service = _get_face_service()
            face_record = FaceRecord.objects.filter(user=request.user).first()

            if not face_record:
                return Response({
                    'code': 400,
                    'data': {'matched': False, 'confidence': 0, 'message': '请先上传人脸照片'},
                    'msg': '请先上传人脸照片'
                }, status=status.HTTP_400_BAD_REQUEST)

            face_url = request.data.get('face_url')
            if not face_url:
                return Response({'code': 400, 'data': None, 'msg': 'face_url 参数必填'},
                                status=status.HTTP_400_BAD_REQUEST)

            stored_embedding = face_record.embedding
            if isinstance(stored_embedding, list):
                import numpy as np
                stored_embedding = np.array(stored_embedding)

            matched, confidence, message = face_service.match_face(
                stored_embedding=stored_embedding,
                test_image_url=face_url,
                threshold=0.5
            )

            # 记录识别日志，保存采集的图片URL
            FaceRecognitionLog.objects.create(
                user=request.user,
                capture_url=face_url,
                matched=matched,
                confidence=confidence,
                message=message
            )

            result_data = {
                'matched': matched,
                'confidence': confidence,
                'message': message
            }

            return Response({
                'code': 200,
                'data': result_data,
                'msg': 'ok'
            })

        except Exception as e:
            logger.error(f"Failed to match face: {e}")
            return Response({'code': 500, 'data': None, 'msg': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FaceDetectView(APIView):
    """检测图片中的人脸"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """检测图片中的人脸"""
        try:
            face_service = _get_face_service()
            face_url = request.data.get('face_url')
            if not face_url:
                return Response({'code': 400, 'data': None, 'msg': 'face_url 参数必填'},
                                status=status.HTTP_400_BAD_REQUEST)



            image = face_service.download_image_from_url(face_url)
            if image is None:
                return Response({'code': 400, 'data': None, 'msg': '无法下载图片'}, status=status.HTTP_400_BAD_REQUEST)

            success, faces = face_service.detect_faces(image)

            return Response({
                'code': 200,
                'data': {
                    'detected': success,
                    'face_count': len(faces),
                    'faces': faces
                },
                'msg': 'ok'
            })

        except Exception as e:
            logger.error(f"Failed to detect faces: {e}")
            return Response({'code': 500, 'data': None, 'msg': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FaceRecognitionLogView(APIView):
    """获取人脸识别日志"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的人脸识别历史记录"""
        try:
            logs = FaceRecognitionLog.objects.filter(user=request.user).order_by('-created_at')
            
            logs_data = [{
                'id': log.id,
                'capture_url': log.capture_url,
                'matched': log.matched,
                'confidence': log.confidence,
                'message': log.message,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for log in logs]

            return Response({
                'code': 200,
                'data': logs_data,
                'msg': 'ok'
            })

        except Exception as e:
            logger.error(f"Failed to get recognition logs: {e}")
            return Response({'code': 500, 'data': None, 'msg': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
