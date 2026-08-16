"""文档转换服务：PPTX → PDF → PNG（预览链路）。

策略（对应 Fallback Matrix）：
- 首选 unoserver 远程转换（soffice 容器常驻，免冷启动）；
- 备选本机 soffice 命令行；
- 全部失败仅降级预览（E6003 Warning），绝不影响 PPTX 交付。
"""
import os
import subprocess
import tempfile

import fitz  # PyMuPDF
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def pptx_to_pdf(pptx_path: str, out_dir: str) -> str | None:
    """转换失败返回 None（调用方按预览降级处理），不抛异常。"""
    s = get_settings()
    pdf_path = os.path.join(out_dir, os.path.splitext(os.path.basename(pptx_path))[0] + ".pdf")

    if s.convert_backend == "none":
        logger.info("转换后端已禁用(convert_backend=none)，跳过 PDF 生成")
        return None

    # 首选：unoserver 远程转换
    if s.convert_backend == "unoserver":
        try:
            cmd = ["unoconvert", "--host-location", "remote",
                   "--host", s.unoserver_host, "--port", str(s.unoserver_port),
                   "--convert-to", "pdf", pptx_path, pdf_path]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            logger.info("unoserver 转换 PDF 成功: %s", pdf_path)
            return pdf_path
        except Exception as e:
            logger.warning("unoserver 转换失败，尝试本机 soffice 兜底: %s", e)

    # 兜底：本机 soffice
    # 关键：每次转换用独立 UserInstallation 配置目录——soffice 的用户配置有全局锁，
    # 并发调用共用默认配置会随机立即失败（缩略图/预览转换偶发失败的根因）
    profile_dir = tempfile.mkdtemp(prefix="loprofile_")
    try:
        from pathlib import Path
        cmd = [s.soffice_bin, "--headless", "--norestore",
               f"-env:UserInstallation={Path(profile_dir).as_uri()}",
               "--convert-to", "pdf", "--outdir", out_dir, pptx_path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        if os.path.exists(pdf_path):
            logger.info("soffice 转换 PDF 成功: %s", pdf_path)
            return pdf_path
        logger.warning("soffice 未产出 PDF 文件，预览降级(E6003)")
    except Exception as e:
        logger.warning("soffice 转换也失败，预览降级(E6003): %s", e)
    finally:
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)
    return None


def pdf_to_images(pdf_path: str, out_dir: str) -> list[dict]:
    """PDF 逐页转 PNG 大图 + 缩略图。返回 [{page, image_path, thumb_path}]。"""
    s = get_settings()
    results = []
    doc = fitz.open(pdf_path)
    try:
        zoom = s.preview_dpi / 72.0
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            image_path = os.path.join(out_dir, f"page-{i + 1}.png")
            pix.save(image_path)
            # 生成缩略图
            thumb_path = os.path.join(out_dir, f"thumb-{i + 1}.png")
            with Image.open(image_path) as im:
                ratio = s.thumb_width / im.width
                im.resize((s.thumb_width, max(1, int(im.height * ratio)))).save(thumb_path)
            results.append({"page": i + 1, "image_path": image_path, "thumb_path": thumb_path})
    finally:
        doc.close()
    logger.info("PDF 转图片完成，共 %d 页", len(results))
    return results


def convert_healthy() -> bool:
    """健康检查：unoserver 端口可达即认为健康。"""
    s = get_settings()
    if s.convert_backend != "unoserver":
        return True
    import socket
    try:
        with socket.create_connection((s.unoserver_host, s.unoserver_port), timeout=2):
            return True
    except OSError:
        return False


def make_temp_dir() -> str:
    return tempfile.mkdtemp(prefix="pptgen_")
