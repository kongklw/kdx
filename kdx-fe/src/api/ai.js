import request from '@/utils/request'

/** 获取当前用户最近 N 条 AI 聊天历史 */
export function getChatHistory(limit = 50) {
  return request({
    url: '/api/v1/ai/chat-history',
    method: 'get',
    params: { limit },
    baseURL: '/prod-ai' // 走 FastAPI 代理 (非 Django 的 /dev-api)
  })
}
