<template>
  <div class="mobile-ai">
    <van-nav-bar title="AI Park" fixed placeholder />

    <van-grid :column-num="2" :gutter="10" clickable class="ai-grid">
      <van-grid-item icon="chat-o" text="Langchain Chat" to="/mobile/functions/langchain" />
      <van-grid-item icon="photo-o" text="Image Generation" />
      <van-grid-item icon="music-o" text="Voice Assistant" @click="openVoiceAssistant" />
      <van-grid-item icon="star-o" text="Voice Assistant (LC)" @click="openVoiceAssistantLangchain" />
      <van-grid-item icon="video-o" text="Video Creator" />
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
      ttsNextPlayTimeLangchain: 0
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
        try { this.processorNodeLangchain.disconnect() } catch (e) {}
        this.processorNodeLangchain = null
      }
      if (this.sourceNodeLangchain) {
        try { this.sourceNodeLangchain.disconnect() } catch (e) {}
        this.sourceNodeLangchain = null
      }
      if (this.sinkNodeLangchain) {
        try { this.sinkNodeLangchain.disconnect() } catch (e) {}
        this.sinkNodeLangchain = null
      }
      if (this.audioContextLangchain) {
        try { await this.audioContextLangchain.close() } catch (e) {}
        this.audioContextLangchain = null
      }
      if (this.micStreamLangchain) {
        try { this.micStreamLangchain.getTracks().forEach((t) => t.stop()) } catch (e) {}
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
</style>
