import hashlib
import hmac
import json
import os
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote_plus, urlencode

import pytz
import requests


class SignatureRequest:
    def __init__(
            self,
            http_method: str,
            canonical_uri: str,
            host: str,
            x_acs_action: str,
            x_acs_version: str
    ):
        self.http_method = http_method
        self.canonical_uri = canonical_uri
        self.host = host
        self.x_acs_action = x_acs_action
        self.x_acs_version = x_acs_version
        self.headers = self._init_headers()
        self.query_param = OrderedDict()  # type: Dict[str, Any]
        self.body = None  # type: Optional[bytes]

    def _init_headers(self) -> Dict[str, str]:
        current_time = datetime.now(pytz.timezone('Etc/GMT'))
        headers = OrderedDict([
            ('host', self.host),
            ('x-acs-action', self.x_acs_action),
            ('x-acs-version', self.x_acs_version),
            ('x-acs-date', current_time.strftime('%Y-%m-%dT%H:%M:%SZ')),
            ('x-acs-signature-nonce', str(uuid.uuid4())),
        ])
        return headers

    def sorted_query_params(self) -> None:
        """对查询参数按名称排序并返回编码后的字符串"""
        self.query_param = dict(sorted(self.query_param.items()))

    def sorted_headers(self) -> None:
        """对请求头按名称排序并返回编码后的字符串"""
        self.headers = dict(sorted(self.headers.items()))


def get_authorization(request: SignatureRequest) -> None:
    try:
        new_query_param = OrderedDict()
        process_object(new_query_param, '', request.query_param)
        request.query_param.clear()
        request.query_param.update(new_query_param)
        request.sorted_query_params()

        # 步骤 1：拼接规范请求串
        canonical_query_string = "&".join(
            f"{percent_code(quote_plus(k))}={percent_code(quote_plus(str(v)))}"
            for k, v in request.query_param.items()
        )
        hashed_request_payload = sha256_hex(request.body or b'')
        request.headers['x-acs-content-sha256'] = hashed_request_payload

        if SECURITY_TOKEN:
            signature_request.headers["x-acs-security-token"] = SECURITY_TOKEN
        request.sorted_headers()

        filtered_headers = OrderedDict()
        for k, v in request.headers.items():
            if k.lower().startswith("x-acs-") or k.lower() in ["host", "content-type"]:
                filtered_headers[k.lower()] = v

        canonical_headers = "\n".join(f"{k}:{v}" for k, v in filtered_headers.items()) + "\n"
        signed_headers = ";".join(filtered_headers.keys())

        canonical_request = (
            f"{request.http_method}\n{request.canonical_uri}\n{canonical_query_string}\n"
            f"{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"
        )
        print(canonical_request)

        # 步骤 2：拼接待签名字符串
        hashed_canonical_request = sha256_hex(canonical_request.encode("utf-8"))
        string_to_sign = f"{ALGORITHM}\n{hashed_canonical_request}"
        print(string_to_sign)

        # 步骤 3：计算签名
        signature = hmac256(ACCESS_KEY_SECRET.encode("utf-8"), string_to_sign).hex().lower()

        # 步骤 4：拼接Authorization
        authorization = f'{ALGORITHM} Credential={ACCESS_KEY_ID},SignedHeaders={signed_headers},Signature={signature}'
        request.headers["Authorization"] = authorization
    except Exception as e:
        print("Failed to get authorization")
        print(e)


def form_data_to_string(form_data: Dict[str, Any]) -> str:
    tile_map = OrderedDict()
    process_object(tile_map, "", form_data)
    return urlencode(tile_map)


def process_object(result_map: Dict[str, str], key: str, value: Any) -> None:
    if value is None:
        return

    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            process_object(result_map, f"{key}.{i + 1}", item)
    elif isinstance(value, dict):
        for sub_key, sub_value in value.items():
            process_object(result_map, f"{key}.{sub_key}", sub_value)
    else:
        key = key.lstrip(".")
        result_map[key] = value.decode("utf-8") if isinstance(value, bytes) else str(value)


def hmac256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sha256_hex(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()


def call_api(request: SignatureRequest) -> None:
    url = f"https://{request.host}{request.canonical_uri}"
    if request.query_param:
        url += "?" + urlencode(request.query_param, doseq=True, safe="*")

    headers = dict(request.headers)
    data = request.body

    try:
        response = requests.request(
            method=request.http_method, url=url, headers=headers, data=data
        )
        response.raise_for_status()
        print(response.text)
    except requests.RequestException as e:
        print("Failed to send request")
        print(e)


def percent_code(encoded_str: str) -> str:
    return encoded_str.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


# 环境变量中获取Access Key ID和Access Key Secret
ACCESS_KEY_ID = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
ACCESS_KEY_SECRET = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
SECURITY_TOKEN = os.environ.get("ALIBABA_CLOUD_SECURITY_TOKEN")

ALGORITHM = "ACS3-HMAC-SHA256"

"""
签名示例，您在测试时可根据实际情况选择main函数中的示例并修改示例值，例如调用SendSms选择示例一即可，然后修改http_method、host、x_acs_action、x_acs_version以及query_param。
ROA和RPC只有canonicalUri取值逻辑是不同的。

通过OpenAPI元数据获取请求方法（methods）、请求参数名称（name）、请求参数类型（type）、请求参数位置（in），并将参数封装到SignatureRequest中。
1. 请求参数在元数据中显示"in":"query"，通过queryParam传参，无需设置content-type。注：RPC接口该类型参数也支持通过body传参，content-type为application/x-www-form-urlencoded，参见示例三。
2. 请求参数在元数据中显示"in": "body"，通过body传参，根据实际情况设置content-type。注：RPC接口不建议使用application/json，可使用示例三替代。
3. 请求参数在元数据中显示"in": "formData"，通过body传参，content-type为application/x-www-form-urlencoded。
"""
if __name__ == "__main__":
    # RPC接口请求示例一：请求参数"in":"query"
    http_method = "POST"  # 请求方式，从元数据中可以获取，建议使用POST。
    canonical_uri = "/"  # RPC接口无资源路径，故使用正斜杠（/）作为CanonicalURI
    host = "ecs.cn-hangzhou.aliyuncs.com"  # 云产品服务接入点
    x_acs_action = "DescribeInstanceStatus"  # API名称
    x_acs_version = "2014-05-26"  # API版本号
    signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)
    # DescribeInstanceStatus请求参数如下：
    # RegionId在元数据中显示的类型是String，"in":"query"，必填
    signature_request.query_param['RegionId'] = 'cn-hangzhou'
    # InstanceId的在元数据中显示的类型是array，"in":"query"，非必填
    signature_request.query_param['InstanceId'] = ["i-bp10igfmnyttXXXXXXXX", "i-bp1incuofvzxXXXXXXXX",
                                                   "i-bp1incuofvzxXXXXXXXX"]

    # # RPC接口请求示例二：请求参数"in":"body"（上传文件场景）
    # http_method = "POST"
    # canonical_uri = "/"
    # host = "ocr-api.cn-hangzhou.aliyuncs.com"
    # x_acs_action = "RecognizeGeneral"
    # x_acs_version = "2021-07-07"
    # signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)
    # # 请求参数在元数据中显示"in": "body"，通过body传参。
    # file_path = "D:\\test.png"
    # with open(file_path, 'rb') as file:
    #     # 读取图片内容为字节数组
    #     signature_request.body = file.read()
    #     signature_request.headers["content-type"] = "application/octet-stream"

    # # RPC接口请求示例三：请求参数"in": "formData"或"in":"body"（非上传文件场景）
    # http_method = "POST"
    # canonical_uri = "/"
    # host = "mt.aliyuncs.com"
    # x_acs_action = "TranslateGeneral"
    # x_acs_version = "2018-10-12"
    # signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)
    # # TranslateGeneral请求参数如下：
    # # Context在元数据中显示的类型是String，"in":"query"，非必填
    # signature_request.query_param['Context'] = '早上'
    # # FormatType、SourceLanguage、TargetLanguage等参数，在元数据中显示"in":"formData"
    # form_data = OrderedDict()
    # form_data["FormatType"] = "text"
    # form_data["SourceLanguage"] = "zh"
    # form_data["TargetLanguage"] = "en"
    # form_data["SourceText"] = "你好"
    # form_data["Scene"] = "general"
    # signature_request.body = bytes(form_data_to_string(form_data), 'utf-8')
    # signature_request.headers["content-type"] = "application/x-www-form-urlencoded"

    # # 示例四：ROA接口POST请求
    # http_method = "POST"
    # canonical_uri = "/clusters"
    # host = "cs.cn-beijing.aliyuncs.com"
    # x_acs_action = "CreateCluster"
    # x_acs_version = "2015-12-15"
    # signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)
    # 请求参数在元数据中显示"in":"body"，通过body传参。
    # body = OrderedDict()
    # body["name"] = "testDemo"
    # body["region_id"] = "cn-beijing"
    # body["cluster_type"] = "ExternalKubernetes"
    # body["vpcid"] = "vpc-2zeou1uod4ylaXXXXXXXX"
    # body["container_cidr"] = "172.16.1.0/20"
    # body["service_cidr"] = "10.2.0.0/24"
    # body["security_group_id"] = "sg-2ze1a0rlgeo7XXXXXXXX"
    # body["vswitch_ids"] = ["vsw-2zei30dhfldu8XXXXXXXX"]
    # signature_request.body = bytes(json.dumps(body, separators=(',', ':')), 'utf-8')
    # signature_request.headers["content-type"] = "application/json; charset=utf-8"

    # # 示例五：ROA接口GET请求
    # http_method = "GET"
    # # canonicalUri如果存在path参数，需要对path参数encode，percent_code({path参数})
    # cluster_id_encode = percent_code("ca72cfced86db497cab79aa28XXXXXXXX")
    # canonical_uri = f"/clusters/{cluster_id_encode}/resources"
    # host = "cs.cn-beijing.aliyuncs.com"
    # x_acs_action = "DescribeClusterResources"
    # x_acs_version = "2015-12-15"
    # signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)
    # signature_request.query_param['with_addon_resources'] = True

    # # 示例六：ROA接口DELETE请求
    # http_method = "DELETE"
    # # canonicalUri如果存在path参数，需要对path参数encode，percent_code({path参数})
    # cluster_id_encode = percent_code("ca72cfced86db497cab79aa28XXXXXXXX")
    # canonical_uri = f"/clusters/{cluster_id_encode}"
    # host = "cs.cn-beijing.aliyuncs.com"
    # x_acs_action = "DeleteCluster"
    # x_acs_version = "2015-12-15"
    # signature_request = SignatureRequest(http_method, canonical_uri, host, x_acs_action, x_acs_version)

    get_authorization(signature_request)
    call_api(signature_request)
