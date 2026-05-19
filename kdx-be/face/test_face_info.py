#!/usr/bin/env python3
"""
测试 face/info 接口是否正确返回人脸状态
"""

import os
import sys
import django

# 设置 Django 环境
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kdemo.settings')
django.setup()

from face.models import FaceRecord
from django.contrib.auth import get_user_model

User = get_user_model()


def test_face_info():
    """测试人脸信息查询"""
    print("=== 测试 face/info 接口逻辑 ===")
    
    # 获取第一个用户（假设存在）
    user = User.objects.first()
    if not user:
        print("✗ 没有找到用户")
        return
    
    print(f"用户: {user.username}")
    
    # 查询人脸记录
    face_record = FaceRecord.objects.filter(user=user).first()
    
    if face_record:
        print(f"人脸记录存在:")
        print(f"  face_url: {face_record.face_url}")
        print(f"  created_at: {face_record.created_at}")
        print(f"  has_face 应该为: True")
        
        # 检查 face_url 是否为空
        if not face_record.face_url:
            print("✗ 警告: face_url 为空！")
        else:
            print("✓ face_url 正常")
    else:
        print("人脸记录不存在")
        print(f"has_face 应该为: False")


if __name__ == "__main__":
    test_face_info()