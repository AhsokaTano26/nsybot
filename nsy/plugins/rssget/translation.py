import requests
import json
import re
from openai import OpenAI
from nonebot import get_plugin_config

from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from .config import Config


def _get_config():
    """获取插件配置"""
    return get_plugin_config(Config)


class BaiDu:
    """
    调用百度机器翻译API进行翻译操作
    """
    def main(self, body=str):
        url = "https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1?access_token=" + self.get_access_token()

        payload = json.dumps({
            "from": "auto",
            "to": "zh",
            "q": f"{body}"
        }, ensure_ascii=False)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))

        json_result = response.text
        result = json.loads(json_result)

        # 提取单个 dst
        first_translation = result["result"]["trans_result"][0]["dst"]

        return first_translation


    def get_access_token(self):
        """
        使用 AK，SK 生成鉴权签名（Access Token）
        :return: access_token，或是None(如果错误)
        """
        config = _get_config()
        API_KEY = config.api_key
        SECRET_KEY = config.secret_key

        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": SECRET_KEY}
        return str(requests.post(url, params=params).json().get("access_token"))



class Ali:
    """
    调用阿里翻译
    """
    def __init__(self):
        pass

    @staticmethod
    def create_client() -> OpenApiClient:
        """
        使用凭据初始化账号Client
        @return: Client
        @throws Exception
        """
        plugin_config = _get_config()
        API_KEY = plugin_config.api_key
        SECRET_KEY = plugin_config.secret_key


        credential = CredentialClient()
        config = open_api_models.Config(
            credential=credential,
            access_key_id=API_KEY,
            access_key_secret=SECRET_KEY
        )
        # Endpoint 请参考 https://api.aliyun.com/product/alimt
        config.endpoint = f'mt.cn-hangzhou.aliyuncs.com'
        return OpenApiClient(config)

    @staticmethod
    def create_api_info() -> open_api_models.Params:
        """
        API 相关
        @param path: string Path parameters
        @return: OpenApi.Params
        """
        params = open_api_models.Params(
            # 接口名称,
            action='TranslateGeneral',
            # 接口版本,
            version='2018-10-12',
            # 接口协议,
            protocol='HTTPS',
            # 接口 HTTP 方法,
            method='POST',
            auth_type='AK',
            style='RPC',
            # 接口 PATH,
            pathname=f'/',
            # 接口请求体内容格式,
            req_body_type='formData',
            # 接口响应体内容格式,
            body_type='json'
        )
        return params

    @staticmethod
    def main(text: str):
        """
        同步调用
        """
        client = Ali.create_client()
        params = Ali.create_api_info()
        # body params
        body = {}
        body['FormatType'] = 'text'
        body['SourceLanguage'] = 'auto'
        body['TargetLanguage'] = 'zh'
        body['SourceText'] = text
        body['Scene'] = 'general'
        # runtime options
        runtime = util_models.RuntimeOptions()
        request = open_api_models.OpenApiRequest(
            body=body
        )
        # 返回值实际为 Map 类型，可从 Map 中获得三类数据：响应体 body、响应头 headers、HTTP 返回的状态码 statusCode。
        response = client.call_api(params, request, runtime)
        return response['body']['Data']['Translated']

    @staticmethod
    async def main_async(text: str):
        """
        异步调用
        """
        client = Ali.create_client()
        params = Ali.create_api_info()
        # body params
        body = {}
        body['FormatType'] = 'text'
        body['SourceLanguage'] = 'auto'
        body['TargetLanguage'] = 'zh'
        body['SourceText'] = text
        body['Scene'] = 'general'
        # runtime options
        runtime = util_models.RuntimeOptions()
        request = open_api_models.OpenApiRequest(
            body=body
        )
        # 返回值实际为 Map 类型，可从 Map 中获得三类数据：响应体 body、响应头 headers、HTTP 返回的状态码 statusCode。
        response = await client.call_api_async(params, request, runtime)
        return response['body']['Data']['Translated']


class DeepSeek:
    def main(self, text):
        config = _get_config()
        client = OpenAI(
            api_key=config.api_key,
            base_url="https://api.deepseek.com"
        )
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": f"你是一名专业的翻译助手，请将用户输入的内容准确翻译成中文，不要添加任何额外解释。"
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            stream=False
        )
        translated_text = response.choices[0].message.content
        return translated_text



class Ollama:
    """
    调用本地部署ollama进行翻译
    """
    def remove_think_tags(self, text):
        """
        移除文本中 <think> 和 </think> 标签及其之间的内容
        """
        pattern = r'<think>.*?</think>'
        return re.sub(pattern, '', text, flags=re.DOTALL)

    def main(self, text, source_lang="日文", target_lang="中文"):
        """
        使用 Ollama 进行翻译

        参数：
        text: 要翻译的文本
        source_lang: 源语言（默认中文）
        target_lang: 目标语言（默认英文）
        model: Ollama 模型名称

        返回：翻译结果字符串
        """
        config = _get_config()
        model = config.model_name
        url = "http://192.168.1.189:11434/api/generate"
        prompt = f"将以下{source_lang}内容翻译成{target_lang}，只返回翻译结果：\n{text}"

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "1s"
        }

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            a = response.json()["response"].strip()
            return self.remove_think_tags(a)
        except Exception as e:
            print(f"翻译出错: {e}")
            return "翻译失败"
