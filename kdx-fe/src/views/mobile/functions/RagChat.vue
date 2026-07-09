<template>
  <div class="mobile-rag-chat">
    <svg class="gradient-defs" width="0" height="0">
      <defs>
        <linearGradient id="globalAiGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#6366f1" />
          <stop offset="100%" stop-color="#8b5cf6" />
        </linearGradient>
        <linearGradient id="globalUserGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#10b981" />
          <stop offset="100%" stop-color="#059669" />
        </linearGradient>
      </defs>
    </svg>
    <van-nav-bar
      title="育儿知识库"
      left-text="返回"
      left-arrow
      fixed
      placeholder
      @click-left="onClickLeft"
    />

    <div ref="chatContainer" class="chat-container">
      <div class="message-list">
        <div
          v-for="(msg, index) in messages"
          :key="index"
          class="message-item"
          :class="{ 'message-mine': msg.author === 'You', 'message-ai': msg.author === 'AI' }"
        >
          <div v-if="msg.author !== 'You'" class="avatar avatar-ai">
            <img src="/机器人.jpg" alt="AI">
          </div>
          <div class="content">
            <div v-if="msg.retrievedDocs && msg.retrievedDocs.length > 0" class="retrieved-docs">
              <div class="docs-title">📚 检索到的相关文档</div>
              <div v-for="(doc, idx) in msg.retrievedDocs" :key="idx" class="doc-item">
                <div class="doc-title">{{ doc.title || doc.filename }}</div>
                <div class="doc-content" v-html="parseMarkdown(doc.content)" />
                <div v-if="doc.distance !== undefined" class="doc-distance">相似度: {{ (1 - doc.distance).toFixed(2) }}</div>
              </div>
            </div>
            <div class="text" v-html="parseMarkdown(msg.text)" />
            <div v-if="msg.isLoading" class="loading">
              <van-loading size="16" type="spinner" />
              <span>{{ msg.loadingText }}</span>
            </div>
            <div v-if="msg.sources && msg.sources.length > 0" class="sources">
              <van-tag v-for="(source, idx) in msg.sources" :key="idx" size="small" plain>
                {{ source.title || source.filename }}
              </van-tag>
            </div>
          </div>
          <div v-if="msg.author === 'You'" class="avatar avatar-user">
            <img src="/v仔兽.jpeg" alt="User">
          </div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <van-field
        v-model="newMessage"
        center
        clearable
        placeholder="询问育儿知识..."
        @keyup.enter="sendMessage"
      >
        <template #button>
          <van-button size="small" type="primary" :loading="sending" @click="sendMessage">提问</van-button>
        </template>
      </van-field>
    </div>

  </div>
</template>

<script>
import { getToken } from '@/utils/auth'

export default {
  name: 'MobileRagChat',
  data() {
    return {
      messages: [
        { author: 'AI', text: '您好！我是您的育儿知识助手。您可以问我关于宝宝喂养、疫苗接种、睡眠等方面的问题。', sources: [] }
      ],
      newMessage: '',
      sending: false,
      ws: null,
      currentAiMsgIndex: -1,
      reconnectCount: 0
    }
  },
  mounted() {
    this.connectWebSocket()
  },
  beforeDestroy() {
    this.closeWebSocket()
  },
  methods: {
    parseMarkdown(text) {
      if (!text) return ''
      let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')

      html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
      html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')
      html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>')

      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')

      const lines = html.split('\n')
      const result = []
      let inOl = false
      let inUl = false
      let currentParagraph = []

      const flushParagraph = () => {
        if (currentParagraph.length > 0) {
          result.push('<p>' + currentParagraph.join(' ') + '</p>')
          currentParagraph = []
        }
      }

      lines.forEach(line => {
        const trimmed = line.trim()

        if (/^\d+\.\s+/.test(trimmed)) {
          flushParagraph()
          if (inUl) {
            result.push('</ul>')
            inUl = false
          }
          if (!inOl) {
            result.push('<ol>')
            inOl = true
          }
          result.push('<li>' + trimmed.replace(/^\d+\.\s+/, '') + '</li>')
        } else if (/^[-*+]\s+/.test(trimmed)) {
          flushParagraph()
          if (inOl) {
            result.push('</ol>')
            inOl = false
          }
          if (!inUl) {
            result.push('<ul>')
            inUl = true
          }
          result.push('<li>' + trimmed.replace(/^[-*+]\s+/, '') + '</li>')
        } else if (trimmed === '') {
          flushParagraph()
          if (inOl) {
            result.push('</ol>')
            inOl = false
          }
          if (inUl) {
            result.push('</ul>')
            inUl = false
          }
        } else if (/^<(h[1-6]|\/[h1-6])>/.test(trimmed)) {
          flushParagraph()
          if (inOl) {
            result.push('</ol>')
            inOl = false
          }
          if (inUl) {
            result.push('</ul>')
            inUl = false
          }
          result.push(trimmed)
        } else {
          if (inOl) {
            result.push('</ol>')
            inOl = false
          }
          if (inUl) {
            result.push('</ul>')
            inUl = false
          }
          currentParagraph.push(trimmed)
        }
      })

      flushParagraph()
      if (inOl) result.push('</ol>')
      if (inUl) result.push('</ul>')

      html = result.join('\n')
      html = html.replace(/<p><\/p>/g, '')

      return html
    },

    onClickLeft() {
      this.closeWebSocket()
      this.$router.back()
    },

    connectWebSocket() {
      const token = getToken()
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/prod-ai/ws/rag_query?token=${token}`

      this.ws = new WebSocket(wsUrl)

      this.ws.onopen = () => {
        console.log('RAG WebSocket connected')
        this.reconnectCount = 0
      }

      this.ws.onmessage = (event) => {
        this.handleWebSocketMessage(event.data)
      }

      this.ws.onclose = () => {
        console.log('RAG WebSocket disconnected')
        if (this.reconnectCount < 5) {
          this.reconnectCount++
          setTimeout(() => this.connectWebSocket(), 3000)
        }
      }

      this.ws.onerror = (error) => {
        console.error('RAG WebSocket error:', error)
      }
    },

    closeWebSocket() {
      if (this.ws) {
        this.ws.close()
        this.ws = null
      }
    },

    handleWebSocketMessage(data) {
      try {
        const message = JSON.parse(data)
        const eventType = message.type
        const eventData = message.data

        switch (eventType) {
          case 'connected':
            console.log('Connected to RAG service')
            break

          case 'query_start':
            this.currentAiMsgIndex = this.messages.length
            this.messages.push({
              author: 'AI',
              text: '',
              isLoading: true,
              loadingText: '开始查询...',
              sources: []
            })
            this.scrollToBottom()
            break

          case 'retrieve_start':
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].loadingText = '正在检索知识库...'
            }
            break

          case 'retrieve_done':
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].loadingText = '检索完成，正在生成回答...'
              this.messages[this.currentAiMsgIndex].retrievedDocs = eventData.documents
            }
            this.scrollToBottom()
            break

          case 'prompt_generated':
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].loadingText = '正在生成回答...'
            }
            break

          case 'generate_chunk':
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].isLoading = false
              this.messages[this.currentAiMsgIndex].text += eventData.chunk
            }
            this.scrollToBottom()
            break

          case 'generate_done':
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].isLoading = false
              this.messages[this.currentAiMsgIndex].sources = eventData.sources
            }
            this.scrollToBottom()
            break

          case 'query_done':
            this.sending = false
            break

          case 'query_error':
            this.sending = false
            if (this.currentAiMsgIndex >= 0) {
              this.messages[this.currentAiMsgIndex].isLoading = false
              this.messages[this.currentAiMsgIndex].text = '查询失败: ' + eventData.error
            }
            this.$toast.fail('查询失败')
            break

          case 'pong':
            break

          default:
            console.log('Unknown event type:', eventType)
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    },

    sendMessage() {
      if (!this.newMessage.trim()) return
      if (this.sending) return

      this.messages.push({ author: 'You', text: this.newMessage, sources: [] })
      const content = this.newMessage
      this.newMessage = ''
      this.sending = true

      this.scrollToBottom()

      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'query',
          query: content
        }))
      } else {
        this.$toast.fail('连接未建立，请稍后重试')
        this.sending = false
      }
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.chatContainer
        if (container) {
          container.scrollTop = container.scrollHeight
        }
      })
    }
  }
}
</script>

<style lang="scss" scoped>
.gradient-defs {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
}

.mobile-rag-chat {
  background: linear-gradient(180deg, #f0f4ff 0%, #f5f7fa 50%, #f0fdf4 100%);
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.chat-container {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    padding-bottom: 80px;
}

.message-item {
    display: flex;
    margin-bottom: 20px;
    align-items: flex-start;

    &.message-mine {
        justify-content: flex-end;
        .content {
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            margin-right: 10px;
            margin-left: 0;
            border-radius: 20px 20px 6px 20px;
            color: #fff;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
            .text {
                color: #fff;
            }
            .text :deep(strong) {
                color: #fff;
            }
            .text :deep(a) {
                color: #fff;
                text-decoration: underline;
            }
            .text :deep(p) {
                color: rgba(255, 255, 255, 0.95);
            }
            .text :deep(ul), .text :deep(ol) {
                color: rgba(255, 255, 255, 0.95);
            }
            .text :deep(li) {
                color: rgba(255, 255, 255, 0.95);
            }
            .text :deep(li::marker) {
                color: rgba(255, 255, 255, 0.7);
            }
            .loading span {
                color: rgba(255, 255, 255, 0.8);
            }
        }
    }

    &.message-ai {
        justify-content: flex-start;
        .content {
            background-color: #fff;
            margin-left: 10px;
            margin-right: 0;
            border-radius: 20px 20px 20px 6px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        }
    }

    .avatar {
        width: 44px;
        height: 44px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        flex-shrink: 0;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
        border: 2px solid #fff;

        &.avatar-ai {
            background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
        }

        &.avatar-user {
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
        }

        svg {
            width: 100%;
            height: 100%;
            border-radius: 50%;
        }

        img {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
        }
    }

    .content {
        padding: 14px 18px;
        border-radius: 20px;
        max-width: 78%;
        word-break: break-word;

        .text {
            font-size: 15px;
            color: #334155;
            line-height: 1.8;

            :deep(p) {
                margin: 0 0 10px 0;
                text-align: justify;
            }

            :deep(p:last-child) {
                margin-bottom: 0;
            }

            :deep(strong) {
                font-weight: 600;
                color: #6366f1;
                background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(139, 92, 246, 0.1) 100%);
                padding: 1px 4px;
                border-radius: 4px;
            }

            :deep(ul), :deep(ol) {
                margin: 12px 0;
                padding-left: 24px;
            }

            :deep(li) {
                margin: 6px 0;
                line-height: 1.7;
                position: relative;
            }

            :deep(li::marker) {
                color: #6366f1;
                font-weight: 600;
            }

            :deep(h1), :deep(h2), :deep(h3), :deep(h4), :deep(h5), :deep(h6) {
                margin: 14px 0 10px 0;
                font-weight: 700;
                color: #1e293b;
                padding-bottom: 6px;
                border-bottom: 2px solid #e0e7ff;
            }

            :deep(h1) { font-size: 18px; }
            :deep(h2) { font-size: 16px; }
            :deep(h3) { font-size: 15px; }

            :deep(hr) {
                border: none;
                border-top: 2px dashed #e2e8f0;
                margin: 16px 0;
            }

            :deep(code) {
                background: #f1f5f9;
                padding: 3px 8px;
                border-radius: 6px;
                font-size: 14px;
                font-family: monospace;
            }

            :deep(a) {
                color: #6366f1;
                text-decoration: none;
                font-weight: 500;
            }

            :deep(a:hover) {
                text-decoration: underline;
            }
        }

        .loading {
            display: flex;
            align-items: center;
            gap: 10px;
            color: #64748b;
            font-size: 14px;
            padding: 10px 0;
        }

        .retrieved-docs {
            margin-top: 16px;
            padding-top: 14px;
            border-top: 1px dashed #e2e8f0;

            .docs-title {
                font-size: 13px;
                color: #64748b;
                margin-bottom: 12px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 8px;
                background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%);
                padding: 6px 10px;
                border-radius: 8px;
                display: inline-flex;
            }

            .doc-item {
                background: linear-gradient(135deg, #f8fafc 0%, #f0fdf4 100%);
                border-radius: 12px;
                padding: 12px 14px;
                margin-bottom: 10px;
                font-size: 13px;
                border: 1px solid #e2e8f0;
                transition: all 0.2s ease;

                &:hover {
                    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
                    border-color: #d1d5db;
                }

                .doc-title {
                    color: #1e293b;
                    font-weight: 600;
                    margin-bottom: 6px;
                    font-size: 14px;
                }

                .doc-content {
                    color: #64748b;
                    margin-bottom: 6px;
                    max-height: 100px;
                    overflow: hidden;
                    line-height: 1.6;
                    font-size: 13px;

                    :deep(p) {
                        margin: 0 0 4px 0;
                    }

                    :deep(strong) {
                        font-weight: 600;
                        color: #6366f1;
                    }

                    :deep(ul), :deep(ol) {
                        margin: 4px 0;
                        padding-left: 16px;
                    }

                    :deep(li) {
                        margin: 2px 0;
                    }

                    :deep(li::marker) {
                        color: #6366f1;
                        font-size: 12px;
                    }
                }

                .doc-distance {
                    color: #94a3b8;
                    font-size: 12px;
                }
            }
        }

        .sources {
            margin-top: 12px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
    }
}

.input-area {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border-top: 1px solid rgba(226, 232, 240, 0.8);
    padding: 10px 16px 20px;
    z-index: 100;
    box-shadow: 0 -4px 20px rgba(0,0,0,0.06);
}
</style>
