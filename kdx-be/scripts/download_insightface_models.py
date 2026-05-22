#!/usr/bin/env python3
"""
预下载 InsightFace 模型脚本
用于在构建 Docker 镜像时预先下载模型，避免运行时懒加载延迟
"""
import os
import sys

def download_insightface_models():
    print("=== 开始预下载 InsightFace 模型 ===")
    
    # 设置环境变量禁用 CPU 优化（兼容更多 CPU 型号）
    os.environ.setdefault('ORT_DISABLE_CPU_OPTIMIZATION', '1')
    os.environ.setdefault('ONNXRUNTIME_DISABLE_OPTIMIZATION', '1')
    
    try:
        import insightface
        from insightface.app import FaceAnalysis
        
        print("正在初始化 FaceAnalysis...")
        
        # 创建 FaceAnalysis 实例，指定使用的模型
        # 默认使用 'buffalo_l' 模型，这是最常用的模型
        app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        
        # 准备模型（会自动下载）
        print("正在下载/加载模型...")
        app.prepare(ctx_id=0, det_size=(640, 640))
        
        print("=== InsightFace 模型预下载完成 ===")
        # 获取模型路径（兼容新版 insightface）
        model_path = os.path.expanduser('~/.insightface/models')
        print(f"模型路径：{model_path}")
        
    except Exception as e:
        print(f"模型下载失败：{e}")
        print("请确保网络可以访问 InsightFace 模型仓库")
        sys.exit(1)

if __name__ == '__main__':
    download_insightface_models()