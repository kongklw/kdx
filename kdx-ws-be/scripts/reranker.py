import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_URL = "https://ai.gitee.com/v1/rerank"
api_key = os.getenv("moli_api_key")
headers = {
	"X-Failover-Enabled": "true",
	"Authorization": f"Bearer {api_key}" # 使用 Bearer 令牌进行身份验证
}

def query(payload):
	response = requests.post(API_URL, headers=headers, json=payload)
	return response.json()

output = query({
	# 用户查询的问题
	"query": "How to read a CSV file in Python?",
	# 待排序的文档列表
	"documents": [
		"Use pandas: `import pandas as pd; df = pd.read_csv('data.csv')`",
		"You can read CSV files with numpy.loadtxt()",
		"To write JSON files, use json.dump() in Python",
		"CSV means Comma Separated Values. Python files can be opened using read() method."
	],
	"model": "Qwen3-Reranker-8B" # 指定使用的模型
})
print(output)