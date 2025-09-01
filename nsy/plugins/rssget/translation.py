import requests
import json
import os

API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')

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