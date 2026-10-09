<template>
  <div class="ai-entrance">
    <!-- 顶部 Header -->
    <div class="ae-header">
      <div class="ae-header-title">宝宝 AI 助手</div>
      <div class="ae-header-actions">
        <span :class="['ae-status-dot', isWsOpen ? 'ok' : 'bad']" />
        <span class="ae-status-text">{{ isWsOpen ? '在线' : wsStatusText }}</span>
      </div>
    </div>

    <!-- 消息区 -->
    <div ref="msgList" class="ae-body">
      <!-- 欢迎页 -->
      <div v-if="messages.length === 0" class="ae-welcome">
        <!-- 圆形 AI 头像 -->
        <div class="ae-avatar-wrap">
          <div class="ae-avatar">
            <svg viewBox="0 0 120 120" width="100%" height="100%">
              <defs>
                <radialGradient id="avatarBg" cx="50%" cy="40%" r="60%">
                  <stop offset="0%" stop-color="#a5b4fc" />
                  <stop offset="100%" stop-color="#6366f1" />
                </radialGradient>
                <linearGradient id="hairGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stop-color="#4c1d95" />
                  <stop offset="100%" stop-color="#312e81" />
                </linearGradient>
              </defs>
              <!-- 背景圆 -->
              <circle cx="60" cy="60" r="58" fill="url(#avatarBg)" />
              <!-- 脸 -->
              <ellipse cx="60" cy="68" rx="30" ry="32" fill="#fce7d5" />
              <!-- 头发 -->
              <path d="M30,55 Q30,25 60,22 Q90,25 90,55 Q88,40 60,38 Q32,40 30,55 Z" fill="url(#hairGrad)" />
              <!-- 刘海 -->
              <path d="M35,45 Q40,35 60,34 Q80,35 85,45 Q75,38 60,40 Q45,38 35,45 Z" fill="#312e81" />
              <!-- 眼睛 -->
              <ellipse cx="48" cy="65" rx="4" ry="5" fill="#1f2937" />
              <ellipse cx="72" cy="65" rx="4" ry="5" fill="#1f2937" />
              <circle cx="49" cy="63" r="1.5" fill="#fff" />
              <circle cx="73" cy="63" r="1.5" fill="#fff" />
              <!-- 腮红 -->
              <circle cx="42" cy="78" r="5" fill="#fca5a5" opacity="0.5" />
              <circle cx="78" cy="78" r="5" fill="#fca5a5" opacity="0.5" />
              <!-- 嘴巴 -->
              <path d="M52,82 Q60,88 68,82" stroke="#1f2937" stroke-width="2" fill="none" stroke-linecap="round" />
            </svg>
          </div>
          <!-- 光晕动画 -->
          <div class="ae-avatar-glow" />
        </div>

        <!-- 欢迎语 -->
        <div class="ae-welcome-text">
          嗨，我是宝宝 AI 助手 👶
        </div>
        <div class="ae-welcome-sub">
          我可以帮你记录喂奶、体温、睡眠、尿不湿，也能回答育儿问题，陪你聊聊～
        </div>

        <!-- 快捷问题 -->
        <div class="ae-quick-chips">
          <div v-for="c in quickChips" :key="c" class="ae-chip" @click="onChip(c)">
            <span class="ae-chip-text">{{ c }}</span>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div
        v-for="(m, idx) in messages"
        :key="idx"
        :class="['ae-msg', m.role === 'user' ? 'is-user' : 'is-ai']"
      >
        <!-- 消息气泡 -->
        <div class="ae-bubble-wrap">
          <div :class="['ae-bubble', m.role === 'user' ? 'user' : 'ai']">
            <!-- AI 工具调用轨迹 -->
            <div v-if="m.toolEvents && m.toolEvents.length" class="ae-tools">
              <div v-for="(t, ti) in m.toolEvents" :key="ti" class="ae-tool-item">
                <span class="ae-tool-icon">{{ t.ok === false ? '⚠️' : '🔧' }}</span>
                <span class="ae-tool-name">{{ t.name }}</span>
                <span class="ae-tool-result">{{ t.brief }}</span>
              </div>
            </div>
            <!-- AI 确认卡片 -->
            <div v-if="m.confirm" class="ae-confirm">
              <div class="ae-confirm-title">📋 待确认操作</div>
              <div v-for="(t, ci) in m.confirm.tools" :key="ci" class="ae-confirm-item">
                <b>{{ toolLabel(t.name) }}</b>
                <div class="ae-confirm-args" v-html="argsDisplay(t.name, t.args)" />
              </div>
              <div class="ae-confirm-actions">
                <button class="ae-btn primary" :disabled="m.confirm.confirming" @click="onConfirm(m.confirm.confirm_id, 'approve')">{{ m.confirm.confirming ? '处理中…' : '确认' }}</button>
                <button class="ae-btn" :disabled="m.confirm.confirming" @click="onConfirm(m.confirm.confirm_id, 'reject')">取消</button>
              </div>
            </div>
            <!-- 文本内容 -->
            <span v-if="m.text">{{ m.text }}<span v-if="m.streaming" class="ae-cursor">▍</span><span v-if="m.cancelled" class="ae-cancelled">（已中断）</span></span>
            <span v-if="!m.text && !m.toolEvents && !m.confirm" class="ae-typing">{{ m.cancelled ? '已中断' : '思考中…' }}</span>
          </div>
        </div>
      </div>

      <div v-if="loading && lastStreamingEmpty" class="ae-typing-indicator">
        <span /><span /><span />
      </div>
    </div>

    <!-- 底部输入区 - 豆包风格：整体一个圆角卡片条框 -->
    <div class="ae-composer">
      <div class="ae-input-bar">
        <!-- 左侧：相机按钮 -->
        <button class="ab-icon-btn" title="拍照/图片" @click="onCamera">
          <van-icon name="photograph" size="20" />
        </button>

        <!-- 中间：按住说话 / 文字输入 二选一 -->
        <div class="ab-input-area">
          <!-- 默认语音模式：按住说话 -->
          <div
            v-if="!isTextMode"
            class="ab-ptt-btn"
            :class="{ pressing: isPressing }"
            @touchstart.prevent="onPressStart"
            @touchend.prevent="onPressEnd"
            @touchcancel.prevent="onPressCancel"
            @mousedown.prevent="onPressStart"
            @mouseup.prevent="onPressEnd"
            @mouseleave.prevent="onPressCancel"
          >
            <span class="ab-ptt-text">{{ isRecording ? '松开 结束' : '按住 说话' }}</span>
          </div>
          <!-- 文字模式：输入框 -->
          <input
            v-else
            ref="textInput"
            v-model="textInput"
            class="ab-text-input"
            type="text"
            placeholder="问问宝宝的喂奶、体温、睡眠…"
            @keydown.enter.exact.prevent="onSend"
          >
        </div>

        <!-- 右侧：键盘/麦克风 切换按钮 -->
        <button class="ab-icon-btn" :title="isTextMode ? '语音输入' : '键盘输入'" @click="toggleInputMode">
          <van-icon :name="isTextMode ? 'audio' : 'edit'" size="20" />
        </button>

        <!-- 发送/加号 -->
        <button v-if="canSendText" class="ab-icon-btn send" title="发送" @click="onSend">
          <van-icon name="arrow-up" size="18" color="#fff" />
        </button>
        <button v-else class="ab-icon-btn" title="更多" @click="onPlus">
          <van-icon name="plus" size="20" />
        </button>
      </div>
    </div>

    <!-- 录音中提示浮层 -->
    <div v-if="isRecording" class="ae-recording-mask" @touchstart.stop @touchend.stop @mousedown.stop @mouseup.stop>
      <div class="ae-recording-card">
        <!-- 实时转写文字 ★ -->
        <div v-if="liveTranscript" class="ae-live-transcript">{{ liveTranscript }}</div>
        <div class="ae-recording-wave">
          <span v-for="n in 12" :key="n" :style="{ animationDelay: (n * 0.08) + 's' }" />
        </div>
        <div class="ae-recording-tip">{{ isPressing ? '松开 发送' : '手指上滑 取消' }}</div>
        <div class="ae-recording-cancel">上滑取消</div>
      </div>
    </div>

    <!-- 隐藏的文件选择 -->
    <input ref="fileInput" type="file" accept="image/*" class="ae-file-input" @change="onFileChange">
  </div>
</template>

<script>
import { Toast } from 'vant'
import { getToken } from '@/utils/auth'
import { getChatHistory } from '@/api/ai'

export default {
  name: 'AiEntrance',
  data() {
    return {
      // WebSocket
      ws: null,
      wsReadyState: 3,
      wsStatus: 'DISCONNECTED',
      reconnectTimer: null,
      isDestroyed: false,

      // 消息
      messages: [],
      loading: false,
      streamingIdx: -1,
      currentRequestId: null,

      // 输入（默认语音模式）
      isTextMode: false,
      textInput: '',
      isPressing: false,
      isRecording: false,
      pressSessionId: 0,
      sentAudioBytes: 0,

      // 录音相关
      micStream: null,
      audioContext: null,
      processorNode: null,
      sourceNode: null,
      sinkNode: null,
      inputSampleRate: 48000,
      targetSampleRate: 16000,
      liveTranscript: '', // ★ 录音浮层上实时显示的转写文字

      // TTS 播放
      ttsAudioCtx: null,
      ttsNextPlayTime: 0,

      // 快捷问题
      quickChips: [
        '今天喝了多少奶',
        '宝宝体温多少',
        '昨晚睡眠怎么样',
        '本月花了多少钱',
        '疫苗还有哪些没打',
        '最近身高体重',
        '宝宝多大啦',
        '育儿小贴士'
      ]
    }
  },
  computed: {
    isWsOpen() {
      return this.wsReadyState === 1
    },
    wsStatusText() {
      return { 0: '连接中', 2: '关闭中', 3: '离线' }[this.wsReadyState] || this.wsStatus
    },
    canSendText() {
      return this.isWsOpen && this.textInput.trim().length > 0 && this.isTextMode
    },
    lastStreamingEmpty() {
      const m = this.messages[this.streamingIdx]
      return this.loading && (!m || (!m.text && !(m.toolEvents || []).length && !m.confirm))
    }
  },
  mounted() {
    this.loadHistory().finally(() => this.connect())
  },
  beforeDestroy() {
    this.isDestroyed = true
    this.disconnect()
    this.stopRecording()
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
  },
  methods: {
    // ─── 加载聊天历史 ────────────────────
    async loadHistory() {
      try {
        const res = await getChatHistory(50)
        if (res.code === 200 && res.data && res.data.messages) {
          const msgs = res.data.messages
          this.messages = msgs.map(m => {
            if (m.role === 'user') {
              return { role: 'user', text: m.text, fromHistory: true }
            }
            // AI 消息: 恢复 text, toolEvents; 历史 confirm 已过期, 不渲染按钮
            let text = m.text || ''
            const confirm = null
            if (m.confirm) {
              // 历史 confirm 卡片: 保留信息但标记过期, 不显示按钮
              text = text || '📋 待确认操作（会话已结束）'
            }
            return {
              role: 'ai',
              text,
              toolEvents: (m.tool_events || []).map(t => ({ name: t.name, brief: t.brief || '完成', ok: t.ok })),
              confirm,
              streaming: false,
              fromHistory: true
            }
          }).filter(m => m.text || (m.toolEvents && m.toolEvents.length))
          this.scrollToBottom()
        }
      } catch (e) {
        // 历史加载失败不阻塞 WS 连接
        console.warn('[AiEntrance] load history failed:', e)
      }
    },
    // ─── WS 连接 ────────────────────────
    getDefaultWsUrl() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // 统一走 /prod-ai 代理路径: dev 环境由 vue.config.js 代理到后端 8001,
      // 线上由 Nginx 转发到后端 8001。避免 Remote SSH 时浏览器 127.0.0.1 指向本地电脑。
      return `${scheme}://${window.location.host}/prod-ai/ws/app-ai-entrance`
    },
    buildWsUrl() {
      let base = this.getDefaultWsUrl()
      const token = getToken() || ''
      if (token) {
        base += `${base.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      }
      return base
    },
    connect() {
      if (this.wsReadyState === 1 || this.wsReadyState === 0) {
        console.log('[AiEntrance.connect] already connecting/connected, skip')
        return
      }
      const token = getToken()
      if (!token) {
        console.warn('[AiEntrance.connect] no token found, skip WS connection — user not logged in?')
        this.wsStatus = 'NO_TOKEN'
        return
      }
      const url = this.buildWsUrl()
      console.log('[AiEntrance.connect] wsUrl=', url)
      console.log('[AiEntrance.connect] token len=', token.length)
      let socket
      try {
        socket = new WebSocket(url)
      } catch (e) {
        console.error('[AiEntrance.connect] WebSocket constructor failed:', e)
        this.wsReadyState = 3
        return
      }
      socket.binaryType = 'arraybuffer'
      this.wsReadyState = socket.readyState
      socket.onopen = () => {
        console.log('[AiEntrance] WS onopen ✅')
        this.wsReadyState = 1
        this.wsStatus = 'CONNECTED'
      }
      socket.onmessage = (evt) => { this.handleMessage(evt) }
      socket.onerror = (e) => {
        console.error('[AiEntrance] WS onerror ❌', e)
      }
      socket.onclose = (evt) => {
        console.log('[AiEntrance] WS onclose code=', evt.code, 'reason=', evt.reason, 'wasClean=', evt.wasClean)
        this.wsReadyState = 3
        this.ws = null
        // 关键：组件已销毁时禁止重连 — 否则会出现"旧实例重连 + 新实例也连"的连接泄漏
        if (this.isDestroyed) {
          console.log('[AiEntrance] component destroyed, skip reconnect')
          return
        }
        if (!this.reconnectTimer) {
          console.log('[AiEntrance] scheduling reconnect in 3s...')
          this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null
            if (!this.isDestroyed) this.connect()
          }, 3000)
        }
      }
      this.ws = socket
    },
    disconnect() {
      if (!this.ws) return
      try { this.ws.close(1000, 'client close') } catch (e) { /* ignore */ }
      this.ws = null
      this.wsReadyState = 3
    },
    handleMessage(evt) {
      const data = evt.data
      // 打印后端发来的原始消息
      if (typeof data === 'string') {
        console.log('[AiEntrance] ← backend message:', data)
        try { this.handleEvent(JSON.parse(data)) } catch (e) { /* ignore */ }
      } else {
        console.log('[AiEntrance] ← backend binary:', data && data.byteLength, 'bytes')
        this.playTtsChunk(data)
      }
    },

    // ─── WS 事件分发 ──────────────────────
    /** 判断消息是否是当前请求的有效流式消息 */
    isCurrentMsg(m) {
      if (!m) return false
      if (m.cancelled) return false
      if (!m.request_id) return true // 后端没返回 request_id 时默认接收
      return m.request_id === this.currentRequestId
    },
    handleEvent(p) {
      const type = p && p.type
      if (!type) return
      // 后端协议为平铺格式: {type, request_id, answer, chunk, ...}
      // 不嵌套在 data 字段里, 故直接从 p 取值
      if (type === 'connected' || type === 'pong') return
      if (type === 'voice_started') return
      if (type === 'cancel_ack') return // 后端确认取消，跳过

      // ── 语音识别结果 ──────────────────────
      if (type === 'stt_chunk') {
        // 部分识别 → 更新录音浮层上的实时文字 (用户正盯着浮层看)
        this.liveTranscript = p.transcript || ''
        return
      }
      if (type === 'stt_output') {
        // 句尾定稿 → 压入 user 气泡 + 准备 AI streaming 气泡
        const transcript = (p.transcript || '').trim()
        if (!transcript) { this.liveTranscript = ''; return }
        this.messages.push({ role: 'user', text: transcript })
        const reqId = p.request_id || this.currentRequestId || this.genRequestId()
        this.currentRequestId = reqId
        this.streamingIdx = this.messages.length
        this.messages.push({ role: 'ai', text: '', toolEvents: [], streaming: true, request_id: reqId })
        this.loading = true
        this.liveTranscript = '' // 定稿后清空浮层上的实时文字
        this.scrollToBottom()
        return
      }
      if (type === 'query_received') {
        // 后端归一化完成, 确保存在 AI streaming 气泡 + request_id
        if (p.request_id) this.currentRequestId = p.request_id
        this.loading = true
        if (this.streamingIdx < 0 || !this.messages[this.streamingIdx]?.streaming) {
          this.streamingIdx = this.messages.length
          this.messages.push({ role: 'ai', text: '', toolEvents: [], streaming: true, request_id: p.request_id || this.currentRequestId })
        } else {
          const aiM = this.messages[this.streamingIdx]
          if (aiM && p.request_id) aiM.request_id = p.request_id
        }
        this.scrollToBottom()
        return
      }

      if (type === 'intent_detected') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) { m.intent = p.intent; if (p.confidence) m.confidence = p.confidence }
        return
      }
      if (type === 'tool_call') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) { m.toolEvents = m.toolEvents || []; m.toolEvents.push({ name: p.name, brief: this.argsBrief(p.args), ok: null }) }
        this.scrollToBottom(); return
      }
      if (type === 'tool_result') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m) && m.toolEvents && m.toolEvents.length) {
          const t = m.toolEvents[m.toolEvents.length - 1]; t.ok = p.ok !== false; t.brief = this.resultBrief(p.result)
        }
        return
      }
      if (type === 'confirmation_request') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) {
          m.confirm = { confirm_id: p.confirm_id, tools: p.tools || [] }
          // 确认卡已到, 停止 "思考中" 动画 + 清 loading (用户需要点按钮)
          m.streaming = false
          this.loading = false
        }
        this.scrollToBottom(); return
      }
      if (type === 'retrieve_done') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) { m.toolEvents = m.toolEvents || []; m.toolEvents.push({ name: 'rag_retrieve', brief: `知识库检索 ${p.count || 0} 条`, ok: true }) }
        return
      }
      if (type === 'agent_chunk' || type === 'generate_chunk') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) { m.text = (m.text || '') + (p.chunk || p.text || ''); this.scrollToBottom() }
        return
      }
      if (type === 'answer_done') {
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) {
          if (!m.text && p.answer) m.text = p.answer
          if (p.tool_trace && (!m.toolEvents || !m.toolEvents.length)) {
            m.toolEvents = p.tool_trace.map(t => ({ name: t.name, brief: t.ok ? '完成' : '失败', ok: t.ok }))
          }
          m.streaming = false
        }
        return
      }
      if (type === 'tts_chunk' && p.audio) { this.playTtsBase64(p.audio); return }
      if (type === 'query_done' || type === 'request_done') {
        // stale_cancelled 是清理上一轮残留 interrupt, 不是当前 query 结束;
        // 其 request_id 是新生成的 uuid, 与当前 request_id 不同。
        // 不能据此清 loading / streaming, 否则后续 confirmation_request 挂不上
        const route = p.route || ''
        const rid = p.request_id || ''
        if (route.includes('stale') || (rid && this.currentRequestId && rid !== this.currentRequestId)) {
          return // 忽略: 不是当前 query 的 done
        }
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) {
          m.streaming = false
          // confirm 流程结束 (approve/reject 后的 query_done): 清除确认卡
          if (m.confirm) m.confirm = null
        }
        this.loading = false
        return
      }
      if (type === 'query_error' || type === 'error') {
        // 同理: 非当前 request_id 的 error 不影响当前 loading 状态
        const rid = p.request_id || ''
        if (rid && this.currentRequestId && rid !== this.currentRequestId) {
          return
        }
        const errMsg = p.error || '未知错误'
        // pending write confirmation: 有待确认的操作未处理, 滚动到现有确认卡
        if (errMsg.includes('pending') && errMsg.includes('confirm')) {
          this.loading = false
          // 找到带 confirm 的消息并滚动到它
          const cidx = this.messages.findIndex(m => m.confirm)
          if (cidx >= 0) {
            this.$set(this.messages[cidx].confirm, 'confirming', false)
            this.scrollToBottom()
          }
          return
        }
        this.loading = false
        // 确认流程出错: 恢复确认卡按钮 (去掉 "处理中")
        const cidx2 = this.messages.findIndex(m => m.confirm)
        if (cidx2 >= 0) this.$set(this.messages[cidx2].confirm, 'confirming', false)
        const m = this.messages[this.streamingIdx]
        if (this.isCurrentMsg(m)) { m.text = m.text || `出错了: ${errMsg}`; m.streaming = false }
        return
      }
    },

    // ─── 发送 ────────────────────────────
    genRequestId() { return `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` },

    /** 打断上一个流式回答：前端截断 + 通知后端 */
    cancelPreviousStreaming() {
      if (this.streamingIdx >= 0 && this.streamingIdx < this.messages.length) {
        const prev = this.messages[this.streamingIdx]
        if (prev && prev.streaming) {
          prev.streaming = false
          prev.cancelled = true
          // 给后端发 cancel 信号（后端 app_ai_entrance 后续可以实现）
          if (this.isWsOpen) {
            try { this.ws.send(JSON.stringify({ type: 'cancel' })) } catch (e) { /* ignore */ }
          }
        }
      }
      this.loading = false
    },

    onChip(text) { this.isTextMode = true; this.textInput = text; this.$nextTick(() => this.onSend()) },

    onSend() {
      const text = this.textInput.trim()
      if (!text || !this.isWsOpen) return
      // 关键：发送新问题前，先打断上一个正在流式的回答
      this.cancelPreviousStreaming()

      const requestId = this.genRequestId()
      this.currentRequestId = requestId

      this.messages.push({ role: 'user', text }); this.scrollToBottom()
      this.ws.send(JSON.stringify({ type: 'query', query: text, request_id: requestId }))
      this.textInput = ''
      this.loading = true
      this.streamingIdx = this.messages.length
      this.messages.push({ role: 'ai', text: '', toolEvents: [], streaming: true, request_id: requestId })
      this.scrollToBottom()
    },
    onConfirm(confirmId, action) {
      if (!this.isWsOpen) return
      // 按 confirm_id 找到确认卡所在消息 (不依赖 streamingIdx)
      const idx = this.messages.findIndex(m => m.confirm && m.confirm.confirm_id === confirmId)
      if (idx < 0) return
      const m = this.messages[idx]
      // 标记为 "处理中", 禁用按钮, 但不清除 confirm (等后端响应)
      this.$set(m.confirm, 'confirming', true)
      this.loading = true
      this.ws.send(JSON.stringify({ type: 'confirm', confirm_id: confirmId, action }))
    },

    // ─── 输入模式切换 ────────────────────
    toggleInputMode() {
      this.isTextMode = !this.isTextMode
      this.$nextTick(() => { if (this.isTextMode && this.$refs.textInput) this.$refs.textInput.focus() })
    },

    // ─── 语音输入 ────────────────────────
    onPressStart() {
      if (!this.isWsOpen) { Toast.fail('未连接'); return }
      if (this.isPressing) return
      // 打断上一个流式回答, 清空上次录音残留的实时文字
      this.cancelPreviousStreaming()
      this.liveTranscript = ''
      this.isPressing = true; this.pressSessionId++
      const sessionId = this.pressSessionId
      this.startRecording(sessionId)
    },
    onPressEnd() {
      if (!this.isPressing) return
      this.isPressing = false; this.pressSessionId++
      this.stopRecording()
    },
    onPressCancel() {
      if (!this.isPressing) return
      this.isPressing = false; this.pressSessionId++
      this.stopRecording()
    },
    async startRecording(sessionId) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        Toast.fail('不支持录音'); this.isPressing = false; return
      }
      try { this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true }) } catch (e) { Toast.fail('麦克风权限失败'); this.isPressing = false; return }

      if (!this.isPressing || sessionId !== this.pressSessionId) {
        this.micStream.getTracks().forEach(t => t.stop()); this.micStream = null; return
      }

      const AudioContextClass = window.AudioContext || window.webkitAudioContext
      if (!AudioContextClass) { this.stopRecording(); Toast.fail('不支持录音'); return }

      try {
        this.audioContext = new AudioContextClass()
        this.inputSampleRate = this.audioContext.sampleRate || 48000
        this.sourceNode = this.audioContext.createMediaStreamSource(this.micStream)
        this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1)
        this.sinkNode = this.audioContext.createGain()
        this.sinkNode.gain.value = 0
        this.sentAudioBytes = 0
        this.processorNode.onaudioprocess = (e) => {
          if (!this.ws || this.ws.readyState !== 1 || !this.isRecording) return
          const input = e.inputBuffer.getChannelData(0)
          const downsampled = this.downsampleBuffer(input, this.inputSampleRate, this.targetSampleRate)
          const pcm16 = this.floatTo16BitPCM(downsampled)
          this.sentAudioBytes += pcm16.byteLength
          try { this.ws.send(pcm16.buffer) } catch (err) { console.error(err) }
        }
        this.sourceNode.connect(this.processorNode); this.processorNode.connect(this.sinkNode); this.sinkNode.connect(this.audioContext.destination)
        this.isRecording = true
        this.ws.send(JSON.stringify({ type: 'start', codec: 'pcm_s16le', sample_rate: this.targetSampleRate }))
      } catch (e) { this.stopRecording(); Toast.fail('录音初始化失败') }
    },
    async stopRecording() {
      this.isRecording = false
      if (this.processorNode) { try { this.processorNode.disconnect() } catch (e) { /* ignore */ } this.processorNode = null }
      if (this.sourceNode) { try { this.sourceNode.disconnect() } catch (e) { /* ignore */ } this.sourceNode = null }
      if (this.sinkNode) { try { this.sinkNode.disconnect() } catch (e) { /* ignore */ } this.sinkNode = null }
      if (this.audioContext) { try { await this.audioContext.close() } catch (e) { /* ignore */ } this.audioContext = null }
      if (this.micStream) { try { this.micStream.getTracks().forEach(t => t.stop()) } catch (e) { /* ignore */ } this.micStream = null }
      if (this.isWsOpen && this.sentAudioBytes > 0) {
        this.ws.send(JSON.stringify({ type: 'end', audio_bytes: this.sentAudioBytes }))
      }
      this.sentAudioBytes = 0
    },

    // ─── 音频工具 ────────────────────────
    downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
      if (outputSampleRate >= inputSampleRate) return buffer
      const ratio = inputSampleRate / outputSampleRate
      const newLen = Math.round(buffer.length / ratio)
      const result = new Float32Array(newLen)
      let out = 0; let inp = 0
      while (out < newLen) {
        const next = Math.round((out + 1) * ratio)
        let acc = 0; let cnt = 0
        for (let i = inp; i < next && i < buffer.length; i++) { acc += buffer[i]; cnt++ }
        result[out] = cnt ? acc / cnt : 0
        out++; inp = next
      }
      return result
    },
    floatTo16BitPCM(arr) {
      const out = new Int16Array(arr.length)
      for (let i = 0; i < arr.length; i++) {
        let s = arr[i]; if (s > 1) s = 1; if (s < -1) s = -1
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      return out
    },

    // ─── TTS 播放 ────────────────────────
    async ensureTtsAudioContext() {
      if (this.ttsAudioCtx) { if (this.ttsAudioCtx.state === 'suspended') { try { await this.ttsAudioCtx.resume() } catch (e) { /* ignore */ } } return }
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return
      this.ttsAudioCtx = new AC(); this.ttsNextPlayTime = this.ttsAudioCtx.currentTime
      if (this.ttsAudioCtx.state === 'suspended') { try { await this.ttsAudioCtx.resume() } catch (e) { /* ignore */ } }
    },
    async playTtsChunk(ab) {
      if (!ab || ab.byteLength < 2) return
      await this.ensureTtsAudioContext(); if (!this.ttsAudioCtx) return
      try {
        const samples = new Int16Array(ab)
        const floatData = new Float32Array(samples.length)
        for (let i = 0; i < samples.length; i++) floatData[i] = Math.max(-1, Math.min(1, samples[i] / 32768))
        const buf = this.ttsAudioCtx.createBuffer(1, floatData.length, 24000)
        buf.getChannelData(0).set(floatData)
        const src = this.ttsAudioCtx.createBufferSource(); src.buffer = buf; src.connect(this.ttsAudioCtx.destination)
        const now = this.ttsAudioCtx.currentTime; const startAt = Math.max(now, this.ttsNextPlayTime)
        src.start(startAt); this.ttsNextPlayTime = startAt + buf.duration
      } catch (e) { /* ignore */ }
    },
    base64ToUint8(b64) {
      if (!b64) return null
      try {
        const raw = window.atob(b64); const arr = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i)
        return arr
      } catch (e) { return null }
    },
    async playTtsBase64(b64) { const b = this.base64ToUint8(b64); if (b) await this.playTtsChunk(b.buffer) },

    // ─── 辅助 ────────────────────────────
    toolLabel(n) { return { get_baby_info: '宝宝信息', query_feed_milk: '查询喂奶', add_feed_milk: '记录喂奶', query_temperature: '查询体温', add_temperature: '记录体温', query_sleep: '查询睡眠', add_sleep: '记录睡眠', query_diapers: '查询尿不湿', add_diaper: '记录尿不湿', query_expense: '查询花费', add_expense: '记录花费', query_growth: '查询身高体重', add_growth: '记录成长', query_vaccines: '查询疫苗', mark_vaccine_done: '标记疫苗已接种', query_birthdays: '查询生日' }[n] || n },
    argsBrief(a) {
      if (!a) return ''
      const p = []
      if (a.milk_volume) p.push(`${a.milk_volume}ml`)
      if (a.temperature) p.push(`${a.temperature}℃`)
      if (a.day && a.day !== 'today') p.push(a.day)
      if (a.name) p.push(a.name)
      if (a.amount) p.push(`¥${a.amount}`)
      return p.join(' ') || '…'
    },
    // 确认卡参数中文展示: 字段名 → 中文标签, 值 → 友好格式
    argsDisplay(toolName, args) {
      if (!args) return ''
      const labels = {
        feed_time: '时间', milk_volume: '奶量', feed_type: '方式',
        temperature: '体温', measure_date: '日期', height: '身高', weight: '体重',
        sleep_time: '入睡时间', wake_time: '醒来时间', duration: '时长',
        stool_shape: '便便形状', status: '状态', diaper_type: '类型',
        name: '名称', amount: '金额', expense_type: '收支',
        order_time: '时间', tag: '标签',
        title: '标题', todo_id: '待办ID', title_match: '标题匹配',
        vaccine_id: '疫苗ID', actual_date: '接种日期',
        description: '备注', note: '备注'
      }
      const feedTypeMap = { bottle: '瓶喂', breast: '亲喂', formula: '奶粉' }
      const expenseTypeMap = { income: '收入', expense: '支出' }
      const lines = []
      for (const [k, v] of Object.entries(args)) {
        if (v === null || v === undefined || v === '') continue
        const label = labels[k] || k
        let val = v
        if (k === 'feed_type') val = feedTypeMap[v] || v
        if (k === 'expense_type') val = expenseTypeMap[v] || v
        // ISO 时间 → 友好显示
        if (typeof val === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(val)) {
          val = val.replace('T', ' ').replace(/:\d{2}$/, m => '')
        }
        lines.push(`<span class="ae-arg-row"><span class="ae-arg-label">${label}</span><span class="ae-arg-val">${val}</span></span>`)
      }
      return lines.join('') || '<span class="ae-arg-val">无参数</span>'
    },
    resultBrief(r) {
      if (!r) return '完成'
      try {
        const o = typeof r === 'string' ? JSON.parse(r) : r
        if (o && typeof o === 'object') {
          if ('total_volume_ml' in o) return `共 ${o.total_volume_ml}ml`
          if ('total_amount' in o) return `共 ¥${o.total_amount}`
          if ('count' in o && 'records' in o) return `${o.count} 条记录`
          return '完成'
        }
      } catch (e) { /* ignore */ }
      return String(r).slice(0, 40)
    },
    scrollToBottom() { this.$nextTick(() => { const el = this.$refs.msgList; if (el) el.scrollTop = el.scrollHeight }) },
    onCamera() { this.$refs.fileInput.click() },
    onFileChange(e) { Toast.info('图片上传开发中'); e.target.value = '' },
    onPlus() { Toast.info('更多功能开发中') }
  }
}
</script>

<style scoped>
/* ── 整体布局 ───────────────────────── */
/* 父容器 main-content 已有明确高度 (flex:1)，height:100% 生效 */
/* margin: -10px 抵消 main-content 的 padding，让页面铺满 */
.ai-entrance {
  display: flex;
  flex-direction: column;
  height: 100%;
  margin: -10px;
  background: #f7f8fa;
  overflow: hidden;
}

/* ── Header ─────────────────────────── */
.ae-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}
.ae-header-title { font-size: 17px; font-weight: 600; color: #1f2937; }
.ae-header-actions { display: flex; align-items: center; gap: 6px; }
.ae-status-dot { width: 8px; height: 8px; border-radius: 50%; }
.ae-status-dot.ok { background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.5); }
.ae-status-dot.bad { background: #ef4444; }
.ae-status-text { font-size: 12px; color: #6b7280; }

/* ── 消息区 ─────────────────────────── */
.ae-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ── 欢迎页 ─────────────────────────── */
.ae-welcome { display: flex; flex-direction: column; align-items: center; padding: 10px; margin-top: 10px; }
.ae-avatar-wrap { position: relative; width: 110px; height: 110px; margin-bottom: 18px; }
.ae-avatar {
  width: 100%; height: 100%; border-radius: 50%; overflow: hidden;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.25);
  position: relative; z-index: 2;
}
.ae-avatar-glow {
  position: absolute; top: -8px; left: -8px; right: -8px; bottom: -8px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.2) 0%, transparent 70%);
  animation: glow 3s ease-in-out infinite; z-index: 1;
}
@keyframes glow {
  0%, 100% { opacity: 0.6; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.05); }
}
.ae-welcome-text { font-size: 17px; font-weight: 600; color: #1f2937; margin-bottom: 6px; }
.ae-welcome-sub { font-size: 13px; color: #6b7280; text-align: center; line-height: 1.6; padding: 0 24px; margin-bottom: 22px; }

/* 快捷问题 */
.ae-quick-chips {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; width: 100%;
}
.ae-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.15s;
}
.ae-chip:active { transform: scale(0.97); background: #f0f0ff; border-color: #c7d2fe; }
.ae-chip-text { font-size: 13px; color: #374151; font-weight: 500; }

/* ── 消息气泡 ───────────────────────── */
.ae-msg { display: flex; gap: 8px; align-items: flex-start; }
.ae-msg.is-user { flex-direction: row-reverse; }
.ae-bubble-wrap { max-width: 85%; display: flex; flex-direction: column; gap: 4px; }
.ae-bubble {
  padding: 10px 14px; border-radius: 16px;
  font-size: 14px; line-height: 1.6; word-break: break-word; white-space: pre-wrap;
}
.ae-bubble.user {
  background: linear-gradient(135deg, #6366f1, #818cf8); color: #fff;
  border-bottom-right-radius: 4px;
}
.ae-bubble.ai {
  background: #fff; color: #1f2937;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

/* 工具调用 */
.ae-tools { display: flex; flex-direction: column; gap: 4px; margin-bottom: 6px; }
.ae-tool-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px; background: #f9fafb;
  border: 1px dashed #e5e7eb; border-radius: 8px; font-size: 12px;
}
.ae-tool-name { color: #374151; font-weight: 600; }
.ae-tool-result { color: #059669; }

/* 确认卡片 */
.ae-confirm { background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 12px; margin-bottom: 8px; }
.ae-confirm-title { font-size: 13px; font-weight: 600; color: #92400e; margin-bottom: 8px; }
.ae-confirm-item { font-size: 12px; color: #78716c; margin-bottom: 4px; }
.ae-confirm-args { display: flex; flex-direction: column; gap: 2px; margin: 4px 0; }
.ae-arg-row { display: flex; gap: 6px; align-items: baseline; }
.ae-arg-label { color: #a8a29e; font-size: 11px; min-width: 3em; }
.ae-arg-val { color: #1c1917; font-size: 12px; font-weight: 500; }
.ae-confirm-actions { display: flex; gap: 8px; margin-top: 10px; }
.ae-btn {
  flex: 1; padding: 8px 14px; border-radius: 8px;
  border: 1px solid #d1d5db; background: #fff; color: #374151; font-size: 13px; cursor: pointer;
}
.ae-btn.primary { background: #6366f1; border-color: #6366f1; color: #fff; }

/* 光标/打字 */
.ae-cursor { display: inline-block; animation: blink 0.8s infinite; color: #6366f1; font-weight: bold; }
.ae-cancelled { color: #9ca3af; font-size: 12px; margin-left: 4px; }
@keyframes blink { 50% { opacity: 0; } }
.ae-typing-indicator { display: flex; gap: 4px; padding: 4px 0; }
.ae-typing-indicator span {
  width: 6px; height: 6px; background: #9ca3af; border-radius: 50%;
  animation: typing 1.4s infinite;
}
.ae-typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.ae-typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* ── 底部输入区 - 豆包风格 ──────────── */
.ae-composer {
  flex-shrink: 0;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  background: #fff;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

/* 整个输入区是一个圆角白色卡片条框 */
.ae-input-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  background: #f4f5f7;
  border-radius: 24px;
}

/* 圆形图标按钮 */
.ab-icon-btn {
  width: 36px; height: 36px; flex-shrink: 0;
  border: none; background: transparent; color: #606266;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; border-radius: 50%;
  padding: 0;
}
.ab-icon-btn:active { background: rgba(0, 0, 0, 0.06); }
.ab-icon-btn.send {
  background: #6366f1; color: #fff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4);
}
.ab-icon-btn.send:active { background: #4f46e5; }

/* 中间输入区域 */
.ab-input-area { flex: 1; min-width: 0; display: flex; align-items: center; }

/* 按住说话按钮 */
.ab-ptt-btn {
  width: 100%;
  height: 36px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  -webkit-user-select: none;
  transition: all 0.15s;
}
.ab-ptt-btn.pressing {
  background: #e0e7ff;
  border-color: #818cf8;
  transform: scale(0.98);
}
.ab-ptt-text {
  font-size: 14px;
  color: #374151;
  font-weight: 500;
}

/* 文字输入框 */
.ab-text-input {
  width: 100%; height: 36px;
  padding: 0 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  font-size: 14px;
  color: #1f2937;
  outline: none;
}
.ab-text-input::placeholder { color: #9ca3af; }

/* ── 录音浮层 ───────────────────────── */
.ae-recording-mask {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.ae-recording-card {
  background: #fff; border-radius: 20px; padding: 32px 40px;
  display: flex; flex-direction: column; align-items: center; gap: 16px; min-width: 200px;
}
.ae-recording-wave { display: flex; align-items: center; gap: 4px; height: 40px; }
.ae-recording-wave span {
  width: 4px; height: 28px;
  background: linear-gradient(180deg, #6366f1, #818cf8);
  border-radius: 2px;
  animation: recWave 0.8s ease-in-out infinite;
}
@keyframes recWave {
  0%, 100% { transform: scaleY(0.3); }
  50% { transform: scaleY(1); }
}
.ae-recording-tip { font-size: 16px; font-weight: 600; color: #1f2937; }
.ae-recording-cancel { font-size: 12px; color: #9ca3af; }
.ae-live-transcript {
  max-width: 280px;
  font-size: 18px;
  font-weight: 500;
  color: #1f2937;
  line-height: 1.5;
  text-align: center;
  min-height: 27px;
}

/* ── 隐藏文件输入 ───────────────────── */
.ae-file-input {
  position: absolute; width: 0; height: 0; opacity: 0; pointer-events: none;
}
</style>
