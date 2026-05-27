<template>
  <div class="mobile-ai">
    <van-nav-bar title="AI Park" fixed placeholder />

    <van-grid :column-num="2" :gutter="10" clickable class="ai-grid">
      <van-grid-item icon="chat-o" text="Langchain Chat" to="/mobile/functions/langchain" />
      <van-grid-item icon="photo-o" text="Image Generation" />
      <van-grid-item icon="music-o" text="Voice Assistant" @click="openVoiceAssistant" />
      <van-grid-item icon="star-o" text="Voice Assistant (LC)" @click="openVoiceAssistantLangchain" />
      <van-grid-item icon="video-o" text="Video Creator" />
      <van-grid-item icon="user-o" text="Face Recognition" @click="openFaceRecognition" />
    </van-grid>

    <van-empty description="更多 AI 功能即将上线" />

    <van-popup
      v-model="showVoiceAssistant"
      position="bottom"
      round
      closeable
      :style="{ height: '82vh' }"
      class="voice-popup"
      @close="handleClose"
    >
      <div class="va">
        <div class="va-header">
          <div class="va-title">Voice Assistant</div>
          <div class="va-header-right">
            <div :class="['va-status', isWsOpen ? 'ok' : 'bad']">
              {{ isWsOpen ? 'CONNECTED' : wsStatusText }}
            </div>
            <van-icon name="setting-o" class="va-setting" @click="showWsSettings = true" />
          </div>
        </div>

        <div class="va-body">
          <div class="va-log-body">
            <div v-for="(line, idx) in logs" :key="idx" class="va-log-line">{{ line }}</div>
          </div>
        </div>

        <div class="va-composer">
          <van-icon
            :name="inputMode === 'text' ? 'audio' : 'edit'"
            class="va-mode"
            @click="toggleInputMode"
          />

          <div v-if="inputMode === 'text'" class="va-text-wrap">
            <van-field
              v-model="textMessage"
              class="va-text"
              type="textarea"
              autosize
              rows="1"
              placeholder="输入消息"
            />
          </div>

          <div
            v-else
            class="va-ptt"
            :class="{ pressed: isPressing }"
            @touchstart.prevent="onPressStart"
            @touchend.prevent="onPressEnd"
            @touchcancel.prevent="onPressCancel"
            @mousedown.prevent="onPressStart"
            @mouseup.prevent="onPressEnd"
            @mouseleave="onPressCancel"
          >
            {{ isRecording ? '松开 结束' : '按住 说话' }}
          </div>

          <van-button
            v-if="inputMode === 'text'"
            size="small"
            type="primary"
            class="va-send"
            :disabled="!canSendText"
            @click="sendText"
          >
            发送
          </van-button>
        </div>
      </div>
    </van-popup>

    <van-popup
      v-model="showWsSettings"
      position="bottom"
      round
      closeable
      :style="{ height: '58vh' }"
      class="va-settings"
      @close="showWsSettings = false"
    >
      <div class="va-settings-title">连接设置</div>
      <van-field v-model="wsUrl" label="WS" placeholder="ws://127.0.0.1:8001/ws/voice-agent" />
      <div class="va-settings-actions">
        <van-button size="small" @click="setWsUrlToHost">使用当前域名</van-button>
        <van-button size="small" @click="setWsUrlToLocal">使用本地 8001</van-button>
      </div>
      <van-field v-model="token" label="Token" placeholder="可留空（如果后端允许匿名）" />
      <div class="va-settings-actions">
        <van-button size="small" type="primary" :disabled="isWsOpen" @click="connectWs">连接</van-button>
        <van-button size="small" type="danger" :disabled="!isWsOpen" @click="disconnectWs">断开</van-button>
        <van-button size="small" :disabled="!isWsOpen" @click="sendPing">Ping</van-button>
        <van-button size="small" @click="clearLogs">清空日志</van-button>
      </div>
    </van-popup>

    <van-popup
      v-model="showVoiceAssistantLangchain"
      position="bottom"
      round
      closeable
      :style="{ height: '82vh' }"
      class="voice-popup"
      @close="handleCloseLangchain"
    >
      <div class="va">
        <div class="va-header">
          <div class="va-title">Voice Assistant (LangChain)</div>
          <div class="va-header-right">
            <div :class="['va-status', isWsOpenLangchain ? 'ok' : 'bad']">
              {{ isWsOpenLangchain ? 'CONNECTED' : wsStatusTextLangchain }}
            </div>
            <van-icon name="setting-o" class="va-setting" @click="showWsSettingsLangchain = true" />
          </div>
        </div>

        <div class="va-body">
          <div class="va-lc-panels">
            <div class="va-lc-panel">
              <div class="va-lc-title">识别中</div>
              <div class="va-lc-text">{{ sttPartialLangchain || '—' }}</div>
            </div>
            <div class="va-lc-panel">
              <div class="va-lc-title">最终识别</div>
              <div class="va-lc-text">{{ sttFinalLangchain || '—' }}</div>
            </div>
            <div class="va-lc-panel">
              <div class="va-lc-title">AI 输出</div>
              <div class="va-lc-text">{{ agentTextLangchain || '—' }}</div>
            </div>
          </div>

          <div class="va-log-body">
            <div v-for="(line, idx) in logsLangchain" :key="idx" class="va-log-line">{{ line }}</div>
          </div>
        </div>

        <div class="va-composer">
          <div
            class="va-ptt"
            :class="{ pressed: isPressingLangchain }"
            @touchstart.prevent="onPressStartLangchain"
            @touchend.prevent="onPressEndLangchain"
            @touchcancel.prevent="onPressCancelLangchain"
            @mousedown.prevent="onPressStartLangchain"
            @mouseup.prevent="onPressEndLangchain"
            @mouseleave="onPressCancelLangchain"
          >
            {{ isRecordingLangchain ? '松开 结束' : '按住 说话' }}
          </div>
        </div>
      </div>
    </van-popup>

    <van-popup
      v-model="showWsSettingsLangchain"
      position="bottom"
      round
      closeable
      :style="{ height: '58vh' }"
      class="va-settings"
      @close="showWsSettingsLangchain = false"
    >
      <div class="va-settings-title">连接设置 (LangChain)</div>
      <van-field v-model="wsUrlLangchain" label="WS" placeholder="ws://127.0.0.1:8001/ws/voice_agent_langchain" />
      <div class="va-settings-actions">
        <van-button size="small" @click="setWsUrlToHostLangchain">使用当前域名</van-button>
        <van-button size="small" @click="setWsUrlToLocalLangchain">使用本地 8001</van-button>
      </div>
      <van-field v-model="tokenLangchain" label="Token" placeholder="可留空（如果后端允许匿名）" />
      <div class="va-settings-actions">
        <van-button size="small" type="primary" :disabled="isWsOpenLangchain" @click="connectWsLangchain">连接</van-button>
        <van-button size="small" type="danger" :disabled="!isWsOpenLangchain" @click="disconnectWsLangchain">断开</van-button>
        <van-button size="small" @click="clearLogsLangchain">清空日志</van-button>
      </div>
    </van-popup>

    <!-- 人脸识别弹窗 -->
    <van-popup
      v-model="showFaceRecognition"
      position="bottom"
      round
      closeable
      :style="{ height: '85vh' }"
      class="face-popup"
      @close="handleCloseFaceRecognition"
    >
      <div class="face-container">
        <!-- 头部 -->
        <div class="face-header">
          <div class="face-title">人脸识别</div>
        </div>

        <!-- 主内容区 -->
        <div class="face-body">
          <!-- 未上传人脸时显示上传区域 -->
          <div v-if="!hasFace" class="upload-section">
            <div class="upload-icon">
              <van-icon name="user-o" size="64" />
            </div>
            <div class="upload-text">请先上传您的人脸照片</div>
            <div class="upload-hint">上传后即可使用人脸识别功能</div>
            <van-button
              type="primary"
              size="large"
              class="upload-btn"
              @click="selectImage"
            >
              选择照片
            </van-button>
            <input
              type="file"
              accept="image/*"
              capture="environment"
              class="file-input"
              @change="handleImageSelect"
            >
          </div>

          <!-- 已上传人脸时显示识别区域 -->
          <div v-else class="recognize-section">
            <!-- 识别进行中显示摄像头画面 -->
            <div v-if="isRecognizing" class="camera-section">
              <div class="camera-label">正在识别中...</div>
              <div class="camera-container">
                <video ref="videoRef" class="camera-video" autoplay playsinline />
                <div class="face-frame" />
              </div>
            </div>

            <!-- 未识别时显示已上传人脸预览 -->
            <div v-else class="face-preview">
              <div class="preview-label">已上传的人脸</div>
              <div class="preview-placeholder">
                <van-icon name="user-o" size="80" />
              </div>
            </div>

            <!-- 重新上传按钮 -->
            <van-button
              size="small"
              class="reupload-btn"
              @click="selectImage"
            >
              重新上传照片
            </van-button>
            <input
              type="file"
              accept="image/*"
              capture="environment"
              class="file-input"
              @change="handleImageSelect"
            >
          </div>

          <!-- 识别结果展示 -->
          <div v-if="recognitionResult" class="result-section">
            <div :class="['result-icon', recognitionResult.matched ? 'success' : 'fail']">
              <van-icon :name="recognitionResult.matched ? 'success' : 'cross'" size="48" />
            </div>
            <div :class="['result-text', recognitionResult.matched ? 'success' : 'fail']">
              {{ recognitionResult.matched ? '人脸识别成功' : '人脸识别失败' }}
            </div>
            <div v-if="recognitionResult.confidence" class="result-confidence">
              相似度: {{ (recognitionResult.confidence * 100).toFixed(2) }}%
            </div>
          </div>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<script>
import { Toast } from 'vant'
import { getToken } from '@/utils/auth'

export default {
  name: 'MobileAI',
  data() {
    return {
      showVoiceAssistant: false,
      showWsSettings: false,
      inputMode: 'text',
      isPressing: false,
      pressSessionId: 0,
      wsUrl: '',
      token: '',
      ws: null,
      wsReadyState: 3,
      wsStatus: 'DISCONNECTED',
      logs: [],
      textMessage: '',
      recorder: null,
      recorderStream: null,
      isRecording: false,
      recordMeta: '',
      recordMode: null,
      endSent: false,
      audioCtx: null,
      audioSource: null,
      audioProcessor: null,
      audioGain: null,
      sentAudioBytes: 0,

      showVoiceAssistantLangchain: false,
      showWsSettingsLangchain: false,
      isPressingLangchain: false,
      pressSessionIdLangchain: 0,
      wsUrlLangchain: '',
      tokenLangchain: '',
      wsLangchain: null,
      wsReadyStateLangchain: 3,
      wsStatusLangchain: 'DISCONNECTED',
      logsLangchain: [],
      micStreamLangchain: null,
      isRecordingLangchain: false,
      audioContextLangchain: null,
      processorNodeLangchain: null,
      sourceNodeLangchain: null,
      sinkNodeLangchain: null,
      inputSampleRateLangchain: 48000,
      targetSampleRateLangchain: 16000,
      sentAudioBytesLangchain: 0,
      sttPartialLangchain: '',
      sttFinalLangchain: '',
      agentTextLangchain: '',
      ttsAudioCtxLangchain: null,
      ttsNextPlayTimeLangchain: 0,

      // 人脸识别相关
      showFaceRecognition: false,
      hasFace: false,
      faceStatus: 'idle', // idle, uploading, uploaded, recognizing, matched, failed
      isRecognizing: false,
      recognitionResult: null
    }
  },
  computed: {
    isWsOpen() {
      return this.wsReadyState === 1
    },
    wsStatusText() {
      return this.wsStatus
    },
    canSendText() {
      return this.isWsOpen && (this.textMessage || '').trim().length > 0
    },
    isWsOpenLangchain() {
      return this.wsReadyStateLangchain === 1
    },
    wsStatusTextLangchain() {
      return this.wsStatusLangchain
    }
    // 人脸识别状态
  },
  watch: {
    showVoiceAssistant(val) {
      if (val) {
        if (!this.wsUrl) {
          this.wsUrl = this.getDefaultWsUrl()
        }
        if (!this.token) {
          this.token = getToken() || ''
        }
        this.$nextTick(() => {
          this.connectWs()
        })
        return
      }
      this.handleClose()
    },
    showVoiceAssistantLangchain(val) {
      if (val) {
        if (!this.wsUrlLangchain) {
          this.wsUrlLangchain = this.getDefaultWsUrlLangchain()
        }
        if (!this.tokenLangchain) {
          this.tokenLangchain = getToken() || ''
        }
        this.$nextTick(() => {
          this.connectWsLangchain()
        })
        return
      }
      this.handleCloseLangchain()
    }
  },
  methods: {
    openVoiceAssistant() {
      this.showVoiceAssistant = true
    },
    openVoiceAssistantLangchain() {
      this.showVoiceAssistantLangchain = true
    },
    handleClose() {
      this.stopRecording()
      this.disconnectWs()
      this.showWsSettings = false
      this.inputMode = 'text'
      this.isPressing = false
    },
    getDefaultWsUrl() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      return `${scheme}://127.0.0.1:8001/ws/voice-agent`
    },
    setWsUrlToHost() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.wsUrl = `${scheme}://${window.location.host}/prod-ai/ws/voice-agent`
    },
    setWsUrlToLocal() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.wsUrl = `${scheme}://127.0.0.1:8001/ws/voice-agent`
    },
    buildWsUrl() {
      const base = (this.wsUrl || '').trim()
      if (!base) return ''
      if (!this.token) return base
      try {
        const u = new URL(base)
        if (!u.searchParams.get('token')) {
          u.searchParams.set('token', this.token.trim())
        }
        return u.toString()
      } catch (e) {
        if (base.indexOf('?') === -1) return `${base}?token=${encodeURIComponent(this.token.trim())}`
        return `${base}&token=${encodeURIComponent(this.token.trim())}`
      }
    },
    appendLog(direction, payload) {
      const now = new Date()
      const pad = (n) => String(n).padStart(2, '0')
      const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
      const text = typeof payload === 'string' ? payload : JSON.stringify(payload)
      this.logs.push(`[${time}] ${direction} ${text}`)
      if (this.logs.length > 300) {
        this.logs.splice(0, this.logs.length - 300)
      }
    },
    clearLogs() {
      this.logs = []
    },
    connectWs() {
      const url = this.buildWsUrl()
      if (!url) {
        Toast.fail('请填写 WebSocket URL')
        return
      }
      if (this.wsReadyState === 1 || this.wsReadyState === 0) {
        return
      }

      this.wsStatus = 'CONNECTING'
      this.appendLog('->', { type: 'connect', url })
      let socket = null
      try {
        socket = new WebSocket(url)
      } catch (e) {
        this.wsStatus = 'DISCONNECTED'
        this.appendLog('<-', { type: 'error', message: String(e) })
        Toast.fail(String(e))
        return
      }

      socket.binaryType = 'arraybuffer'
      this.wsReadyState = socket.readyState
      socket.onopen = () => {
        this.wsStatus = 'CONNECTED'
        this.wsReadyState = 1
        this.appendLog('<-', { type: 'open' })
      }
      socket.onmessage = (evt) => {
        const data = evt.data
        if (typeof data === 'string') {
          try {
            this.appendLog('<-', JSON.parse(data))
          } catch (e) {
            this.appendLog('<-', data)
          }
          return
        }
        const size = data && data.byteLength ? data.byteLength : 0
        this.appendLog('<-', { type: 'binary', bytes: size })
      }
      socket.onerror = () => {
        this.appendLog('<-', { type: 'error', message: 'ws error' })
      }
      socket.onclose = (evt) => {
        this.appendLog('<-', { type: 'close', code: evt.code, reason: evt.reason })
        this.wsStatus = 'DISCONNECTED'
        this.wsReadyState = 3
        this.ws = null
        this.stopRecording()
      }

      this.ws = socket
    },
    disconnectWs() {
      if (!this.ws) return
      try {
        this.appendLog('->', { type: 'disconnect' })
        this.wsReadyState = 2
        this.ws.close(1000, 'client close')
      } catch (e) {
        this.appendLog('<-', { type: 'error', message: String(e) })
        this.ws = null
        this.wsReadyState = 3
        this.wsStatus = 'DISCONNECTED'
      }
    },
    sendJson(payload) {
      if (!this.isWsOpen) {
        Toast.fail('WebSocket 未连接')
        this.appendLog('<-', { type: 'error', message: 'WebSocket 未连接' })
        return
      }
      this.appendLog('->', payload)
      this.ws.send(JSON.stringify(payload))
    },
    sendPing() {
      this.sendJson({ type: 'ping' })
    },
    sendText() {
      const text = (this.textMessage || '').trim()
      if (!text) return
      this.sendJson({ type: 'text', text })
      this.textMessage = ''
    },
    toggleInputMode() {
      this.inputMode = this.inputMode === 'text' ? 'voice' : 'text'
    },
    onPressStart() {
      if (this.inputMode !== 'voice') return
      if (!this.isWsOpen) {
        Toast.fail('WebSocket 未连接')
        this.appendLog('<-', { type: 'error', message: 'WebSocket 未连接' })
        return
      }
      if (this.isPressing) return
      this.pressSessionId += 1
      const sessionId = this.pressSessionId
      this.isPressing = true
      this.startRecording(sessionId)
    },
    onPressEnd() {
      if (!this.isPressing) return
      this.isPressing = false
      this.pressSessionId += 1
      this.stopRecording()
    },
    onPressCancel() {
      if (!this.isPressing) return
      this.isPressing = false
      this.pressSessionId += 1
      this.stopRecording()
    },
    async startRecording(sessionId) {
      if (!this.isWsOpen) {
        Toast.fail('WebSocket 未连接')
        return
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        Toast.fail('当前浏览器不支持录音')
        return
      }

      try {
        this.recorderStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (e) {
        Toast.fail('麦克风权限获取失败')
        this.appendLog('<-', { type: 'error', message: String(e) })
        return
      }

      if (!this.isPressing || sessionId !== this.pressSessionId) {
        try {
          this.recorderStream.getTracks().forEach((t) => t.stop())
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
        this.recorderStream = null
        return
      }

      this.isRecording = true
      this.endSent = false
      this.sentAudioBytes = 0
      this.recordMode = null

      if (typeof MediaRecorder !== 'undefined') {
        let recorder = null
        try {
          recorder = new MediaRecorder(this.recorderStream)
        } catch (e) {
          recorder = null
        }

        if (recorder) {
          this.recorder = recorder
          this.recordMode = 'media_recorder'
          this.recordMeta = `mimeType=${recorder.mimeType || 'unknown'}`
          this.sendJson({ type: 'start', mimeType: recorder.mimeType || '' })

          recorder.ondataavailable = (ev) => {
            if (!this.isWsOpen || !this.isRecording || !this.isPressing) return
            if (!ev.data || ev.data.size === 0) return
            this.sentAudioBytes += ev.data.size
            this.ws.send(ev.data)
          }

          recorder.onstop = () => {
            if (this.isWsOpen && !this.endSent) {
              this.endSent = true
              this.sendJson({ type: 'end', audio_bytes: this.sentAudioBytes })
            }
            this.recordMeta = ''
          }

          recorder.start(300)
          this.appendLog('->', { type: 'record_start', mode: 'media_recorder', mimeType: recorder.mimeType || '' })
          return
        }
      }

      const AudioContextClass = window.AudioContext || window.webkitAudioContext
      if (!AudioContextClass) {
        this.stopRecording()
        Toast.fail('当前环境不支持录音')
        this.appendLog('<-', { type: 'error', message: 'AudioContext not supported' })
        return
      }

      try {
        this.audioCtx = new AudioContextClass()
        this.audioSource = this.audioCtx.createMediaStreamSource(this.recorderStream)
        this.audioProcessor = this.audioCtx.createScriptProcessor(4096, 1, 1)
        this.audioGain = this.audioCtx.createGain()
        this.audioGain.gain.value = 0

        this.audioProcessor.onaudioprocess = (e) => {
          if (!this.isWsOpen || !this.isRecording || !this.isPressing) return
          const input = e.inputBuffer.getChannelData(0)
          const buffer = new ArrayBuffer(input.length * 2)
          const view = new DataView(buffer)
          for (let i = 0; i < input.length; i++) {
            let s = input[i]
            if (s > 1) s = 1
            if (s < -1) s = -1
            view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
          }
          this.sentAudioBytes += buffer.byteLength
          try {
            this.ws.send(buffer)
          } catch (err) {
            this.appendLog('<-', { type: 'error', message: String(err) })
          }
        }

        this.audioSource.connect(this.audioProcessor)
        this.audioProcessor.connect(this.audioGain)
        this.audioGain.connect(this.audioCtx.destination)
      } catch (e) {
        this.stopRecording()
        Toast.fail('录音初始化失败')
        this.appendLog('<-', { type: 'error', message: String(e) })
        return
      }

      this.recordMeta = 'pcm_s16le'
      this.recordMode = 'webaudio'
      this.sendJson({ type: 'start', codec: 'pcm_s16le' })
      this.appendLog('->', { type: 'record_start', mode: 'webaudio', codec: 'pcm_s16le' })
    },
    stopAudioGraph() {
      if (this.audioProcessor) {
        try {
          this.audioProcessor.disconnect()
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      if (this.audioSource) {
        try {
          this.audioSource.disconnect()
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      if (this.audioGain) {
        try {
          this.audioGain.disconnect()
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      if (this.audioCtx) {
        try {
          this.audioCtx.close()
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      this.audioProcessor = null
      this.audioSource = null
      this.audioGain = null
      this.audioCtx = null
    },
    stopRecording() {
      if (!this.isRecording && !this.recorder && !this.audioCtx && !this.recorderStream) return
      this.isRecording = false
      if (this.recorder) {
        try {
          this.recorder.stop()
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      this.stopAudioGraph()
      if (this.recorderStream) {
        try {
          this.recorderStream.getTracks().forEach((t) => t.stop())
        } catch (e) {
          this.appendLog('<-', { type: 'error', message: String(e) })
        }
      }
      this.recorder = null
      this.recorderStream = null
      this.isRecording = false
      this.recordMeta = ''
      if (this.isWsOpen && this.recordMode === 'webaudio' && !this.endSent) {
        this.endSent = true
        this.sendJson({ type: 'end', audio_bytes: this.sentAudioBytes })
      }
      this.recordMode = null
    },
    handleCloseLangchain() {
      this.stopRecordingLangchain()
      this.disconnectWsLangchain()
      this.showWsSettingsLangchain = false
      this.isPressingLangchain = false
      this.sttPartialLangchain = ''
      this.sttFinalLangchain = ''
      this.agentTextLangchain = ''
      this.logsLangchain = []
    },
    getDefaultWsUrlLangchain() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      return `${scheme}://127.0.0.1:8001/ws/voice_agent_langchain`
    },
    setWsUrlToHostLangchain() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.wsUrlLangchain = `${scheme}://${window.location.host}/prod-ai/ws/voice_agent_langchain`
    },
    setWsUrlToLocalLangchain() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      this.wsUrlLangchain = `${scheme}://127.0.0.1:8001/ws/voice_agent_langchain`
    },
    buildWsUrlLangchain() {
      const base = (this.wsUrlLangchain || '').trim()
      if (!base) return ''
      if (!this.tokenLangchain) return base
      try {
        const u = new URL(base)
        if (!u.searchParams.get('token')) {
          u.searchParams.set('token', this.tokenLangchain.trim())
        }
        return u.toString()
      } catch (e) {
        if (base.indexOf('?') === -1) return `${base}?token=${encodeURIComponent(this.tokenLangchain.trim())}`
        return `${base}&token=${encodeURIComponent(this.tokenLangchain.trim())}`
      }
    },
    appendLogLangchain(direction, payload) {
      const now = new Date()
      const pad = (n) => String(n).padStart(2, '0')
      const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
      const text = typeof payload === 'string' ? payload : JSON.stringify(payload)
      this.logsLangchain.push(`[${time}] ${direction} ${text}`)
      if (this.logsLangchain.length > 300) {
        this.logsLangchain.splice(0, this.logsLangchain.length - 300)
      }
    },
    clearLogsLangchain() {
      this.logsLangchain = []
    },
    connectWsLangchain() {
      const url = this.buildWsUrlLangchain()
      if (!url) {
        Toast.fail('请填写 WebSocket URL')
        return
      }
      if (this.wsReadyStateLangchain === 1 || this.wsReadyStateLangchain === 0) {
        return
      }

      this.wsStatusLangchain = 'CONNECTING'
      this.appendLogLangchain('->', { type: 'connect', url })
      let socket = null
      try {
        socket = new WebSocket(url)
      } catch (e) {
        this.wsStatusLangchain = 'DISCONNECTED'
        this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        Toast.fail(String(e))
        return
      }

      socket.binaryType = 'arraybuffer'
      this.wsReadyStateLangchain = socket.readyState
      socket.onopen = () => {
        this.wsStatusLangchain = 'CONNECTED'
        this.wsReadyStateLangchain = 1
        this.appendLogLangchain('<-', { type: 'open' })
      }
      socket.onmessage = (evt) => {
        const data = evt.data
        if (typeof data === 'string') {
          try {
            const payload = JSON.parse(data)
            this.appendLogLangchain('<-', payload)
            this.handleAgentEventLangchain(payload)
          } catch (e) {
            this.appendLogLangchain('<-', data)
          }
          return
        }
        const size = data && data.byteLength ? data.byteLength : 0
        this.appendLogLangchain('<-', { type: 'binary', bytes: size })
      }
      socket.onerror = () => {
        this.appendLogLangchain('<-', { type: 'error', message: 'ws error' })
      }
      socket.onclose = (evt) => {
        this.appendLogLangchain('<-', { type: 'close', code: evt.code, reason: evt.reason })
        this.wsStatusLangchain = 'DISCONNECTED'
        this.wsReadyStateLangchain = 3
        this.wsLangchain = null
        this.stopRecordingLangchain()
      }

      this.wsLangchain = socket
    },
    disconnectWsLangchain() {
      if (!this.wsLangchain) return
      try {
        this.appendLogLangchain('->', { type: 'disconnect' })
        this.wsReadyStateLangchain = 2
        this.wsLangchain.close(1000, 'client close')
      } catch (e) {
        this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        this.wsLangchain = null
        this.wsReadyStateLangchain = 3
        this.wsStatusLangchain = 'DISCONNECTED'
      }
    },
    onPressStartLangchain() {
      if (!this.isWsOpenLangchain) {
        Toast.fail('WebSocket 未连接')
        this.appendLogLangchain('<-', { type: 'error', message: 'WebSocket 未连接' })
        return
      }
      if (this.isPressingLangchain) return
      this.pressSessionIdLangchain += 1
      const sessionId = this.pressSessionIdLangchain
      this.isPressingLangchain = true
      this.startRecordingLangchain(sessionId)
    },
    onPressEndLangchain() {
      if (!this.isPressingLangchain) return
      this.isPressingLangchain = false
      this.pressSessionIdLangchain += 1
      this.stopRecordingLangchain()
    },
    onPressCancelLangchain() {
      if (!this.isPressingLangchain) return
      this.isPressingLangchain = false
      this.pressSessionIdLangchain += 1
      this.stopRecordingLangchain()
    },
    downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
      if (outputSampleRate >= inputSampleRate) return buffer
      const sampleRateRatio = inputSampleRate / outputSampleRate
      const newLength = Math.round(buffer.length / sampleRateRatio)
      const result = new Float32Array(newLength)
      let offsetResult = 0
      let offsetBuffer = 0
      while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio)
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
      const output = new Int16Array(float32Array.length)
      for (let i = 0; i < float32Array.length; i++) {
        let s = float32Array[i]
        if (s > 1) s = 1
        if (s < -1) s = -1
        output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      return output
    },
    async startRecordingLangchain(sessionId) {
      if (!this.isWsOpenLangchain) {
        Toast.fail('WebSocket 未连接')
        return
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        Toast.fail('当前浏览器不支持录音')
        return
      }

      try {
        this.micStreamLangchain = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (e) {
        Toast.fail('麦克风权限获取失败')
        this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        return
      }

      if (!this.isPressingLangchain || sessionId !== this.pressSessionIdLangchain) {
        try {
          this.micStreamLangchain.getTracks().forEach((t) => t.stop())
        } catch (e) {
          this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        }
        this.micStreamLangchain = null
        return
      }

      const AudioContextClass = window.AudioContext || window.webkitAudioContext
      if (!AudioContextClass) {
        this.stopRecordingLangchain()
        Toast.fail('当前环境不支持录音')
        this.appendLogLangchain('<-', { type: 'error', message: 'AudioContext not supported' })
        return
      }

      try {
        this.audioContextLangchain = new AudioContextClass()
        this.inputSampleRateLangchain = this.audioContextLangchain.sampleRate || 48000
        this.sourceNodeLangchain = this.audioContextLangchain.createMediaStreamSource(this.micStreamLangchain)
        this.processorNodeLangchain = this.audioContextLangchain.createScriptProcessor(4096, 1, 1)
        this.sinkNodeLangchain = this.audioContextLangchain.createGain()
        this.sinkNodeLangchain.gain.value = 0
        this.sentAudioBytesLangchain = 0

        this.processorNodeLangchain.onaudioprocess = (e) => {
          if (!this.wsLangchain || this.wsLangchain.readyState !== 1) return
          if (!this.isRecordingLangchain || !this.isPressingLangchain) return
          const input = e.inputBuffer.getChannelData(0)
          const downsampled = this.downsampleBuffer(input, this.inputSampleRateLangchain, this.targetSampleRateLangchain)
          const pcm16 = this.floatTo16BitPCM(downsampled)
          this.sentAudioBytesLangchain += pcm16.byteLength
          try {
            this.wsLangchain.send(pcm16.buffer)
          } catch (err) {
            this.appendLogLangchain('<-', { type: 'error', message: String(err) })
          }
        }
        this.sourceNodeLangchain.connect(this.processorNodeLangchain)
        this.processorNodeLangchain.connect(this.sinkNodeLangchain)
        this.sinkNodeLangchain.connect(this.audioContextLangchain.destination)

        this.isRecordingLangchain = true
        this.sttPartialLangchain = ''
        this.sttFinalLangchain = ''
        this.agentTextLangchain = ''
        this.appendLogLangchain('->', { type: 'record_start', codec: 'pcm_s16le', sample_rate: this.targetSampleRateLangchain })
      } catch (e) {
        this.stopRecordingLangchain()
        Toast.fail('录音初始化失败')
        this.appendLogLangchain('<-', { type: 'error', message: String(e) })
      }
    },
    async stopRecordingLangchain() {
      this.isRecordingLangchain = false
      if (this.processorNodeLangchain) {
        try { this.processorNodeLangchain.disconnect() } catch (e) { /* ignore disconnect errors */ }
        this.processorNodeLangchain = null
      }
      if (this.sourceNodeLangchain) {
        try { this.sourceNodeLangchain.disconnect() } catch (e) { /* ignore disconnect errors */ }
        this.sourceNodeLangchain = null
      }
      if (this.sinkNodeLangchain) {
        try { this.sinkNodeLangchain.disconnect() } catch (e) { /* ignore disconnect errors */ }
        this.sinkNodeLangchain = null
      }
      if (this.audioContextLangchain) {
        try { await this.audioContextLangchain.close() } catch (e) { /* ignore close errors */ }
        this.audioContextLangchain = null
      }
      if (this.micStreamLangchain) {
        try { this.micStreamLangchain.getTracks().forEach((t) => t.stop()) } catch (e) { /* ignore stop errors */ }
        this.micStreamLangchain = null
      }
    },
    handleAgentEventLangchain(payload) {
      const type = payload && payload.type
      if (!type) return
      if (type === 'stt_chunk') {
        this.sttPartialLangchain = payload.transcript || ''
        return
      }
      if (type === 'stt_output') {
        this.sttFinalLangchain = payload.transcript || ''
        this.sttPartialLangchain = ''
        this.agentTextLangchain = ''
        return
      }
      if (type === 'agent_chunk') {
        this.agentTextLangchain += payload.text || ''
        return
      }
      if (type === 'tts_chunk') {
        this.playTtsChunkLangchain(payload.audio || '')
      }
    },
    async ensureTtsAudioContextLangchain() {
      if (this.ttsAudioCtxLangchain) {
        if (this.ttsAudioCtxLangchain.state === 'suspended') {
          try {
            await this.ttsAudioCtxLangchain.resume()
          } catch (e) {
            this.appendLogLangchain('<-', { type: 'error', message: String(e) })
          }
        }
        return
      }
      const AudioContextClass = window.AudioContext || window.webkitAudioContext
      if (!AudioContextClass) return
      this.ttsAudioCtxLangchain = new AudioContextClass()
      this.ttsNextPlayTimeLangchain = this.ttsAudioCtxLangchain.currentTime
      if (this.ttsAudioCtxLangchain.state === 'suspended') {
        try {
          await this.ttsAudioCtxLangchain.resume()
        } catch (e) {
          this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        }
      }
    },
    base64ToUint8ArrayLangchain(base64) {
      if (!base64) return null
      try {
        const raw = window.atob(base64)
        const arr = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i)
        return arr
      } catch (e) {
        this.appendLogLangchain('<-', { type: 'error', message: String(e) })
        return null
      }
    },
    async playTtsChunkLangchain(base64Audio) {
      const bytes = this.base64ToUint8ArrayLangchain(base64Audio)
      if (!bytes || bytes.byteLength < 2) return
      await this.ensureTtsAudioContextLangchain()
      if (!this.ttsAudioCtxLangchain) return
      const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2))
      const floatData = new Float32Array(samples.length)
      for (let i = 0; i < samples.length; i++) {
        floatData[i] = Math.max(-1, Math.min(1, samples[i] / 32768))
      }
      const buffer = this.ttsAudioCtxLangchain.createBuffer(1, floatData.length, 24000)
      buffer.getChannelData(0).set(floatData)
      const source = this.ttsAudioCtxLangchain.createBufferSource()
      source.buffer = buffer
      source.connect(this.ttsAudioCtxLangchain.destination)
      const now = this.ttsAudioCtxLangchain.currentTime
      const startAt = Math.max(now, this.ttsNextPlayTimeLangchain)
      source.start(startAt)
      this.ttsNextPlayTimeLangchain = startAt + buffer.duration
    },
    // 人脸识别相关方法
    openFaceRecognition() {
      this.showFaceRecognition = true
      this.recognitionResult = null
      this.checkFaceInfo()
    },
    handleCloseFaceRecognition() {
      this.showFaceRecognition = false
      this.recognitionResult = null
    },
    async checkFaceInfo() {
      try {
        // axios拦截器已经处理过响应，response直接是后端返回的{code, data, msg}
        const response = await this.$axios.get('/face/info')
        if (response.code === 200 && response.data.has_face) {
          this.$set(this, 'hasFace', true)
          this.$set(this, 'faceStatus', 'uploaded')
          // 已上传人脸，自动开始识别
          setTimeout(() => {
            this.startRecognition()
          }, 500)
        } else {
          this.$set(this, 'hasFace', false)
          this.$set(this, 'faceStatus', 'idle')
        }
      } catch (error) {
        this.$set(this, 'hasFace', false)
        this.$set(this, 'faceStatus', 'idle')
      }
    },
    async selectImage() {
      // 触发文件选择
      const fileInput = this.$refs.fileInput || this.$refs.reuploadInput
      if (fileInput) {
        fileInput.click()
      }
    },
    async uploadToMinIO(file) {
      // 步骤1：获取预签名上传URL
      let initResponse
      try {
        initResponse = await this.$axios.post('/file/presign/init', {
          purpose: 'face',
          filename: file.name,
          content_type: file.type,
          size: file.size
        })
      } catch (error) {
        // 请求失败或响应拦截器抛出异常
        const msg = (error.response && error.response.data && error.response.data.msg) || '获取上传地址失败'
        throw new Error(msg)
      }

      // 响应拦截器已处理，直接检查code
      if (!initResponse || initResponse.code !== 200) {
        const msg = (initResponse && initResponse.msg) || '获取上传地址失败'
        // 如果 S3 未启用，降级到表单上传
        if (initResponse && initResponse.code === 400 && msg === 'S3 media not enabled') {
          return await this.uploadByForm(file)
        }
        throw new Error(msg)
      }

      const { asset_id: assetId, upload_url: uploadUrl, headers } = initResponse.data

      // 根据当前页面协议动态调整 MinIO URL 协议（兼容 HTTP 和 HTTPS）
      const fixedUploadUrl = window.location.protocol === 'https:'
        ? uploadUrl.replace('http://', 'https://')
        : uploadUrl.replace('https://', 'http://')

      // 步骤2：上传文件到 MiniIO（直接 PUT 请求到预签名 URL）
      const uploadResponse = await fetch(fixedUploadUrl, {
        method: 'PUT',
        body: file,
        headers: {
          ...(headers || {}),
          'Content-Type': file.type
        }
      })

      if (!uploadResponse.ok) {
        throw new Error(`上传文件失败: ${uploadResponse.status}`)
      }

      // 步骤3：确认上传完成
      let completeResponse
      try {
        completeResponse = await this.$axios.post('/file/presign/complete', {
          asset_id: assetId
        })
      } catch (error) {
        const msg = (error.response && error.response.data && error.response.data.msg) || '确认上传失败'
        throw new Error(msg)
      }

      if (!completeResponse || completeResponse.code !== 200) {
        throw new Error((completeResponse && completeResponse.msg) || '确认上传失败')
      }

      // 步骤4：获取文件访问URL
      let urlResponse
      try {
        urlResponse = await this.$axios.get('/file/presign/url', {
          params: { asset_id: assetId }
        })
      } catch (error) {
        const msg = (error.response && error.response.data && error.response.data.msg) || '获取文件URL失败'
        throw new Error(msg)
      }

      if (!urlResponse || urlResponse.code !== 200) {
        throw new Error((urlResponse && urlResponse.msg) || '获取文件URL失败')
      }

      return urlResponse.data.url
    },
    async uploadByForm(file) {
      // 降级方案：直接通过表单上传到后端
      const formData = new FormData()
      formData.append('file', file)

      let response
      try {
        response = await this.$axios.post('/file/upload', formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        })
      } catch (error) {
        const msg = (error.response && error.response.data && error.response.data.msg) || '上传失败'
        throw new Error(msg)
      }

      if (!response || response.code !== 200) {
        throw new Error((response && response.msg) || '上传失败')
      }

      // 将相对路径转换为完整的绝对URL
      let fileUrl = response.data.url
      if (fileUrl.startsWith('/')) {
        // 拼接后端基础URL
        const baseUrl = process.env.VUE_APP_API_TARGET_DEFAULT || 'http://localhost:8086'
        fileUrl = baseUrl + fileUrl
      }

      return fileUrl
    },
    async handleImageSelect(event) {
      const file = event.target.files[0]
      if (!file) return

      // 验证文件类型
      if (!file.type.startsWith('image/')) {
        Toast.fail('请选择图片文件')
        return
      }

      // 验证文件大小（最大 5MB）
      if (file.size > 5 * 1024 * 1024) {
        Toast.fail('图片大小不能超过 5MB')
        return
      }

      this.faceStatus = 'uploading'

      try {
        // 使用 MiniIO 上传流程
        const faceUrl = await this.uploadToMinIO(file)

        // 调用 Django 人脸识别 API 上传人脸
        const response = await this.$axios.post('/face/upload', {
          face_url: faceUrl
        })

        // axios拦截器已经处理过响应，response直接是后端返回的{code, data, msg}
        if (response.code === 200) {
          Toast.success('人脸照片上传成功')
          // 使用 Vue.set 确保响应式更新
          this.$set(this, 'hasFace', true)
          this.$set(this, 'faceStatus', 'uploaded')
          this.$set(this, 'recognitionResult', null)
          // 强制重新渲染确保界面正确更新
          this.$forceUpdate()
          // 重新检查人脸状态确保一致性
          setTimeout(() => {
            this.checkFaceInfo()
          }, 300)
        } else {
          Toast.fail(response.msg || '上传失败')
          this.faceStatus = 'idle'
        }
      } catch (error) {
        Toast.fail('上传失败，请重试')
        this.faceStatus = 'idle'
      }

      // 重置文件输入
      const target = event.target
      Promise.resolve().then(() => {
        target.value = ''
      })
    },
    async startRecognition() {
      // 使用摄像头拍照进行识别
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        Toast.fail('当前浏览器不支持摄像头')
        return
      }

      let stream = null
      try {
        this.isRecognizing = true
        this.faceStatus = 'recognizing'
        this.recognitionResult = null

        // 请求摄像头权限
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }})

        // 获取视频元素并显示摄像头画面
        const video = this.$refs.videoRef
        if (video) {
          video.srcObject = stream
          await video.play()
        }

        // 等待摄像头就绪并拍照
        await new Promise(resolve => setTimeout(resolve, 2000))

        // 拍照
        const canvas = document.createElement('canvas')
        const videoElement = video || document.createElement('video')
        canvas.width = videoElement.videoWidth || 640
        canvas.height = videoElement.videoHeight || 480
        const ctx = canvas.getContext('2d')
        ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height)

        // 停止摄像头
        if (stream) {
          stream.getTracks().forEach(track => track.stop())
        }

        // 清除视频显示
        if (video) {
          video.srcObject = null
        }

        // 转换为 Blob
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg'))

        // 创建 File 对象
        const file = new File([blob], 'face_capture.jpg', { type: 'image/jpeg' })

        // 使用 MiniIO 上传流程
        const faceUrl = await this.uploadToMinIO(file)

        // 调用 Django 人脸识别 API 进行比对
        const response = await this.$axios.post('/face/match', {
          face_url: faceUrl
        })

        // axios拦截器已经处理过响应，response直接是后端返回的{code, data, msg}
        if (response.code === 200) {
          this.recognitionResult = response.data
          this.faceStatus = response.data.matched ? 'matched' : 'failed'

          if (response.data.matched) {
            Toast.success('人脸识别成功！')
          } else {
            Toast.fail(response.data.message || '人脸识别失败')
          }
        } else {
          Toast.fail(response.msg || '识别失败')
          this.faceStatus = 'failed'
        }
      } catch (error) {
        // 停止摄像头
        if (stream) {
          stream.getTracks().forEach(track => track.stop())
        }
        // 清除视频显示
        const video = this.$refs.videoRef
        if (video) {
          video.srcObject = null
        }

        Toast.fail('识别失败，请重试')
        this.faceStatus = 'uploaded'
        this.recognitionResult = {
          matched: false,
          confidence: 0,
          message: '识别失败: ' + (error.message || '未知错误')
        }
      } finally {
        this.isRecognizing = false
      }
    }
  }
}
</script>

<style scoped>
.mobile-ai {
  background-color: #f7f8fa;
  min-height: 100vh;
}
.ai-grid {
    padding-top: 10px;
}
.voice-popup {
  display: flex;
  flex-direction: column;
}
.va {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.va-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 8px;
}
.va-title {
  font-size: 16px;
  font-weight: 600;
}
.va-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.va-setting {
  font-size: 18px;
  color: #666;
}
.va-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #e7e8ef;
  background: #f7f8fa;
}
.va-status.ok {
  color: #128a4f;
}
.va-status.bad {
  color: #b42318;
}
.va-body {
  flex: 1;
  min-height: 0;
  padding: 0 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.va-lc-panels {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.va-lc-panel {
  background: #fff;
  border: 1px solid #e9edf3;
  border-radius: 8px;
  padding: 8px;
}
.va-lc-title {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
}
.va-lc-text {
  font-size: 13px;
  color: #111827;
  min-height: 18px;
  white-space: pre-wrap;
  word-break: break-word;
}
.va-log-body {
  flex: 1;
  min-height: 140px;
  background: #0d0f1a;
  color: #d6dcff;
  border-radius: 10px;
  padding: 10px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.35;
}
.va-log-line {
  white-space: pre-wrap;
  word-break: break-word;
}
.va-composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px 14px;
  border-top: 1px solid #eef0f5;
}
.va-mode {
  font-size: 22px;
  color: #4b5563;
  padding: 6px;
}
.va-text-wrap {
  flex: 1;
  min-width: 0;
}
.va-text :deep(.van-field__control) {
  background: #f7f8fa;
  border-radius: 10px;
  padding: 10px 10px;
}
.va-ptt {
  flex: 1;
  min-width: 0;
  background: #f7f8fa;
  border-radius: 10px;
  padding: 12px 10px;
  text-align: center;
  color: #111;
  user-select: none;
}
.va-ptt.pressed {
  background: #e7ecff;
}
.va-send {
  height: 36px;
}
.va-settings {
  padding: 12px 12px 16px;
}
.va-settings-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
}
.va-settings-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 2px 10px;
}

/* 人脸识别弹窗样式 */
.face-popup {
  display: flex;
  flex-direction: column;
}

.face-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.face-header {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px 12px 12px;
}

.face-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.face-body {
  flex: 1;
  min-height: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.upload-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.upload-icon {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
}

.upload-text {
  font-size: 18px;
  font-weight: 500;
  color: #111827;
}

.upload-hint {
  font-size: 14px;
  color: #6b7280;
}

.upload-btn {
  width: 100%;
  max-width: 200px;
  height: 44px;
}

.file-input {
  display: none;
}

.recognize-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.face-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.preview-label {
  font-size: 12px;
  color: #6b7280;
}

.preview-placeholder {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
}

.recognize-hint {
  font-size: 14px;
  color: #6b7280;
}

.reupload-btn {
  color: #6b7280;
}

/* 摄像头相关样式 */
.camera-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.camera-label {
  font-size: 14px;
  color: #6b7280;
}

.camera-container {
  position: relative;
  width: 100%;
  max-width: 300px;
  aspect-ratio: 4/3;
  border-radius: 12px;
  overflow: hidden;
  background: #1a1a1a;
}

.camera-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}

.face-frame {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 120px;
  height: 120px;
  border: 3px solid #10b981;
  border-radius: 50%;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.5);
  pointer-events: none;
}

.result-section {
  position: fixed;
  top: 55%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(255, 255, 255, 0.98);
  border-radius: 20px;
  padding: 40px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  z-index: 1000;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  min-width: 260px;
}

.result-icon {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.result-icon.success {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #fff;
}

.result-icon.fail {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: #fff;
}

.result-text {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.result-text.success {
  color: #059669;
}

.result-text.fail {
  color: #dc2626;
}

.result-confidence {
  font-size: 14px;
  color: #6b7280;
}
</style>
