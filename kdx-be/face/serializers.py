from rest_framework import serializers
from .models import FaceRecord


class FaceRecordSerializer(serializers.ModelSerializer):
    """人脸记录序列化器"""

    class Meta:
        model = FaceRecord
        fields = ['id', 'face_url', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class FaceUploadSerializer(serializers.Serializer):
    """人脸上传请求序列化器"""
    face_url = serializers.URLField(required=True, help_text="人脸图片URL")


class FaceMatchResultSerializer(serializers.Serializer):
    """人脸比对结果序列化器"""
    matched = serializers.BooleanField()
    confidence = serializers.FloatField()
    message = serializers.CharField()


class FaceInfoSerializer(serializers.Serializer):
    """人脸信息序列化器"""
    has_face = serializers.BooleanField()
    face_url = serializers.URLField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)