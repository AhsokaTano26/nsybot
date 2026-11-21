"""Bound decoded response bytes before RSS parsing, including compressed streams."""

import zlib
from xml.parsers import expat


class FeedResourceError(ValueError):
    pass


class FeedSyntaxError(FeedResourceError):
    """Invalid source data can be transient; retain the usual retry policy."""


def check_feed_structure(content):
    """先用无 DOM 的扫描约束条目数/节点/深度，避免小文件产生海量对象。"""
    parser = expat.ParserCreate(namespace_separator="}")
    depth = elements = entries = 0

    def start(name, attrs):
        nonlocal depth, elements, entries
        depth += 1
        elements += 1
        if name.rsplit("}", 1)[-1].lower() in {"item", "entry"}:
            entries += 1
        if depth > 64 or elements > 20000 or entries > 500:
            raise FeedResourceError("FeedStructureTooLarge")

    def end(name):
        nonlocal depth
        depth -= 1

    def doctype(*args):
        raise FeedSyntaxError("UnsupportedFeedDoctype")

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.StartDoctypeDeclHandler = doctype
    try:
        parser.Parse(content, True)
    except expat.ExpatError as exc:
        # 格式错误后的剩余正文无法可靠计数，不能绕过结构预算交给宽松解析器。
        raise FeedSyntaxError("MalformedFeed") from exc


async def read_feed_body(response, limit, *, prefix=False):
    """Read at most limit decoded bytes; prefix mode is only for HTTP error diagnostics."""
    if response.is_stream_consumed:
        data = response.content
        if len(data) > limit and not prefix:
            raise FeedResourceError("FeedTooLarge")
        return data[:limit]
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"", "identity", "gzip", "deflate"}:
        raise FeedSyntaxError("UnsupportedEncoding")
    content_length = response.headers.get("Content-Length", "")
    if encoding in {"", "identity"} and content_length.isdigit() and int(content_length) > limit and not prefix:
        raise FeedResourceError("FeedTooLarge")
    decoder = None
    if encoding == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    output = bytearray()
    # deflate 在实际 HTTP 服务中可能省略 zlib 头；等两个字节再决定，
    # 仍使用 max_length 限制解压输出，不进行无界的试解压。
    deflate_header = bytearray() if encoding == "deflate" else None
    try:
        async for chunk in response.aiter_raw():
            if deflate_header is not None:
                needed = max(0, 2 - len(deflate_header))
                deflate_header.extend(chunk[:needed])
                chunk = chunk[needed:]
                if len(deflate_header) < 2:
                    continue
                cmf, flags = deflate_header
                zlib_header = cmf & 15 == 8 and cmf >> 4 <= 7 and (cmf * 256 + flags) % 31 == 0
                decoder = zlib.decompressobj(zlib.MAX_WBITS if zlib_header else -zlib.MAX_WBITS)
                chunk = bytes(deflate_header) + chunk
                deflate_header = None
            remaining = limit - len(output)
            decoded = decoder.decompress(chunk, remaining + 1) if decoder else chunk
            if len(decoded) > remaining:
                if prefix:
                    output.extend(decoded[:remaining])
                    return bytes(output)
                raise FeedResourceError("FeedTooLarge")
            output.extend(decoded)
        if decoder is not None and (not decoder.eof or decoder.unused_data):
            raise FeedSyntaxError("InvalidCompressedFeed")
    except zlib.error as exc:
        raise FeedSyntaxError("InvalidCompressedFeed") from exc
    return bytes(output)
