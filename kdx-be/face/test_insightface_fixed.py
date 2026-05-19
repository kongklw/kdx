#!/usr/bin/env python3
"""
InsightFace 诊断测试脚本（修复版本）

在导入 InsightFace 之前设置环境变量，禁用 CPU 优化。
"""

import os
import sys

# 在导入任何模块之前设置环境变量
os.environ['ORT_DISABLE_CPU_OPTIMIZATION'] = '1'
os.environ['ONNXRUNTIME_DISABLE_OPTIMIZATION'] = '1'

print("已设置环境变量禁用 CPU 优化")
print(f"ORT_DISABLE_CPU_OPTIMIZATION = {os.environ.get('ORT_DISABLE_CPU_OPTIMIZATION')}")


def main():
    print("\n" + "=" * 60)
    print("     InsightFace 测试（修复版本）")
    print("=" * 60)
    
    try:
        print("\n1. 导入 InsightFace...")
        from insightface.app import FaceAnalysis
        print("✓ InsightFace 导入成功")
        
        print("\n2. 初始化 FaceAnalysis...")
        app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        print("✓ FaceAnalysis 创建成功")
        
        print("\n3. 准备模型（可能需要下载，耐心等待）...")
        app.prepare(ctx_id=-1, det_size=(640, 640))
        print("✓ 模型准备成功")
        
        print("\n4. 测试人脸检测...")
        import numpy as np
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        faces = app.get(test_image)
        print(f"✓ 人脸检测完成，检测到 {len(faces)} 张人脸")
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过！InsightFace 可以正常运行")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()