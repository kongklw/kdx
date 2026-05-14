# -*- coding: utf-8 -*-
# This file is auto-generated, don't edit it. Thanks.
import os
import sys

from typing import List

from alibabacloud_dysmsapi20170525.client import Client as Dysmsapi20170525Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dysmsapi20170525 import models as dysmsapi_20170525_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient


def create_client(
        access_key_id: str,
        access_key_secret: str,
) -> Dysmsapi20170525Client:
    """
    使用AK&SK初始化账号Client
    @param access_key_id:
    @param access_key_secret:
    @return: Client
    @throws Exception
    """
    config = open_api_models.Config(
        # 必填，您的 AccessKey ID,
        access_key_id=access_key_id,
        # 必填，您的 AccessKey Secret,
        access_key_secret=access_key_secret
    )
    # 访问的域名
    config.endpoint = f'dysmsapi.aliyuncs.com'
    return Dysmsapi20170525Client(config)


def main(
        args: List[str],
) -> None:
    # 请确保代码运行环境设置了环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID 和 ALIBABA_CLOUD_ACCESS_KEY_SECRET。
    # 工程代码泄露可能会导致 AccessKey 泄露，并威胁账号下所有资源的安全。
    # 以下代码示例使用环境变量获取 AccessKey 的方式进行调用，仅供参考，建议使用更安全的 STS 方式。
    # 更多鉴权访问方式请参见：https://help.aliyun.com/document_detail/378657.html
    client = create_client(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'], os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])

    send_sms_request = dysmsapi_20170525_models.SendSmsRequest(
        phone_numbers='18310353760',
        sign_name='阿里云短信测试',
        template_code='SMS_154950909',
        template_param='{"code":"1234"}'
    )

    '''
    {
  "PhoneNumbers": "18310353760",
  "SignName": "阿里云短信测试",
  "TemplateCode": "SMS_154950909",
  "TemplateParam": "{\"code\":\"1234\"}",
  "SourceIp": "61.149.15.18"
}
    
    '''
    runtime = util_models.RuntimeOptions()
    try:
        # 复制代码运行请自行打印 API 的返回值
        ans = client.send_sms_with_options(send_sms_request, runtime)
        print(ans)
    except Exception as error:
        # 如有需要，请打印 error
        print(f'send error: {error}')
        UtilClient.assert_as_string(error.message)


async def main_async(
        args: List[str],
) -> None:
    # 请确保代码运行环境设置了环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID 和 ALIBABA_CLOUD_ACCESS_KEY_SECRET。
    client = create_client(os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'], os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'])
    send_sms_request = dysmsapi_20170525_models.SendSmsRequest(
        phone_numbers='1520000****',
        sign_name='阿里云短信测试',
        template_code='SMS_15495****',
        template_param='{"code":"1234"}'
    )
    runtime = util_models.RuntimeOptions()
    try:
        # 复制代码运行请自行打印 API 的返回值
        await client.send_sms_with_options_async(send_sms_request, runtime)
    except Exception as error:
        # 如有需要，请打印 error
        UtilClient.assert_as_string(error.message)


if __name__ == '__main__':
    main(sys.argv[1:])
