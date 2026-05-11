<template>
  <div class="app-container">
    <div class="chat-content">
      <span style="color:#67C23A; margin:0px 0px 20px 0px; font-size: Medium;">
        Hello everyone, we are experiencing a wonderful era of AI. Try it !!!
        <br>
      </span>

      <el-card class="voice-card" shadow="never">
        <div slot="header" class="card-header">
          <span>语音助手（FastAPI /ws/voice_agent_langchain）</span>
          <span class="ws-status" :class="{ online: wsState === 'online', offline: wsState !== 'online' }">
            {{ wsStateLabel }}
          </span>
        </div>

        <el-row :gutter="12">
          <el-col :span="18">
            <el-input v-model="wsUrl" placeholder="WebSocket 地址" />
          </el-col>
          <el-col :span="6" class="btn-col">
            <el-button v-if="wsState !== 'online'" type="primary" @click="connectWs">连接</el-button>
            <el-button v-else type="danger" @click="disconnectWs">断开</el-button>
          </el-col>
        </el-row>

        <el-row :gutter="12" style="margin-top: 10px;">
          <el-col :span="12">
            <el-button :disabled="wsState !== 'online' || isRecording" type="success" @click="startRecording">
              开始说话
            </el-button>
            <el-button :disabled="!isRecording" type="warning" @click="stopRecording">停止</el-button>
          </el-col>
          <el-col :span="12" class="hint">
            输入音频要求：麦克风 -> 16kHz 单声道 PCM（前端实时重采样/编码后发送）
          </el-col>
        </el-row>

        <div class="voice-panels">
          <div class="panel">
            <div class="panel-title">识别中（stt_chunk）</div>
            <div class="panel-body">{{ sttPartial || '—' }}</div>
          </div>
          <div class="panel">
            <div class="panel-title">最终识别（stt_output）</div>
            <div class="panel-body">{{ sttFinal || '—' }}</div>
          </div>
          <div class="panel">
            <div class="panel-title">AI 输出（agent_chunk）</div>
            <div class="panel-body">{{ agentStreamingText || '—' }}</div>
          </div>
        </div>

        <el-collapse>
          <el-collapse-item title="事件日志（调试用）" name="events">
            <div class="event-log">
              <div v-for="(e, idx) in eventLog" :key="idx" class="event-line">
                <span class="event-type">{{ e.type }}</span>
                <span class="event-text">{{ e.text }}</span>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-card>

      <el-divider />

      <el-row>
        <el-col :span="20">
          <el-input v-model="newMessage" placeholder="试试AI吧" class="input-message" @keyup.enter.native="sendMessage" />
        </el-col>
        <el-col :span="4">
          <el-button type="primary" @click="sendMessage">交流</el-button>
        </el-col>
      </el-row>

      <el-card>
        <div v-for="(message, index) in messages" :key="index" class="message-item">
          <span class="message-author">{{ message.author }}</span>
          <span class="message-text">{{ message.text }}</span>
        </div>
      </el-card>
    </div>

  </div>
</template>

<script>

import {
  askAIReq
} from '@/api/aipark'
import { getToken } from '@/utils/auth'

export default {

  data() {
    return {
      thread_id: '',

      dialogVisible: true,
      messages: [
        { author: 'Alice', text: 'Hello, Bob!' },
        { author: 'Bob', text: 'Hi, Alice! How are you?' }
      ],
      newMessage: '',

      wsUrl: '',
      wsState: 'offline',
      ws: null,
      isRecording: false,
      micStream: null,
      audioContext: null,
      processorNode: null,
      sourceNode: null,
      sinkNode: null,
      inputSampleRate: 48000,
      targetSampleRate: 16000,

      ttsAudioContext: null,
      ttsNextPlayTime: 0,

      sttPartial: '',
      sttFinal: '',
      agentStreamingText: '',
      eventLog: []
    }
  },

  computed: {
    wsStateLabel() {
      if (this.wsState === 'online') return '已连接'
      if (this.wsState === 'connecting') return '连接中'
      if (this.wsState === 'error') return '连接失败'
      return '未连接'
    }
  },

  created() {
    this.wsUrl = this.getDefaultWsUrl()
  },

  methods: {
    getDefaultWsUrl() {
      const token = getToken()
      const qs = token ? `?token=${encodeURIComponent(token)}` : ''
      if (process.env.NODE_ENV === 'development') {
        return `ws://127.0.0.1:8002/ws/voice_agent_langchain${qs}`
      }
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      return `${scheme}://${window.location.host}/prod-ai/ws/voice_agent_langchain${qs}`
    },

    appendEventLog(evt) {
      const type = evt.type || 'unknown'
      let text = ''
      if (type === 'stt_chunk' || type === 'stt_output') text = evt.transcript || ''
      else if (type === 'agent_chunk') text = evt.text || ''
      else if (type === 'tool_call') text = `${evt.name} ${JSON.stringify(evt.args || {})}`
      else if (type === 'tool_result') text = `${evt.name} ${evt.result || ''}`
      else if (type === 'tts_chunk') text = '[audio]'
      else text = JSON.stringify(evt)

      this.eventLog.push({ type, text })
      if (this.eventLog.length > 200) this.eventLog.shift()
    },

    connectWs() {
      if (!this.wsUrl) return
      try {
        if (this.ws) {
          this.ws.close()
          this.ws = null
        }
        this.wsState = 'connecting'
        this.sttPartial = ''
        this.sttFinal = ''
        this.agentStreamingText = ''
        this.eventLog = []

        const ws = new WebSocket(this.wsUrl)
        ws.binaryType = 'arraybuffer'
        ws.onopen = async() => {
          this.wsState = 'online'
          this.ws = ws
          await this.ensureTtsAudioContext()
        }
        ws.onerror = () => {
          this.wsState = 'error'
        }
        ws.onclose = () => {
          this.wsState = 'offline'
          this.ws = null
          this.stopRecording()
        }
        ws.onmessage = (msg) => {
          let evt = null
          try {
            evt = JSON.parse(msg.data)
          } catch (e) {
            return
          }
          if (!evt || !evt.type) return
          this.appendEventLog(evt)

          if (evt.type === 'stt_chunk') {
            this.sttPartial = evt.transcript || ''
          } else if (evt.type === 'stt_output') {
            this.sttFinal = evt.transcript || ''
            this.sttPartial = ''
            this.agentStreamingText = ''
          } else if (evt.type === 'agent_chunk') {
            this.agentStreamingText += (evt.text || '')
          } else if (evt.type === 'agent_end') {
            this.messages.push({ author: 'AI(voice)', text: this.agentStreamingText })
            this.agentStreamingText = ''
          } else if (evt.type === 'tool_call') {
            this.messages.push({ author: 'ToolCall', text: `${evt.name} ${JSON.stringify(evt.args || {})}` })
          } else if (evt.type === 'tool_result') {
            this.messages.push({ author: 'ToolResult', text: `${evt.name}: ${evt.result || ''}` })
          } else if (evt.type === 'tts_chunk') {
            this.playTtsChunk(evt.audio)
          }

          this.$nextTick(() => {
            const chatContent = this.$el.querySelector('.chat-content .el-card__body')
            if (chatContent) chatContent.scrollTop = chatContent.scrollHeight
          })
        }
      } catch (e) {
        this.wsState = 'error'
      }
    },

    disconnectWs() {
      this.stopRecording()
      if (this.ws) {
        this.ws.close()
        this.ws = null
      }
      this.wsState = 'offline'
    },

    async ensureTtsAudioContext() {
      if (this.ttsAudioContext) {
        if (this.ttsAudioContext.state === 'suspended') {
          try { await this.ttsAudioContext.resume() } catch (e) {}
        }
        return
      }
      const Ctx = window.AudioContext || window.webkitAudioContext
      if (!Ctx) return
      this.ttsAudioContext = new Ctx()
      this.ttsNextPlayTime = this.ttsAudioContext.currentTime
      try { await this.ttsAudioContext.resume() } catch (e) {}
    },

    playTtsChunk(base64Audio) {
      if (!base64Audio || !this.ttsAudioContext) return
      const raw = this.base64ToUint8Array(base64Audio)
      if (!raw || raw.byteLength < 2) return

      const samples = new Int16Array(raw.buffer, raw.byteOffset, Math.floor(raw.byteLength / 2))
      const float32 = new Float32Array(samples.length)
      for (let i = 0; i < samples.length; i++) {
        float32[i] = Math.max(-1, Math.min(1, samples[i] / 32768))
      }

      const audioBuffer = this.ttsAudioContext.createBuffer(1, float32.length, 24000)
      audioBuffer.getChannelData(0).set(float32)

      const src = this.ttsAudioContext.createBufferSource()
      src.buffer = audioBuffer
      src.connect(this.ttsAudioContext.destination)

      const now = this.ttsAudioContext.currentTime
      const startAt = Math.max(now, this.ttsNextPlayTime)
      src.start(startAt)
      this.ttsNextPlayTime = startAt + audioBuffer.duration
    },

    base64ToUint8Array(b64) {
      try {
        const bin = window.atob(b64)
        const len = bin.length
        const bytes = new Uint8Array(len)
        for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i)
        return bytes
      } catch (e) {
        return null
      }
    },

    async startRecording() {
      if (!this.ws || this.ws.readyState !== 1) return
      if (this.isRecording) return
      await this.ensureTtsAudioContext()
      const Ctx = window.AudioContext || window.webkitAudioContext
      if (!Ctx || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return

      try {
        this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        this.audioContext = new Ctx()
        if (this.audioContext.state === 'suspended') {
          try { await this.audioContext.resume() } catch (e) {}
        }
        this.inputSampleRate = this.audioContext.sampleRate || 48000

        this.sourceNode = this.audioContext.createMediaStreamSource(this.micStream)
        this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1)
        this.sinkNode = this.audioContext.createGain()
        this.sinkNode.gain.value = 0
        this.processorNode.onaudioprocess = (e) => {
          if (!this.ws || this.ws.readyState !== 1) return
          const input = e.inputBuffer.getChannelData(0)
          const downsampled = this.downsampleBuffer(input, this.inputSampleRate, this.targetSampleRate)
          const pcm16 = this.floatTo16BitPCM(downsampled)
          this.ws.send(pcm16.buffer)
        }
        this.sourceNode.connect(this.processorNode)
        this.processorNode.connect(this.sinkNode)
        this.sinkNode.connect(this.audioContext.destination)
        this.isRecording = true
      } catch (e) {
        this.stopRecording()
      }
    },

    async stopRecording() {
      this.isRecording = false
      if (this.processorNode) {
        try { this.processorNode.disconnect() } catch (e) {}
        this.processorNode.onaudioprocess = null
        this.processorNode = null
      }
      if (this.sourceNode) {
        try { this.sourceNode.disconnect() } catch (e) {}
        this.sourceNode = null
      }
      if (this.sinkNode) {
        try { this.sinkNode.disconnect() } catch (e) {}
        this.sinkNode = null
      }
      if (this.audioContext) {
        try { await this.audioContext.close() } catch (e) {}
        this.audioContext = null
      }
      if (this.micStream) {
        try {
          this.micStream.getTracks().forEach(t => t.stop())
        } catch (e) {}
        this.micStream = null
      }
    },

    downsampleBuffer(buffer, inputRate, outputRate) {
      if (outputRate === inputRate) return buffer
      if (outputRate > inputRate) return buffer
      const ratio = inputRate / outputRate
      const newLength = Math.round(buffer.length / ratio)
      const result = new Float32Array(newLength)
      let offsetResult = 0
      let offsetBuffer = 0
      while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio)
        let accum = 0
        let count = 0
        for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
          accum += buffer[i]
          count++
        }
        result[offsetResult] = count ? accum / count : 0
        offsetResult++
        offsetBuffer = nextOffsetBuffer
      }
      return result
    },

    floatTo16BitPCM(float32Array) {
      const int16 = new Int16Array(float32Array.length)
      for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]))
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      return int16
    },

    handleClose() {
      // 可以在这里处理对话框关闭前的逻辑
    },

    sendMessage() {
      if (this.newMessage.trim()) {
        this.messages.push({ author: 'You', text: this.newMessage })

        // 发送后端请求，将结果加入到messages里面.
        const data = { content: this.newMessage, thread_id: this.thread_id }
        askAIReq(data).then(res => {
          this.newMessage = ''
          if (res.code === 200) {
            const data = res.data
            console.log('请求ai 返回的数据为', data)
            this.messages.push({ author: 'AI', text: data.msg })
            this.thread_id = data.thread_id
          }
        })

        // 可以在这里添加滚动到底部的逻辑
        this.$nextTick(() => {
          const chatContent = this.$el.querySelector('.chat-content .el-card__body')
          chatContent.scrollTop = chatContent.scrollHeight
        })
      }
    }

  }

}
</script>

<style>
.centered-form-container {
  display: flex;
  justify-content: center;
  align-items: center;
  /* height: 100vh;  */
  /* 使容器高度占满整个视口高度 */

}

.custom-form {
  min-width: 80%;
  /* 设置表单宽度 */
  padding: 20px;
  border: 1px solid #dcdcdc;
  border-radius: 4px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  background-color: #fff;
}

.chat-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  justify-content: center;
  /* align-items: center; */
  min-width: 60%;
}

.voice-card {
  margin-bottom: 10px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ws-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: #f0f2f5;
  color: #909399;
}

.ws-status.online {
  background: #e1f3d8;
  color: #67c23a;
}

.ws-status.offline {
  background: #fde2e2;
  color: #f56c6c;
}

.btn-col {
  display: flex;
  justify-content: flex-end;
}

.hint {
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.voice-panels {
  display: grid;
  grid-template-columns: 1fr;
  grid-row-gap: 10px;
  margin-top: 12px;
}

.panel {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px;
}

.panel-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.panel-body {
  min-height: 22px;
  white-space: pre-wrap;
  word-break: break-word;
}

.event-log {
  max-height: 220px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
}

.event-line {
  display: grid;
  grid-template-columns: 120px 1fr;
  grid-column-gap: 8px;
  padding: 4px 0;
  border-bottom: 1px dashed #ebeef5;
}

.event-type {
  color: #606266;
}

.event-text {
  color: #303133;
  word-break: break-word;
}

.message-item {
  display: flex;
  justify-content: flex-start;
  margin-bottom: 10px;
}

.message-author {
  font-weight: bold;
  margin-right: 5px;
}

.message-text {
  background-color: #f5f7fa;
  padding: 5px 10px;
  border-radius: 4px;
}

.input-message {
  flex: 1;
  margin-bottom: 10px;
}
</style>
