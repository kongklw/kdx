<template>
  <div class="ba">
    <!-- 头部 -->
    <div class="ba-header">
      <div class="ba-title">
        <span class="ba-dot" :class="isWsOpen ? 'ok' : 'bad'" />
        Baby Assistant
        <span class="ba-status">{{ isWsOpen ? '在线' : wsStatusText }}</span>
      </div>
      <van-icon name="cross" class="ba-close" @click="$emit('close')" />
    </div>

    <!-- 消息列表 -->
    <div ref="msgList" class="ba-body">
      <div v-if="messages.length === 0" class="ba-welcome">
        <div class="ba-welcome-icon">👶</div>
        <div class="ba-welcome-title">宝宝养育助手</div>
        <div class="ba-welcome-desc">我可以帮你查询和记录：喂奶、体温、睡眠、尿不湿、花费、身高体重、疫苗、生日</div>
        <div class="ba-chips">
          <span v-for="c in quickChips" :key="c" class="ba-chip" @click="onChip(c)">{{ c }}</span>
        </div>
      </div>

      <div
        v-for="(m, idx) in messages"
        :key="idx"
        :class="['ba-msg', m.role === 'user' ? 'is-user' : 'is-ai']"
      >
        <!-- 用户消息 -->
        <div v-if="m.role === 'user'" class="ba-bubble user">{{ m.text }}</div>

        <!-- AI 消息 -->
        <div v-else class="ba-ai-block">
          <!-- 意图/路由标签 -->
          <div v-if="m.intent" class="ba-meta">
            <span class="ba-tag">{{ intentLabel(m.intent) }}</span>
            <span v-if="m.confidence" class="ba-tag light">置信度 {{ m.confidence }}</span>
          </div>

          <!-- 工具调用轨迹 -->
          <div v-for="(t, ti) in m.toolEvents" :key="'t' + ti" class="ba-tool" :class="{ err: t.ok === false }">
            <span class="ba-tool-icon">{{ t.ok === false ? '⚠️' : '🔧' }}</span>
            <span class="ba-tool-name">{{ toolLabel(t.name) }}</span>
            <span class="ba-tool-result">{{ t.brief }}</span>
          </div>

          <!-- HITL 确认卡片 -->
          <div v-if="m.confirm" class="ba-confirm">
            <div class="ba-confirm-title">📋 待确认操作</div>
            <div v-for="(t, ci) in m.confirm.tools" :key="ci" class="ba-confirm-item">
              <b>{{ toolLabel(t.name) }}</b>
              <code>{{ JSON.stringify(t.args) }}</code>
            </div>
            <div class="ba-confirm-actions">
              <van-button size="small" type="primary" @click="onConfirm(m.confirm.confirm_id, 'approve')">确认写入</van-button>
              <van-button size="small" @click="onConfirm(m.confirm.confirm_id, 'reject')">取消</van-button>
            </div>
          </div>

          <!-- 回答正文 -->
          <div v-if="m.text" class="ba-bubble ai">{{ m.text }}<span v-if="m.streaming" class="ba-cursor">▍</span></div>
        </div>
      </div>

      <div v-if="loading && lastStreamingEmpty" class="ba-typing">思考中…</div>
    </div>

    <!-- 输入区 -->
    <div class="ba-composer">
      <van-field
        v-model="input"
        class="ba-input"
        type="textarea"
        autosize
        rows="1"
        maxlength="500"
        placeholder="问问宝宝的奶量、体温、睡眠…"
        @keydown.enter.exact.prevent="onSend"
      />
      <van-button
        size="small"
        type="primary"
        class="ba-send"
        :disabled="!canSend"
        @click="onSend"
      >发送</van-button>
    </div>
  </div>
</template>

<script>
import { Toast } from 'vant'
import { getToken } from '@/utils/auth'

const TOOL_LABELS = {
  get_baby_info: '宝宝信息',
  query_feed_milk: '查询喂奶',
  add_feed_milk: '记录喂奶',
  query_temperature: '查询体温',
  add_temperature: '记录体温',
  query_sleep: '查询睡眠',
  add_sleep: '记录睡眠',
  query_diapers: '查询尿不湿',
  add_diaper: '记录尿不湿',
  query_expense: '查询花费',
  add_expense: '记录花费',
  query_growth: '查询身高体重',
  add_growth: '记录成长',
  query_vaccines: '查询疫苗',
  mark_vaccine_done: '标记疫苗已接种',
  query_birthdays: '查询生日'
}

const INTENT_LABELS = {
  data_query: '📊 数据查询/记录',
  knowledge_qa: '📚 育儿知识',
  chitchat: '💬 闲聊'
}

export default {
  name: 'AssistantChat',
  props: {
    visible: { type: Boolean, default: false }
  },
  data() {
    return {
      ws: null,
      wsReadyState: 3,
      wsStatus: 'DISCONNECTED',
      messages: [],
      input: '',
      loading: false,
      // 当前正在流式输出的 AI 消息索引
      streamingIdx: -1,
      quickChips: ['今天喝了多少奶', '记录喂奶80毫升', '宝宝体温', '昨晚睡眠怎么样', '本月花了多少钱', '疫苗还有哪些没打', '最近身高体重', '宝宝多大啦'],
      reconnectTimer: null
    }
  },
  computed: {
    isWsOpen() {
      return this.wsReadyState === 1
    },
    wsStatusText() {
      return { 0: '连接中', 2: '关闭中', 3: '离线' }[this.wsReadyState] || this.wsStatus
    },
    canSend() {
      return this.isWsOpen && !this.loading && this.input.trim().length > 0
    },
    lastStreamingEmpty() {
      const m = this.messages[this.streamingIdx]
      return this.loading && (!m || !m.text && !(m.toolEvents || []).length)
    }
  },
  mounted() {
    this.connect()
  },
  beforeDestroy() {
    this.disconnect()
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
  },
  methods: {
    getDefaultWsUrl() {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = window.location.host
      if (host && !host.includes('localhost') && !host.includes('127.0.0.1')) {
        return `${scheme}://${host}/prod-ai/ws/baby_assistant`
      }
      return `${scheme}://127.0.0.1:8001/ws/baby_assistant`
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
      if (this.wsReadyState === 1 || this.wsReadyState === 0) return
      const url = this.buildWsUrl()
      let socket
      try {
        socket = new WebSocket(url)
      } catch (e) {
        this.wsReadyState = 3
        return
      }
      this.wsReadyState = socket.readyState
      socket.onopen = () => {
        this.wsReadyState = 1
        this.wsStatus = 'CONNECTED'
      }
      socket.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          this.handleEvent(payload)
        } catch (e) { /* ignore */ }
      }
      socket.onerror = () => {}
      socket.onclose = () => {
        this.wsReadyState = 3
        this.ws = null
        // 自动重连 (指数退避简化版)
        if (!this.reconnectTimer) {
          this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null
            this.connect()
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
    genRequestId() {
      return `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    },
    onChip(text) {
      this.input = text
      this.onSend()
    },
    onSend() {
      const text = this.input.trim()
      if (!text) return
      if (!this.isWsOpen) {
        Toast.fail('连接中，请稍候')
        return
      }
      if (this.loading) return
      this.messages.push({ role: 'user', text })
      this.scrollToBottom()
      this.ws.send(JSON.stringify({ type: 'query', query: text, request_id: this.genRequestId() }))
      this.input = ''
      this.loading = true
      this.streamingIdx = this.messages.length
      this.messages.push({ role: 'ai', text: '', intent: '', confidence: '', toolEvents: [], streaming: true })
      this.scrollToBottom()
    },
    onConfirm(confirmId, action) {
      if (!this.isWsOpen) return
      // 找到确认卡片消息并移除按钮
      const m = this.messages[this.streamingIdx]
      if (m && m.confirm) {
        m.confirm = null
        if (action === 'reject') {
          m.text = '已取消。'
          m.streaming = false
          this.loading = false
        }
      }
      this.ws.send(JSON.stringify({ type: 'confirm', confirm_id: confirmId, action }))
    },
    // ── WS 事件分发 ──────────────────────────
    handleEvent(p) {
      const type = p && p.type
      const data = p && p.data || {}
      if (type === 'connected' || type === 'pong') return

      if (type === 'intent_detected') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.intent = data.intent
          m.confidence = data.confidence
        }
        return
      }
      if (type === 'tool_call') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.toolEvents.push({ name: data.name, brief: this.argsBrief(data.args), ok: null })
        }
        this.scrollToBottom()
        return
      }
      if (type === 'tool_result') {
        const m = this.messages[this.streamingIdx]
        if (m && m.toolEvents.length) {
          const t = m.toolEvents[m.toolEvents.length - 1]
          t.ok = data.ok !== false
          t.brief = this.resultBrief(data.result)
        }
        return
      }
      if (type === 'confirmation_request') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.confirm = { confirm_id: data.confirm_id, tools: data.tools || [] }
        }
        this.scrollToBottom()
        return
      }
      if (type === 'retrieve_done') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.toolEvents.push({ name: 'rag_retrieve', brief: `知识库检索 ${data.count || 0} 条`, ok: true })
        }
        return
      }
      if (type === 'generate_chunk') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.text += data.chunk || ''
          this.scrollToBottom()
        }
        return
      }
      if (type === 'answer_done') {
        const m = this.messages[this.streamingIdx]
        if (m) {
          if (!m.text && data.answer) m.text = data.answer
          if (data.tool_trace && !m.toolEvents.length) {
            data.tool_trace.forEach(t => {
              m.toolEvents.push({ name: t.name, brief: t.ok ? '完成' : '失败', ok: t.ok })
            })
          }
          m.streaming = false
        }
        return
      }
      if (type === 'wait_confirm') return // confirmation_request 已处理 UI
      if (type === 'query_done') {
        this.loading = false
        const m = this.messages[this.streamingIdx]
        if (m) m.streaming = false
        return
      }
      if (type === 'query_error') {
        this.loading = false
        const m = this.messages[this.streamingIdx]
        if (m) {
          m.text = m.text || `出错了: ${data.error || '未知错误'}`
          m.streaming = false
        }
        return
      }
    },
    // ── 展示辅助 ─────────────────────────────
    toolLabel(name) {
      return TOOL_LABELS[name] || name
    },
    intentLabel(intent) {
      return INTENT_LABELS[intent] || intent
    },
    argsBrief(args) {
      if (!args) return ''
      const parts = []
      if (args.milk_volume) parts.push(`${args.milk_volume}ml`)
      if (args.temperature) parts.push(`${args.temperature}℃`)
      if (args.day && args.day !== 'today') parts.push(args.day)
      if (args.name) parts.push(args.name)
      if (args.amount) parts.push(`¥${args.amount}`)
      if (args.vaccine_key) parts.push(args.vaccine_key)
      if (args.status) parts.push(args.status)
      if (args.diaper_type) parts.push(args.diaper_type)
      if (args.height_cm) parts.push(`身高${args.height_cm}cm`)
      if (args.weight_kg) parts.push(`体重${args.weight_kg}kg`)
      return parts.join(' ') || '…'
    },
    resultBrief(result) {
      if (!result) return '完成'
      try {
        const obj = typeof result === 'string' ? JSON.parse(result) : result
        if (obj && typeof obj === 'object') {
          if ('total_volume_ml' in obj) return `共 ${obj.total_volume_ml}ml / ${obj.count} 次`
          if ('total_amount' in obj) return `共 ¥${obj.total_amount} / ${obj.count} 笔`
          if ('total_duration_minutes' in obj) return `共 ${obj.total_duration_minutes} 分钟 / ${obj.count} 次`
          if ('count' in obj && 'records' in obj) return `${obj.count} 条记录`
          if ('found' in obj) return obj.found ? obj.baby.name : '未添加宝宝信息'
          if ('milk_volume' in obj) return `已记录 ${obj.milk_volume}ml`
          if ('temperature' in obj) return `已记录 ${obj.temperature}℃`
          if ('ok' in obj && obj.ok === false && obj.message) return obj.message
          return '完成'
        }
      } catch (e) { /* not json */ }
      return String(result).slice(0, 40)
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.msgList
        if (el) el.scrollTop = el.scrollHeight
      })
    }
  }
}
</script>

<style scoped>
.ba {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}
.ba-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  background: #fff;
  border-bottom: 1px solid #eef0f5;
}
.ba-title {
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ba-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.ba-dot.ok { background: #10b981; }
.ba-dot.bad { background: #ef4444; }
.ba-status { font-size: 12px; color: #9ca3af; font-weight: 400; }
.ba-close { font-size: 20px; color: #999; }
.ba-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ba-welcome {
  text-align: center;
  padding: 30px 16px;
}
.ba-welcome-icon { font-size: 44px; }
.ba-welcome-title { font-size: 17px; font-weight: 600; margin-top: 8px; }
.ba-welcome-desc { font-size: 13px; color: #6b7280; margin-top: 6px; line-height: 1.6; }
.ba-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
}
.ba-chip {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  color: #374151;
}
.ba-chip:active { background: #eef2ff; }
.ba-msg { display: flex; }
.ba-msg.is-user { justify-content: flex-end; }
.ba-msg.is-ai { justify-content: flex-start; }
.ba-bubble {
  max-width: 82%;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.ba-bubble.user {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.ba-bubble.ai {
  background: #fff;
  color: #1f2937;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.ba-ai-block { max-width: 92%; display: flex; flex-direction: column; gap: 6px; }
.ba-meta { display: flex; gap: 6px; }
.ba-tag {
  font-size: 11px;
  background: #eef2ff;
  color: #6366f1;
  border-radius: 4px;
  padding: 2px 6px;
}
.ba-tag.light { background: #f3f4f6; color: #6b7280; }
.ba-tool {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #fff;
  border: 1px dashed #e5e7eb;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
  color: #6b7280;
}
.ba-tool.err { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.ba-tool-name { font-weight: 600; color: #374151; }
.ba-tool-result { color: #059669; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ba-tool.err .ba-tool-result { color: #b91c1c; }
.ba-confirm {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 10px;
}
.ba-confirm-title { font-size: 13px; font-weight: 600; color: #92400e; margin-bottom: 6px; }
.ba-confirm-item { font-size: 12px; color: #78716c; margin-bottom: 4px; }
.ba-confirm-item code {
  display: block;
  font-size: 11px;
  background: #fef3c7;
  border-radius: 4px;
  padding: 3px 6px;
  margin-top: 2px;
  word-break: break-all;
}
.ba-confirm-actions { display: flex; gap: 8px; margin-top: 8px; }
.ba-cursor { animation: blink 0.8s infinite; color: #6366f1; }
@keyframes blink { 50% { opacity: 0; } }
.ba-typing { font-size: 12px; color: #9ca3af; padding-left: 4px; }
.ba-composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  background: #fff;
  border-top: 1px solid #eef0f5;
}
.ba-input { flex: 1; min-width: 0; }
.ba-input :deep(.van-field__control) {
  background: #f7f8fa;
  border-radius: 10px;
  padding: 8px 10px;
}
.ba-send { height: 36px; }
</style>
