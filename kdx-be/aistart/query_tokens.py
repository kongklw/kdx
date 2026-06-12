import requests
def check_quota():
    url = "https://bailian.aliyun.com/api/quota"
    api_key = "sk-d3bee7338d164ababa70506e271ce474"
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        # 返回总Tokens、剩余Tokens、过期时间
        return {
            "total_tokens": data['totalTokens'],
            "remaining_tokens": data['remainingTokens'],
            "expiration_date": data['expirationDate']
        }
    raise Exception("获取配额信息失败")


if __name__ == '__main__':
    check_quota()