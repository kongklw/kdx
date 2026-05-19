#!/usr/bin/env python3
"""
InsightFace 诊断测试脚本

用于测试 InsightFace 是否能正常初始化和运行，帮助排查 face/upload 接口失败的问题。
"""

import os
import sys
import traceback
import numpy as np
import cv2

# 添加项目路径到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_insightface_import():
    """测试 InsightFace 导入"""
    print("\n=== 1. 测试 InsightFace 导入 ===")
    try:
        from insightface.app import FaceAnalysis
        print("✓ InsightFace 导入成功")
        return True
    except ImportError as e:
        print(f"✗ InsightFace 导入失败: {e}")
        return False


def test_face_analysis_init():
    """测试 FaceAnalysis 初始化"""
    print("\n=== 2. 测试 FaceAnalysis 初始化 ===")
    try:
        from insightface.app import FaceAnalysis
        
        print("正在初始化 FaceAnalysis...")
        app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        
        print("正在准备模型...")
        app.prepare(ctx_id=-1, det_size=(640, 640))
        
        print("✓ FaceAnalysis 初始化成功")
        return app
    except Exception as e:
        print(f"✗ FaceAnalysis 初始化失败: {e}")
        traceback.print_exc()
        return None


def test_face_detection(app):
    """测试人脸检测功能"""
    print("\n=== 3. 测试人脸检测功能 ===")
    try:
        # 创建一个简单的测试图像（100x100 的黑色图像）
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        
        print("正在检测人脸...")
        faces = app.get(test_image)
        
        print(f"✓ 人脸检测完成，检测到 {len(faces)} 张人脸")
        return True
    except Exception as e:
        print(f"✗ 人脸检测失败: {e}")
        traceback.print_exc()
        return False


def check_model_files():
    """检查模型文件是否存在"""
    print("\n=== 4. 检查模型文件 ===")
    
    # InsightFace 默认模型路径
    model_path = os.path.expanduser("~/.insightface/models/buffalo_l")
    
    if os.path.exists(model_path):
        print(f"✓ 模型目录存在: {model_path}")
        
        files = os.listdir(model_path)
        print(f"  模型文件列表:")
        for f in files:
            file_path = os.path.join(model_path, f)
            size = os.path.getsize(file_path) / (1024 * 1024)  # MB
            print(f"    - {f} ({size:.2f} MB)")
    else:
        print(f"✗ 模型目录不存在: {model_path}")
        print("  模型将在首次初始化时自动下载")


def test_opencv():
    """测试 OpenCV 是否正常"""
    print("\n=== 5. 测试 OpenCV ===")
    try:
        import cv2
        print(f"✓ OpenCV 版本: {cv2.__version__}")
        
        # 测试基本功能
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite("/tmp/test_opencv.jpg", img)
        print("✓ OpenCV 写入测试成功")
        return True
    except Exception as e:
        print(f"✗ OpenCV 测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("=" * 60)
    print("     InsightFace 诊断测试脚本")
    print("=" * 60)
    
    # 测试各项功能
    results = []
    
    results.append(("InsightFace 导入", test_insightface_import()))
    results.append(("OpenCV 测试", test_opencv()))
    check_model_files()
    
    app = test_face_analysis_init()
    if app:
        results.append(("人脸检测", test_face_detection(app)))
    
    # 输出测试结果汇总
    print("\n" + "=" * 60)
    print("           测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status} - {test_name}")
    
    print(f"\n  总计: {passed}/{total} 通过")
    
    if passed != total:
        print("\n  建议检查:")
        print("  1. 确保 insightface 已正确安装")
        print("  2. 检查网络连接（首次运行需要下载模型）")
        print("  3. 确保有足够的磁盘空间")
        print("  4. 尝试重新安装: pip install --upgrade insightface onnxruntime")
        sys.exit(1)
    else:
        print("\n  ✓ 所有测试通过！InsightFace 可以正常运行")
        sys.exit(0)


if __name__ == "__main__":
    main()