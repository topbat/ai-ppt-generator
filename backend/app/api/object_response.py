"""对象存储代理响应：由后端直接流式输出 MinIO 对象。

预签名 URL 绑定 S3_PUBLIC_ENDPOINT（默认 localhost:9000），
局域网内其他机器访问时拿到的仍是 localhost 地址，图片/下载全部失效。
统一改为后端代理输出：浏览器只需可达 API（经前端 nginx /api 反代），
无需对外暴露 MinIO 端口，也不依赖部署机 IP。
"""
import mimetypes
from urllib.parse import quote

from fastapi.responses import Response

from app.services.storage import get_storage

# 预览图缓存 1 小时（对象键内含业务 ID，内容不变键不变，可安全缓存）
_IMAGE_CACHE = "public, max-age=3600"


def object_response(key: str, filename: str | None = None,
                    media_type: str | None = None, download: bool = False,
                    cache: bool = False) -> Response:
    data = get_storage().get_bytes(key)
    media = media_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    headers: dict[str, str] = {}
    if cache:
        headers["Cache-Control"] = _IMAGE_CACHE
    if download:
        # 下载文件名保留原名（中文按 RFC5987 百分号编码）
        name = filename or key.rsplit("/", 1)[-1]
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    return Response(content=data, media_type=media, headers=headers)
