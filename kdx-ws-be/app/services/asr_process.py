'''
这个文件处理语音ASR  STT speak to text
采用三明治的方式。
'''

'''
接收语音chunks （后续优化入库）
大模型返回语音 text
返回语音内容。 （后续优化入库）
'''
from assemblyai_stt import AssemblyAISTT
from .events import VoiceAgentEvent
from typing import AsyncIterator


stt = AssemblyAISTT(sample_rate=16000)

async def _stt_stream(audio_stream:AsyncIterator[bytes]) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Audio (Bytes) → Voice Events (VoiceAgentEvent)

    This function takes a stream of audio chunks and sends them to AssemblyAI for STT.

    It uses a producer-consumer pattern where:
    - Producer: A background task reads audio chunks from audio_stream and sends
      them to AssemblyAI via WebSocket. This runs concurrently with the consumer,
      allowing transcription to begin before all audio has arrived.
    - Consumer: The main coroutine receives transcription events from AssemblyAI
      and yields them downstream. Events include both partial results (stt_chunk)
      and final transcripts (stt_output).

    Args:
        audio_stream: Async iterator of PCM audio bytes (16-bit, mono, 16kHz)

    Yields:
        STT events (stt_chunk for partials, stt_output for final transcripts)
    """

    async  for audio_chunk in audio_stream:
        pass


    pass