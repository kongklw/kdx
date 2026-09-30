"""
语音管线模块: ASR (流式语音识别) + TTS (流式语音合成)

从 ws/voice_agent_langchain.py 提取, 供统一入口 ws/ai_entrance.py 复用。
ASR: DashScope paraformer-realtime-v2 (流式 STT, 支持部分识别 + 句尾定稿)
TTS: DashScope qwen3-tts-vd (流式 TTS, 支持 fallback 模型)
"""
