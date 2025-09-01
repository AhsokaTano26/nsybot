import requests
import json
import os
import re

API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
MODEL_NAME = os.getenv('MODEL_NAME')

class BaiDu:
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
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": SECRET_KEY}
        return str(requests.post(url, params=params).json().get("access_token"))

class Ollama:
    def remove_think_tags(self,text):
        """
        移除文本中 <think> 和 </think> 标签及其之间的内容
        """
        pattern = r'<think>.*?</think>'
        return re.sub(pattern, '', text, flags=re.DOTALL)

    def main(self,text, source_lang="日文", target_lang="中文", model=MODEL_NAME):
        """
        使用 Ollama 进行翻译

        参数：
        text: 要翻译的文本
        source_lang: 源语言（默认中文）
        target_lang: 目标语言（默认英文）
        model: Ollama 模型名称

        返回：翻译结果字符串
        """
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