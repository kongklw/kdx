import os

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from text2vec import SentenceModel


# 初始化模型（首次运行时会自动从 HuggingFace 下载模型权重）
# 模型名称 'shibing624/text2vec-base-chinese' 是官方推荐的标识
# model = SentenceModel('shibing624/text2vec-base-chinese')
model = None

for i in range(3):
    # # 全局单例，只初始化一次


    def get_model():
        global model
        if model is None:
            model = SentenceModel('shibing624/text2vec-base-chinese')
        return model

    get_model()

    # # 使用
    # embeddings = get_model().encode(sentences)

    # 准备待处理的中文句子
    sentences = [
        '如何更换支付宝绑定的银行卡',
        '支付宝修改绑定银行卡的操作步骤',
        '今天的天气真的很不错'
    ]

    # 生成文本向量 (Embeddings)
    embeddings = model.encode(sentences)

    print(f"向量 : {embeddings}")
    # 输出向量形状，通常为 (句子数量, 768)
    print(f"向量维度: {embeddings.shape}")
