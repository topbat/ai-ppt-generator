"""对象存储抽象：MinIO 与阿里云 OSS 均走 S3 协议，切换只需改环境变量。

关键点：
- 内部客户端（容器网络地址）用于读写；
- 公网客户端（浏览器可达地址）仅用于生成预签名 URL，
  否则浏览器拿到 http://minio:9000 的签名地址无法访问。
"""
import io
import json
from functools import lru_cache

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.errors import PPTError
from app.core.logging import get_logger

logger = get_logger(__name__)


class S3Storage:
    def __init__(self):
        s = get_settings()
        self.bucket = s.s3_bucket
        kwargs = dict(
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._client = boto3.client("s3", endpoint_url=s.s3_endpoint, **kwargs)
        # 预签名专用客户端：签名绑定 endpoint，必须用浏览器可达地址
        self._public_client = boto3.client("s3", endpoint_url=s.s3_public_endpoint, **kwargs)
        self._expires = s.presign_expires

    # ---- 基础操作 ----
    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            logger.info("存储桶 %s 不存在，自动创建", self.bucket)
            self._client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        try:
            self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
            return key
        except (ClientError, BotoCoreError) as e:
            logger.error("对象上传失败 key=%s: %s", key, e)
            raise PPTError("E6002", f"上传失败: {key}") from e

    def put_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> str:
        with open(path, "rb") as f:
            return self.put_bytes(key, f.read(), content_type)

    def put_json(self, key: str, obj) -> str:
        return self.put_bytes(key, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def get_bytes(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except (ClientError, BotoCoreError) as e:
            logger.error("对象读取失败 key=%s: %s", key, e)
            raise PPTError("E6001", f"读取失败: {key}") from e

    def get_json(self, key: str):
        return json.loads(self.get_bytes(key).decode("utf-8"))

    def download_to(self, key: str, path: str) -> str:
        data = self.get_bytes(key)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def presign_get(self, key: str, expires: int | None = None, filename: str | None = None) -> str:
        """生成浏览器可直接访问的预签名下载地址。"""
        params = {"Bucket": self.bucket, "Key": key}
        if filename:
            # 下载文件名保留原名（中文需按 RFC5987 百分号编码，否则浏览器回退为对象键名）
            from urllib.parse import quote
            params["ResponseContentDisposition"] = \
                f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
        return self._public_client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires or self._expires
        )

    def stream(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.get_bytes(key))

    def healthy(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> S3Storage:
    return S3Storage()
