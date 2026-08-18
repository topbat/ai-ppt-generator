"""ppt-master 生成 API（独立能力，异步提交 → 轮询状态）。

POST   /api/v1/pptmaster/jobs                     multipart 提交任务，秒回 job_id
GET    /api/v1/pptmaster/jobs                     列表（含进度），前端 3s 轮询
GET    /api/v1/pptmaster/jobs/{id}                详情（含日志尾部 / 提示词 / 产物 / 预览）
POST   /api/v1/pptmaster/jobs/{id}/cancel         取消
DELETE /api/v1/pptmaster/jobs/{id}                删除（软删，运行中不可删）
GET    /api/v1/pptmaster/jobs/{id}/download/{kind} 产物下载（后端代理输出）
GET    /api/v1/pptmaster/jobs/{id}/pages/{n}/image 逐页预览（svg/png）
GET    /api/v1/pptmaster/jobs/{id}/log            完整日志
GET    /api/v1/pptmaster/options                  能力目录（入参枚举 / 可用 Agent / 仓库状态）
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.object_response import object_response
from app.core.config import (default_selectable_model, get_settings, selectable_models,
                             validate_selectable_model)
from app.core.database import get_db
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import PptMasterJob
from app.pptmaster import catalog
from app.pptmaster.prompt import build_prompt
from app.pptmaster.runner import AgentInfo, detect_agents, select_agent
from app.pptmaster.service import cancel_local_process, repo_dir, repo_ready, source_rel_paths
from app.schemas.dto import err, ok

router = APIRouter(prefix="/pptmaster", tags=["pptmaster"])
logger = get_logger(__name__)

_ACTIVE = ("pending", "running")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def _safe_name(name: str, used: set[str]) -> str:
    base = os.path.basename(name or "file")
    base = _SAFE_NAME_RE.sub("_", base).strip(" .") or "file"
    if len(base) > 120:
        stem, ext = os.path.splitext(base)
        base = stem[:120 - len(ext)] + ext
    cand, i = base, 1
    while cand.lower() in used:
        stem, ext = os.path.splitext(base)
        cand = f"{stem}_{i}{ext}"
        i += 1
    used.add(cand.lower())
    return cand


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dto(j: PptMasterJob, detail: bool = False) -> dict:
    outputs = []
    pptx_url = None
    for o in j.outputs or []:
        url = f"/api/v1/pptmaster/jobs/{j.biz_id}/download/{o['kind']}"
        outputs.append({"kind": o["kind"], "name": o.get("name"), "size": o.get("size"), "download_url": url,
                        "label": catalog.OUTPUT_KIND_LABELS.get(o["kind"], o["kind"])})
        if o["kind"] == "pptx" or (pptx_url is None and o["kind"].startswith("pptx")):
            pptx_url = url
    previews = j.preview_keys or []
    params = dict(j.params or {})
    run_info = params.pop("_run", None)
    d = {
        "job_id": j.biz_id, "title": j.title,
        "input_mode": j.input_mode, "route": j.route, "profile": j.profile,
        "agent": j.agent, "model": j.model,
        "status": j.status, "progress": j.progress or 0, "stage": j.stage,
        "params": params,
        "source_files": [{"name": f.get("name"), "size": f.get("size")} for f in (j.source_files or [])],
        "template_name": j.template_name,
        "outputs": outputs, "pptx_url": pptx_url,
        "preview_pages": len(previews),
        "preview_urls": [f"/api/v1/pptmaster/jobs/{j.biz_id}/pages/{i}/image" for i in range(1, len(previews) + 1)],
        "page_count": j.page_count, "file_size": j.file_size,
        "error_message": j.error_message,
        "created_at": _iso(j.created_at), "started_at": _iso(j.started_at), "finished_at": _iso(j.finished_at),
        "duration_ms": j.duration_ms,
        "run": run_info,
    }
    if detail:
        d.update({"prompt": j.prompt or "", "log_tail": j.log_tail or "",
                  "log_url": f"/api/v1/pptmaster/jobs/{j.biz_id}/log"})
    return d


# ---------------------------------------------------------------- options ----
@router.get("/options")
def get_options():
    s = get_settings()
    ready, ver = repo_ready()
    delegated = s.pptmaster_execution_scope == "worker"
    if delegated:
        claude_ready = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
        codex_ready = bool(os.environ.get("OPENAI_API_KEY"))
        agents = [
            AgentInfo("claude", "Claude Code CLI", claude_ready, None,
                      "由 pptmaster-worker 执行并二次校验" if claude_ready else "Worker 未配置 Anthropic 凭据"),
            AgentInfo("codex", "Codex CLI", codex_ready, None,
                      "由 pptmaster-worker 执行并二次校验" if codex_ready else "Worker 未配置 OpenAI 凭据"),
            AgentInfo("mock", "Mock（不调用 Agent，仅生成占位 PPTX 验证链路）", True, None, "内置"),
        ]
    else:
        agents = detect_agents()
    default_agent = "mock"
    try:
        default_agent = select_agent("auto", agents, s.pptmaster_default_agent).key
    except Exception:  # noqa: BLE001
        pass
    return ok({
        "execution_scope": s.pptmaster_execution_scope,
        "repo": {"dir": repo_dir(), "ready": ready, "version": ver, "delegated": delegated},
        "agents": [{"key": a.key, "label": a.label, "available": a.available, "bin": a.bin, "note": a.note}
                   for a in agents],
        "default_agent": default_agent,
        "models": selectable_models(s),
        "default_model": default_selectable_model(s),
        "input_modes": catalog.INPUT_MODES,
        "routes": catalog.ROUTES,
        "profiles": catalog.PROFILES,
        "canvas_formats": catalog.CANVAS_FORMATS,
        "styles": catalog.STYLES,
        "narrative_modes": catalog.NARRATIVE_MODES,
        "reading_modes": catalog.READING_MODES,
        "languages": catalog.LANGUAGES,
        "image_sources": catalog.IMAGE_SOURCES,
        "limits": {"max_files": s.pptmaster_max_files, "max_upload_mb": s.pptmaster_max_upload_mb,
                   "pages_min": 1, "pages_max": 60,
                   "timeout_minutes_default": s.pptmaster_timeout_minutes,
                   "timeout_minutes_max": s.pptmaster_timeout_max_minutes},
        "accept_extensions": catalog.ACCEPT_EXTENSIONS,
    })


# ---------------------------------------------------------------- create ----
@router.post("/jobs")
async def create_job(
    input_mode: str = Form("files"),
    topic: str = Form(""),
    text: str = Form(""),
    url: str = Form(""),
    route: str = Form("generate"),
    profile: str = Form("quick"),
    pages: str = Form(""),
    canvas: str = Form("ppt169"),
    style: str = Form("auto"),
    narrative_mode: str = Form("auto"),
    reading_mode: str = Form("auto"),
    language: str = Form("auto"),
    native_charts: str = Form("false"),
    speaker_notes: str = Form("false"),
    narration: str = Form("false"),
    transitions: str = Form("false"),
    animations: str = Form("false"),
    image_source: str = Form("auto"),
    extra_instructions: str = Form(""),
    title: str = Form(""),
    agent: str = Form("auto"),
    model: str = Form(""),
    timeout_minutes: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    template: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    s = get_settings()
    if route == "template_fill":
        style = "template"
    # ---- 枚举校验 ----
    for k, v in (("input_mode", input_mode), ("route", route), ("profile", profile), ("canvas", canvas),
                 ("style", style), ("narrative_mode", narrative_mode), ("reading_mode", reading_mode),
                 ("language", language), ("image_source", image_source)):
        if v not in catalog.VALID[k]:
            return err(1001, f"参数 {k} 取值不合法：{v}")
    try:
        selected_model = validate_selectable_model(model, s)
    except ValueError as exc:
        return err(1001, str(exc))
    route_def = catalog.ROUTE_BY_KEY[route]
    pages_int: int | None = None
    if str(pages).strip():
        try:
            pages_int = int(str(pages).strip())
        except ValueError:
            return err(1001, "页数必须为整数")
        if not 1 <= pages_int <= 60:
            return err(1004, "页数须在 1~60 之间")
    timeout_int: int | None = None
    if str(timeout_minutes).strip():
        try:
            timeout_int = max(3, min(int(str(timeout_minutes).strip()), s.pptmaster_timeout_max_minutes))
        except ValueError:
            return err(1001, "超时分钟数必须为整数")

    # ---- 输入方式校验 ----
    if input_mode == "topic" and not topic.strip():
        return err(1001, "请填写主题")
    if input_mode == "text" and not text.strip():
        return err(1001, "请粘贴材料文本")
    if input_mode == "url":
        u = url.strip()
        if not u or urlparse(u).scheme not in ("http", "https"):
            return err(1001, "请填写有效的 http/https 网址")
    if input_mode == "files" and not files:
        return err(1001, "请至少上传一个源文件")

    # ---- 文件校验与读取 ----
    max_bytes = s.pptmaster_max_upload_mb * 1024 * 1024
    if len(files) > s.pptmaster_max_files:
        return err(1002, f"最多上传 {s.pptmaster_max_files} 个文件")
    used: set[str] = set()
    read_files: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or "file"
        ext = os.path.splitext(name)[1].lower()
        if ext not in catalog.ACCEPT_EXTENSIONS:
            return err(1001, f"文件类型不支持：{name}")
        data = await f.read()
        if len(data) > max_bytes:
            return err(1002, f"文件超过 {s.pptmaster_max_upload_mb}MB 限制：{name}")
        if not data:
            return err(1003, f"文件为空：{name}")
        read_files.append((_safe_name(name, used), data))
    tpl_data: bytes | None = None
    tpl_name: str | None = None
    if template is not None and template.filename:
        if not template.filename.lower().endswith(".pptx"):
            return err(1001, "模板必须是 .pptx 文件")
        tpl_data = await template.read()
        if len(tpl_data) > max_bytes:
            return err(1002, f"模板超过 {s.pptmaster_max_upload_mb}MB 限制")
        tpl_name = _safe_name(template.filename, used)
    if route_def.get("needs_template") and not tpl_data:
        return err(1001, "该路线需要上传你的 PPTX 模板")
    if route_def.get("needs_pptx") and not any(n.lower().endswith(".pptx") for n, _ in read_files):
        return err(1001, "该路线需要在源文件中上传要处理的 .pptx")
    if route == "image_to_pptx" and not any(os.path.splitext(n)[1].lower() in _IMAGE_EXT for n, _ in read_files):
        return err(1001, "图片还原路线需要上传页面图片（png/jpg/webp）")

    # ---- Agent：API 只校验枚举；可用性由真正执行任务的 Worker 二次校验 ----
    want = agent or "auto"
    if want not in {"auto", "claude", "codex", "mock"}:
        return err(1001, f"未知 Agent：{want}")
    if route_def.get("agents"):
        allowed = route_def["agents"]
        if want == "auto":
            want = allowed[0]
        elif want not in allowed and want != "mock":
            return err(1001, f"该路线仅支持 Agent：{', '.join(allowed)}")
    # ---- 落库与上传 ----
    biz_id = new_biz_id("pm")
    from app.services.storage import get_storage
    storage = get_storage()
    source_files = []
    for name, data in read_files:
        key = f"pptmaster/{biz_id}/sources/{name}"
        storage.put_bytes(key, data)
        source_files.append({"name": name, "size": len(data), "key": key})
    template_key = None
    if tpl_data and tpl_name:
        template_key = f"pptmaster/{biz_id}/template/{tpl_name}"
        storage.put_bytes(template_key, tpl_data)

    if not title.strip():
        if read_files:
            title = os.path.splitext(read_files[0][0])[0]
        elif input_mode == "topic":
            title = topic.strip()[:60]
        elif input_mode == "url":
            title = urlparse(url.strip()).netloc or "网页材料"
        else:
            title = "粘贴文本"
    params = {
        "input_mode": input_mode, "topic": topic.strip(), "text": text if input_mode == "text" else "",
        "url": url.strip(), "route": route, "profile": profile, "pages": pages_int,
        "canvas": canvas, "style": style, "narrative_mode": narrative_mode, "reading_mode": reading_mode,
        "language": language, "native_charts": _truthy(native_charts), "speaker_notes": _truthy(speaker_notes),
        "narration": _truthy(narration), "transitions": _truthy(transitions), "animations": _truthy(animations),
        "image_source": image_source, "extra_instructions": extra_instructions.strip(),
        "timeout_minutes": timeout_int, "agent_requested": agent or "auto",
    }
    # 提示词在此生成（与 Worker 侧路径约定一致：projects/{biz}/sources/<name>）
    names = [n for n, _ in read_files]
    p_for_prompt = dict(params)
    if input_mode == "text":
        names = names + ["pasted_material.md"]
        p_for_prompt["text"] = ""
    prompt = build_prompt(biz_id, p_for_prompt, source_rel_paths(biz_id, names),
                          f"projects/{biz_id}/sources/{tpl_name}" if tpl_name else None)

    job = PptMasterJob(
        biz_id=biz_id, title=title[:250], input_mode=input_mode, route=route, profile=profile,
        agent=want, model=selected_model, params=params, prompt=prompt,
        status="pending", progress=0, stage="排队中", source_files=source_files,
        template_name=tpl_name, template_key=template_key,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.worker import pptmaster_generate
    pptmaster_generate.delay(job.id)
    logger.info("ppt-master 任务已创建 %s（%s / %s / agent=%s / model=%s，%d 个文件）",
                biz_id, input_mode, route, want, selected_model, len(source_files))
    return ok({"job_id": biz_id})


# ---------------------------------------------------------------- query ----
@router.get("/jobs")
def list_jobs(status: str | None = None, page: int = 1, page_size: int = 10, db: Session = Depends(get_db)):
    q = select(PptMasterJob).where(PptMasterJob.deleted_at.is_(None))
    if status:
        q = q.where(PptMasterJob.status == status)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(PptMasterJob.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return ok({"items": [_dto(r) for r in rows], "total": total})


def _get(db: Session, biz_id: str) -> PptMasterJob | None:
    return db.execute(select(PptMasterJob).where(PptMasterJob.biz_id == biz_id,
                                                 PptMasterJob.deleted_at.is_(None))).scalar_one_or_none()


@router.get("/jobs/{biz_id}")
def job_detail(biz_id: str, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return err(404, "任务不存在")
    return ok(_dto(job, detail=True))


@router.post("/jobs/{biz_id}/cancel")
def cancel_job(biz_id: str, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return err(404, "任务不存在")
    if job.status not in _ACTIVE:
        return err(409, f"任务已处于终态（{job.status}），无法取消")
    if job.status == "pending":
        job.status = "canceled"
        job.stage = "已取消"
        job.finished_at = datetime.now(timezone.utc)
    job.cancel_requested = True
    db.commit()
    cancel_local_process(job)
    return ok({"job_id": biz_id, "status": job.status})


@router.delete("/jobs/{biz_id}")
def delete_job(biz_id: str, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return err(404, "任务不存在")
    if job.status in _ACTIVE:
        return err(409, "任务运行中，请先取消再删除")
    job.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return ok({"deleted": True})


@router.get("/jobs/{biz_id}/download/{kind}")
def download_output(biz_id: str, kind: str, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return err(404, "任务不存在")
    for o in job.outputs or []:
        if o.get("kind") == kind:
            return object_response(o["key"], filename=o.get("name"), download=True)
    return err(404, "产物不存在")


@router.get("/jobs/{biz_id}/pages/{page_no}/image")
def page_image(biz_id: str, page_no: int, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return err(404, "任务不存在")
    keys = job.preview_keys or []
    if not 1 <= page_no <= len(keys):
        return err(404, "预览页不存在")
    key = keys[page_no - 1]
    media = "image/svg+xml" if key.lower().endswith(".svg") else "image/png"
    return object_response(key, media_type=media, cache=job.status != "running")


@router.get("/jobs/{biz_id}/log")
def job_log(biz_id: str, db: Session = Depends(get_db)):
    job = _get(db, biz_id)
    if job is None:
        return PlainTextResponse("任务不存在", status_code=404)
    text_out = None
    if job.log_key:
        try:
            from app.services.storage import get_storage
            text_out = get_storage().get_bytes(job.log_key).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text_out = None
    if text_out is None and job.project_dir:
        local = os.path.join(job.project_dir, "agent.log")
        if os.path.exists(local):
            with open(local, "r", encoding="utf-8", errors="replace") as f:
                text_out = f.read()
    if text_out is None:
        text_out = job.log_tail or ""
    return PlainTextResponse(text_out, media_type="text/plain; charset=utf-8")
