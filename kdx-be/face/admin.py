from django.contrib import admin
from .models import FaceRecord


@admin.register(FaceRecord)
class FaceRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'face_url', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['user__username', 'user__phone']
    readonly_fields = ['embedding', 'created_at', 'updated_at']
    ordering = ['-created_at']