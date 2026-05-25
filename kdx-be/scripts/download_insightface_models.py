#!/usr/bin/env python3
"""
预下载 InsightFace 模型脚本
用于在构建 Docker 镜像时预先下载模型，避免运行时懒加载延迟
支持多个备用下载地址，提高下载成功率
"""
import os
import sys
import urllib.request
import zipfile
import shutil

# 备用下载地址列表
MODEL_URLS = [
    # "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
    # "https://gitee.com/mirrors/insightface/attach_files/1163543/download/buffalo_l.zip",
    "https://codeload.github.com/deepinsight/insightface/zip/refs/tags/v0.7",
]

def download_file(url, save_path):
    """从指定URL下载文件，支持超时重试"""
    try:
        print(f"尝试从 {url} 下载...")
        response = urllib.request.urlopen(url, timeout=120)
        with open(save_path, 'wb') as f:
            f.write(response.read())
        return True
    except Exception as e:
        print(f"从 {url} 下载失败: {e}")
        return False

def unzip_file(zip_path, extract_path):
    """解压 ZIP 文件"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        return True
    except Exception as e:
        print(f"解压失败: {e}")
        return False

def download_insightface_models():
    print("=== 开始预下载 InsightFace 模型 ===")
    
    # 设置环境变量禁用 CPU 优化（兼容更多 CPU 型号）
    os.environ.setdefault('ORT_DISABLE_CPU_OPTIMIZATION', '1')
    os.environ.setdefault('ONNXRUNTIME_DISABLE_OPTIMIZATION', '1')
    
    # 创建模型目录
    model_dir = os.path.expanduser('~/.insightface/models')
    os.makedirs(model_dir, exist_ok=True)
    
    try:
        import insightface
        from insightface.app import FaceAnalysis
        
        print("正在初始化 FaceAnalysis...")
        
        # 尝试使用内置方法下载
        try:
            app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            print("正在下载/加载模型...")
            app.prepare(ctx_id=0, det_size=(640, 640))
            print("=== InsightFace 模型预下载完成 ===")
            print(f"模型路径：{model_dir}")
            return
        except Exception as e:
            print(f"内置下载失败，尝试备用地址: {e}")
        
        # 尝试备用下载地址
        zip_path = os.path.join(model_dir, 'buffalo_l.zip')
        
        for url in MODEL_URLS:
            if download_file(url, zip_path):
                print("下载成功，开始解压...")
                if unzip_file(zip_path, model_dir):
                    print("解压成功")
                    # 清理压缩包
                    os.remove(zip_path)
                    print("=== InsightFace 模型预下载完成 ===")
                    print(f"模型路径：{model_dir}")
                    return
                else:
                    print("解压失败，尝试下一个地址")
        
        print("所有备用地址都下载失败")
        # 检查是否已存在模型（可能是之前下载的）
        buffalo_l_dir = os.path.join(model_dir, 'buffalo_l')
        if os.path.exists(buffalo_l_dir) and len(os.listdir(buffalo_l_dir)) > 0:
            print(f"检测到已有模型目录: {buffalo_l_dir}")
            print("=== 使用已存在的模型 ===")
            return
        
        raise Exception("无法下载模型且无已存在的模型")
        
    except Exception as e:
        print(f"模型下载失败：{e}")
        # 检查是否设置了跳过下载的环境变量
        if os.environ.get('SKIP_INSIGHTFACE_DOWNLOAD') == '1':
            print("已设置 SKIP_INSIGHTFACE_DOWNLOAD=1，跳过模型下载")
            print("注意：运行时可能会自动下载模型")
            return
        sys.exit(1)

if __name__ == '__main__':
    download_insightface_models()