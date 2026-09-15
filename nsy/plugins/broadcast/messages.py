from dataclasses import dataclass

from nsy.qq_utils import quote_block


@dataclass(frozen=True)
class BroadcastMessage:
    """一条可复用的定时推送内容。"""

    key: str                      # 业务代号，与群注册表一致
    title: str                    # Markdown 标题
    hours: tuple[int, ...]        # 每日推送的整点时刻
    body: str                     # Markdown 正文，逐行渲染为引用行
    images: tuple[str, ...] = ()  # 图片地址，逐张作为独立图片消息发送

    def render(self) -> str:
        """渲染为 QQ Markdown：标题 + 引用块正文。"""
        return f"# {self.title}\n\n{quote_block(self.body)}"


CQU_EF = BroadcastMessage(
    key="CQU_EF",
    title="🧥 EF邦多利马群法批定制 · 第二弹",
    hours=(12, 18),
    body=(
        "各位老师，EF邦多利马群法批好评如潮第二弹开始了。"
        "如有需求，请填写表格，定制信息空白，默认原版，同时请填写尺码。\n"
        "【腾讯文档】[法批定制]"
        "(https://docs.qq.com/sheet/DVVJTZnNZdmFIcHh5?tab=BB08J2)"
    ),
    images=(
        "https://img.tano.asia/i/47b932ae-cc92-4ca8-8f9b-a462846b6f27.png",
        "https://img.tano.asia/i/d03d97db-ebf6-43b4-be80-77afff7057e0.png",
    ),
)

MESSAGES: dict[str, BroadcastMessage] = {CQU_EF.key: CQU_EF}
