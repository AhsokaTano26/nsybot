from bs4 import BeautifulSoup
from nonebot.log import logger

async def if_trans(entry):
    description = entry.get("description", "")

    # 使用 BeautifulSoup 解析 HTML
    soup = BeautifulSoup(description, "html.parser")

    # 检测是否存在 class="rsshub-quote" 的 div
    quote_div = soup.find("div", class_="rsshub-quote")

    # 判断结果
    if quote_div:
        logger.info("该推文为引用推文")
        return True
    else:
        return False

async def if_self_trans(username,entry):
    flag = "RT " + username
    target = entry.title
    flag = target.startswith(flag)
    if flag:
        logger.info("该推文为自我转发推文")
        return True
    else:
        return False


async def remove_html_tag_soup(html):
    """
    使用BeautifulSoup移除 div 标签及其内容

    参数:
        html (str): HTML字符串

    返回:
        str: 清理后的HTML字符串
    """
    soup = BeautifulSoup(html, 'html.parser')

    # 找到所有目标标签并移除
    for tag in soup.find_all('div', class_='rsshub-quote'):
        tag.decompose()  # 彻底移除标签及其内容

    return str(soup)