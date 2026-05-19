from django.db import models
from django.conf import settings


class FaceRecord(models.Model):
    """用户人脸特征记录"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='face_record',
        verbose_name='用户'
    )

    face_url = models.URLField(max_length=500, verbose_name='人脸图片URL')

    embedding = models.JSONField(verbose_name='人脸特征向量')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tb_face_records'
        verbose_name = '人脸记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'FaceRecord({self.user.username})'


class FaceRecognitionLog(models.Model):
    """人脸识别日志记录"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='face_recognition_logs',
        verbose_name='用户'
    )

    capture_url = models.URLField(max_length=500, verbose_name='采集图片URL')
    
    matched = models.BooleanField(default=False, verbose_name='是否匹配')
    
    confidence = models.FloatField(default=0.0, verbose_name='相似度')
    
    message = models.CharField(max_length=200, blank=True, verbose_name='结果消息')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tb_face_recognition_logs'
        verbose_name = '人脸识别日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'FaceRecognitionLog({self.user.username}, matched={self.matched})'