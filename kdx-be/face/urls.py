from django.urls import path
from .views import FaceInfoView, FaceUploadView, FaceMatchView, FaceDetectView, FaceRecognitionLogView

app_name = 'face'

urlpatterns = [
    path('info', FaceInfoView.as_view(), name='face-info'),
    path('upload', FaceUploadView.as_view(), name='face-upload'),
    path('match', FaceMatchView.as_view(), name='face-match'),
    path('detect', FaceDetectView.as_view(), name='face-detect'),
    path('logs', FaceRecognitionLogView.as_view(), name='face-logs'),
]