"""aistart 聊天服务 — 迁移自 kdx-be/aistart/views.py 并完成解耦。

源实现耦合了 Django 项目内部模块, 此处已替换:
  - kdemo.settings.DASHSCOPE_API_KEY -> 目标项目 .env 的 DASHSCOPE_API_KEY
  - kdemo.memory (MemorySaver)       -> langgraph 内置 MemorySaver (线程内会话记忆)
  - utils.chatApp.obtain_app         -> 本文件内独立编图 (模型/提示词/语言与源一致)
  - utils 的 openai/alibaba_client   -> 移除 (源视图未实际使用这两个客户端)
"""
import os
from typing import Tuple

from loguru import logger


class AistartChatService:
    """懒加载 langgraph 聊天应用, 按 thread_id 维持多轮会话记忆"""

    def __init__(self):
        self._app = None

    def _obtain_app(self):
        """对齐 utils.chatApp.obtain_app(type='norm', need_mem=True)"""
        if self._app is not None:
            return self._app
        try:
            from typing import Sequence

            from typing_extensions import Annotated, TypedDict

            from langchain_core.messages import BaseMessage
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            from langchain_openai import ChatOpenAI
            from langgraph.checkpoint.memory import MemorySaver
            from langgraph.graph import START, StateGraph
            from langgraph.graph.message import add_messages
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError('缺少依赖 langchain_openai，无法使用 AI 功能') from e

        # 模型与源实现一致为 qwen3.7-plus; 但该模型在当前 DASHSCOPE key 下免费额度
        # 已耗尽 (403 AllocationQuota.FreeTierOnly), 故支持环境变量覆盖:
        #   AISTART_MODEL > ASSISTANT_MODEL (目标项目既有约定, .env 中为 qwen-plus) > 源默认
        model_name = os.getenv("AISTART_MODEL") or os.getenv("ASSISTANT_MODEL") or "qwen3.7-plus"
        model = ChatOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY") or "",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model=model_name,
        )

        prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful assistant. Answer all questions to the best of your ability in {language}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        class State(TypedDict):
            messages: Annotated[Sequence[BaseMessage], add_messages]
            language: str

        def call_model(state: State):
            prompt = prompt_template.invoke(state)
            response = model.invoke(prompt)
            return {"messages": [response]}

        workflow = StateGraph(state_schema=State)
        workflow.add_edge(START, "model")
        workflow.add_node("model", call_model)
        self._app = workflow.compile(checkpointer=MemorySaver())
        return self._app

    def ask(self, content: str, thread_id: str) -> Tuple[str, str]:
        """对话并返回 (回复内容, thread_id); language 固定 chinese, 与源实现一致"""
        app = self._obtain_app()
        language = "chinese"
        config = {"configurable": {"thread_id": thread_id}}
        output = app.invoke(
            {"messages": [{"role": "user", "content": content}], "language": language},
            config,
        )
        msg = output["messages"][-1].content
        logger.info(f"aistart ask 完成 thread_id={thread_id}")
        return msg, thread_id
