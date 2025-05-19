from bs4 import BeautifulSoup

async def if_trans(entry):
    description = entry.get("description", "")

    # 使用 BeautifulSoup 解析 HTML
    soup = BeautifulSoup(description, "html.parser")

    # 检测是否存在 class="rsshub-quote" 的 div
    quote_div = soup.find("div", class_="rsshub-quote")

    # 判断结果
    if quote_div:
        return False
    else:
        return True