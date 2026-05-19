#!/usr/bin/env python3
"""
InsightFace 修复脚本

解决 "Illegal instruction (core dumped)" 问题，
这通常是由于 ONNX Runtime 使用了 CPU 不支持的指令集。
"""

import subprocess
import sys


def install_compatible_onnxruntime():
    """安装兼容 CPU 的 ONNX Runtime 版本"""
    print("=== 安装兼容 CPU 的 ONNX Runtime 版本 ===")
    
    # 卸载可能有问题的版本
    print("\n1. 卸载现有版本...")
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "onnxruntime", "onnxruntime-gpu"], 
                   capture_output=True)
    
    # 安装兼容版本
    print("\n2. 安装 CPU 兼容版本的 ONNX Runtime...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "onnxruntime==1.15.1"],
                          capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ ONNX Runtime 安装成功")
        print("输出:", result.stdout)
        return True
    else:
        print("✗ ONNX Runtime 安装失败")
        print("错误:", result.stderr)
        return False


def set_environment_variables():
    """设置环境变量以禁用高级 CPU 指令"""
    print("\n=== 设置环境变量 ===")
    
    # 检查当前环境变量
    import os
    
    # 设置 ONNX Runtime 禁用 AVX2 和 AVX-512
    os.environ['ORT_DISABLE_CPU_OPTIMIZATION'] = '1'
    os.environ['ONNXRUNTIME_DISABLE_OPTIMIZATION'] = '1'
    
    print("✓ 已设置环境变量:")
    print("  - ORT_DISABLE_CPU_OPTIMIZATION=1")
    print("  - ONNXRUNTIME_DISABLE_OPTIMIZATION=1")
    
    return True


def test_fix():
    """测试修复是否有效"""
    print("\n=== 测试修复效果 ===")
    
    # 设置环境变量
    import os
    os.environ['ORT_DISABLE_CPU_OPTIMIZATION'] = '1'
    
    try:
        from insightface.app import FaceAnalysis
        print("✓ InsightFace 导入成功")
        
        print("正在初始化...")
        app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=-1, det_size=(640, 640))
        print("✓ InsightFace 初始化成功")
        
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主修复函数"""
    print("=" * 60)
    print("     InsightFace 修复脚本")
    print("=" * 60)
    print("\n问题原因:")
    print("  'Illegal instruction (core dumped)' 错误通常是由于")
    print("  ONNX Runtime 使用了 CPU 不支持的高级指令集（如 AVX2、AVX-512）")
    print("\n解决方案:")
    print("  1. 安装兼容的 ONNX Runtime 版本")
    print("  2. 设置环境变量禁用 CPU 优化")
    
    print("\n" + "=" * 60)
    
    # 步骤1: 安装兼容版本
    if not install_compatible_onnxruntime():
        print("\n✗ 安装失败，尝试仅设置环境变量...")
    
    # 步骤2: 设置环境变量并测试
    set_environment_variables()
    
    # 步骤3: 测试修复效果
    print("\n" + "=" * 60)
    if test_fix():
        print("\n✓ 修复成功！InsightFace 现在可以正常运行")
        print("\n注意: 每次运行前需要设置环境变量:")
        print("  export ORT_DISABLE_CPU_OPTIMIZATION=1")
        sys.exit(0)
    else:
        print("\n✗ 修复失败，请尝试其他解决方案")
        print("\n其他解决方案:")
        print("  1. 检查 CPU 是否支持 AVX2 指令")
        print("  2. 尝试使用 GPU 版本 (如果有 NVIDIA GPU)")
        print("  3. 更新系统和 CPU 驱动")
        sys.exit(1)


if __name__ == "__main__":
    main()