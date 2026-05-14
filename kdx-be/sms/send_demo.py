# -*- coding: utf-8 -*-
import os
import sys
import json

from typing import List

from alibabacloud_dysmsapi20170525.client import Client as Dysmsapi20170525Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dysmsapi20170525 import models as dysmsapi_20170525_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient


class Sample:
    def __init__(self):
        pass

    @staticmethod
    def create_client() -> Dysmsapi20170525Client:
        """
        使用凭据初始化账号Client
        @return: Client
        @throws Exception
        """
        # 优先从环境变量获取凭据
        access_key_id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID')
        access_key_secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
        

        if access_key_id and access_key_secret:
            # 使用配置的凭据
            credential_config = CredentialConfig(
                type='access_key',
                access_key_id=access_key_id,
                access_key_secret=access_key_secret
            )
            credential = CredentialClient(config=credential_config)
        else:
            # 尝试使用默认凭据链（适用于ECS/RAM角色等场景）
            credential = CredentialClient()
        
        config = open_api_models.Config(
            credential=credential
        )
        # Endpoint 请参考 https://api.aliyun.com/product/Dysmsapi
        config.endpoint = f'dysmsapi.aliyuncs.com'
        return Dysmsapi20170525Client(config)

    @staticmethod
    def main(
            args: List[str],
    ) -> None:
        client = Sample.create_client()
        send_sms_request = dysmsapi_20170525_models.SendSmsRequest(
            sign_name='云渚科技验证平台',
            template_code='SMS_333857173',
            phone_numbers='18261663365',
            template_param='{"code":"129456","min":"5"}'
        )
        runtime = util_models.RuntimeOptions()
        try:
            resp = client.send_sms_with_options(send_sms_request, runtime)
            print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))

    @staticmethod
    async def main_async(
            args: List[str],
    ) -> None:
        client = Sample.create_client()
        send_sms_request = dysmsapi_20170525_models.SendSmsRequest(
            sign_name='云渚科技验证平台',
            template_code='SMS_333857173',
            phone_numbers='18261663365',
            template_param='{"code":"129456","min":"5"}'
        )
        runtime = util_models.RuntimeOptions()
        try:
            resp = await client.send_sms_with_options_async(send_sms_request, runtime)
            print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))


if __name__ == '__main__':
    Sample.main(sys.argv[1:])
