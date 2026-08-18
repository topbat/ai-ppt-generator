"""ppt-master 任务执行服务（Worker 侧）：准备工作区 → 驱动 Agent → 监控进度 → 收集产物 → 上传 → 落库。

与生成流水线（app/pipeline）完全独立：不共享 Stage/Guard/Checkpoint，只复用 storage / convert / db。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import PptMasterJob
from app.pptmaster.prompt import build_prompt
from app.pptmaster.runner import RunResult, agent_env, detect_agents, make_runner, select_agent
from app.services.storage import get_storage

logger = get_logger(__name__)

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_LOG_TAIL_CHARS = 4000
_SVG_PAGE_RE = re.compile(r"(?:^|[\\/])P(\d{2,3})\.svg$", re.IGNORECASE)          # 规范命名 P01.svg
_SVG_ANY_RE = re.compile(r"(?:^|[\\/])(?:P)?(\d{1,3})[^\\/]*\.svg$", re.IGNORECASE)   # 兼容 01_cover.svg 等


def _svg_page_no(path: str) -> int | None:
    m = _SVG_ANY_RE.search(path)
    return int(m.group(1)) if m else None


def _list_page_svgs(d: str) -> list[str]:
    """目录内的页面 SVG，按前导页码排序（无页码的按文件名排在其后）。"""
    if not os.path.isdir(d):
        return []
    svgs = [f for f in glob.glob(os.path.join(d, "*.svg"))]
    svgs.sort(key=lambda f: (_svg_page_no(f) is None, _svg_page_no(f) or 0, os.path.basename(f).lower()))
    return svgs


# ---------------------------------------------------------------- 路径 ----
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))   # backend/


def repo_dir() -> str:
    """ppt-master 仓库目录。相对路径按 backend/ 目录解析（默认 ../ppt-master，即与 backend 同级），与启动 CWD 无关。"""
    raw = get_settings().pptmaster_repo_dir or "../ppt-master"
    return os.path.abspath(raw if os.path.isabs(raw) else os.path.join(_BACKEND_ROOT, raw))


def projects_dir() -> str:
    s = get_settings()
    return os.path.abspath(s.pptmaster_projects_dir or os.path.join(repo_dir(), "projects"))


def repo_ready() -> tuple[bool, str | None]:
    """ppt-master 仓库是否可用（存在 skills/ppt-master/SKILL.md），并尽量读出版本。"""
    r = repo_dir()
    skill = os.path.join(r, "skills", "ppt-master", "SKILL.md")
    if not os.path.exists(skill):
        return False, None
    ver = None
    try:
        import subprocess
        out = subprocess.run(["git", "describe", "--tags", "--always"], cwd=r, capture_output=True,
                             text=True, timeout=10)
        ver = (out.stdout or "").strip() or None
    except Exception:  # noqa: BLE001
        pass
    return True, ver


def project_dir_for(biz_id: str) -> str:
    return os.path.join(projects_dir(), biz_id)


def rel_to_repo(path: str) -> str:
    return os.path.relpath(path, repo_dir()).replace("\\", "/")


_INIT_PATH_RE = re.compile(r"(?:Project initialized|Project created):\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def init_project_workspace(biz_id: str, canvas: str, quick: bool) -> str:
    """调用 ppt-master 的 project_manager.py init 建立规范工作区（目录形如 projects/<biz>_<canvas>_<YYYYMMDD>）。

    init 失败（脚本异常/目录已存在等）时回退为手工创建 projects/<biz>/，保证任务可继续。
    """
    import subprocess

    from app.pptmaster.runner import agent_env
    r = repo_dir()
    script = os.path.join(r, "skills", "ppt-master", "scripts", "project_manager.py")
    base = projects_dir()
    os.makedirs(base, exist_ok=True)
    py = get_settings().pptmaster_python_bin or sys.executable
    cmd = [py, script, "init", biz_id, "--format", canvas or "ppt169", "--dir", base]
    if quick:
        cmd.append("--quick-generate")
    try:
        out = subprocess.run(cmd, cwd=r, env=agent_env(r), capture_output=True, text=True, timeout=120,
                             encoding="utf-8", errors="replace")
        text_out = (out.stdout or "") + "\n" + (out.stderr or "")
        m = _INIT_PATH_RE.search(text_out)
        if out.returncode == 0 and m:
            path = m.group(1).strip().strip("`'\"")
            if os.path.isdir(path):
                return os.path.abspath(path)
        # 兜底：按命名规则猜测
        for d in sorted(glob.glob(os.path.join(base, f"{biz_id}_*")), key=os.path.getmtime, reverse=True):
            if os.path.isdir(d):
                return os.path.abspath(d)
        logger.warning("project_manager.py init 未返回目录（rc=%s）：%s", out.returncode, text_out[-400:])
    except Exception as e:  # noqa: BLE001
        logger.warning("project_manager.py init 调用失败，回退手工建目录：%s", e)
    fallback = os.path.join(base, biz_id)
    for sub in ("sources", "svg_output", "exports", "validation"):
        os.makedirs(os.path.join(fallback, sub), exist_ok=True)
    return fallback


def source_rel_paths(biz_id: str, names: list[str]) -> list[str]:
    return [f"projects/{biz_id}/sources/{n}" for n in names]


def resolve_worker_agent(requested: str):
    """在实际消费任务的 Worker 内刷新能力探测并解析 Agent。"""
    s = get_settings()
    return select_agent(requested, detect_agents(force=True), s.pptmaster_default_agent)


# ---------------------------------------------------------------- 主流程 ----
def _now():
    return datetime.now(timezone.utc)


def _update(job_pk: int, **fields) -> None:
    with db_session() as db:
        job = db.get(PptMasterJob, job_pk)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)


def _cancel_requested(job_pk: int) -> bool:
    with db_session() as db:
        job = db.get(PptMasterJob, job_pk)
        return bool(job and (job.cancel_requested or job.status == "canceled"))


def _tail(path: str, n: int = _LOG_TAIL_CHARS) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > n:
                f.seek(size - n)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


class _ProgressMonitor:
    """把 Agent 事件流与工作区文件变化折算为 progress / stage（启发式），并节流写库。"""

    def __init__(self, job_pk: int, project: str, log_path: str, target_pages: int | None):
        self.job_pk = job_pk
        self.project = project
        self.log_path = log_path
        self.target = target_pages or 10
        self.progress = 5
        self.stage = "启动 Agent"
        self._last_flush = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="pm-monitor", daemon=True)

    # ---- 事件流 ----
    def on_line(self, raw: str, ev: dict | None) -> None:
        if not ev:
            return
        stage = None
        pct = None
        t = ev.get("type")
        if t == "mock_progress":
            pct = 10 + int(80 * ev.get("page", 0) / max(1, ev.get("total", 1)))
            stage = f"生成第 {ev.get('page')} / {ev.get('total')} 页"
        elif t == "assistant":
            for blk in (ev.get("message") or {}).get("content") or []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_use":
                    stage = self._stage_from_tool(blk.get("name") or "", blk.get("input") or {}) or stage
                elif blk.get("type") == "text" and blk.get("text") and not stage:
                    txt = str(blk["text"]).strip().splitlines()
                    if txt:
                        stage = txt[-1][:100]
        elif t == "item.started" or t == "item.completed":          # codex
            item = ev.get("item") or {}
            if item.get("type") == "command_execution":
                stage = self._stage_from_tool("Bash", {"command": item.get("command") or ""}) or stage
            elif item.get("type") == "agent_message" and item.get("text"):
                stage = str(item["text"]).strip().splitlines()[-1][:100]
        if stage or pct is not None:
            with self._lock:
                if stage:
                    self.stage = stage
                if pct is not None:
                    self.progress = max(self.progress, min(pct, 95))

    @staticmethod
    def _stage_from_tool(name: str, inp: dict) -> str | None:
        cmd = str(inp.get("command") or "")
        path = str(inp.get("file_path") or inp.get("path") or "")
        blob = cmd + " " + path
        if "source_to_md" in blob:
            return "转换材料为 Markdown"
        if "project_manager.py init" in blob:
            return "初始化项目工作区"
        if "import-sources" in blob:
            return "导入材料并分析"
        if "image_gen" in blob or "image_search" in blob or "analyze_images" in blob:
            return "准备图片素材"
        if "icon_sync" in blob:
            return "挑选图标"
        if "svg_quality_checker" in blob:
            return "SVG 质量检查"
        if "finalize_svg" in blob:
            return "生成 SVG 预览"
        if "svg_to_pptx" in blob:
            return "编译导出 PPTX"
        if "notes_to_audio" in blob or "narration" in blob:
            return "生成语音旁白"
        if "template_fill_pptx" in blob:
            return "填充 PPTX 模板"
        if "native_enhance" in blob:
            return "增强 PPTX（备注/旁白/转场）"
        if name in ("Write", "Edit", "MultiEdit", "Bash") and "svg_output" in blob:
            no = _svg_page_no(path) or _svg_page_no(cmd)
            if no:
                return f"撰写第 {no} 页 SVG"
        if name in ("Read",) and "SKILL.md" in path:
            return "读取 ppt-master 工作流"
        if name == "Read" and "references" in path:
            return "阅读工作流参考"
        return None

    # ---- 文件扫描 ----
    def _scan(self) -> None:
        p = Path(self.project)
        pct = self.progress
        stage = None
        if (p / "sources").exists() and any((p / "sources").glob("*.md")):
            pct = max(pct, 10)
        if any(p.glob("design_spec*.md")):
            pct = max(pct, 20)
        svgs = _list_page_svgs(str(p / "svg_output"))
        if svgs:
            k = len(svgs)
            pct = max(pct, 25 + int(55 * min(1.0, k / max(1, self.target))))
            stage = f"已生成 {k} 页 SVG" if k < self.target else "SVG 全部完成，质检/导出中"
        if (p / "validation" / "svg_quality_report.json").exists():
            pct = max(pct, 84)
        if (p / "svg_final").exists() and any((p / "svg_final").glob("*.svg")):
            pct = max(pct, 88)
        if (p / "exports").exists() and any((p / "exports").glob("*.pptx")):
            pct = max(pct, 95)
            stage = "PPTX 已导出，收尾中"
        with self._lock:
            self.progress = max(self.progress, min(pct, 95))
            if stage and (self.stage.startswith("已生成") or self.stage.startswith("撰写") or not self.stage
                          or pct >= 95):
                self.stage = stage

    def _loop(self) -> None:
        while not self._stop.wait(3.0):
            try:
                self._scan()
                self.flush()
            except Exception as e:  # noqa: BLE001
                logger.debug("进度监控异常：%s", e)

    def flush(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_flush < 3.0:
            return
        self._last_flush = now
        with self._lock:
            prog, stage = self.progress, self.stage
        _update(self.job_pk, progress=prog, stage=stage[:120] if stage else None,
                log_tail=_tail(self.log_path))

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)


def _classify_pptx(name: str) -> str:
    low = name.lower()
    if "narrated" in low:
        return "pptx_narrated"
    if "native_charts_tables" in low:
        return "pptx_native"
    return "pptx"


def _collect_outputs(project: str, biz_id: str) -> tuple[list[dict], str | None, int | None]:
    """收集 exports/*.pptx（每种变体取最新）与报告；上传并返回 (outputs, 主 pptx 本地路径, page_count)。"""
    storage = get_storage()
    outputs: list[dict] = []
    exports = sorted(glob.glob(os.path.join(project, "exports", "*.pptx")), key=os.path.getmtime, reverse=True)
    picked: dict[str, str] = {}
    for f in exports:
        kind = _classify_pptx(os.path.basename(f))
        picked.setdefault(kind, f)
    primary = picked.get("pptx") or picked.get("pptx_native") or picked.get("pptx_narrated")
    for kind, f in picked.items():
        name = os.path.basename(f)
        key = f"pptmaster/{biz_id}/exports/{name}"
        storage.put_file(key, f, _PPTX_MIME)
        outputs.append({"kind": kind, "name": name, "size": os.path.getsize(f), "key": key})
    reports = sorted(glob.glob(os.path.join(project, "validation", "*.report.json")), key=os.path.getmtime,
                     reverse=True)
    if reports:
        f = reports[0]
        key = f"pptmaster/{biz_id}/report/{os.path.basename(f)}"
        storage.put_file(key, f, "application/json")
        outputs.append({"kind": "report", "name": os.path.basename(f), "size": os.path.getsize(f), "key": key})
    page_count = None
    if primary:
        try:
            from pptx import Presentation
            page_count = len(Presentation(primary).slides)
        except Exception:  # noqa: BLE001
            page_count = None
    return outputs, primary, page_count


def _collect_previews(project: str, biz_id: str, primary_pptx: str | None) -> tuple[list[str], dict | None]:
    """预览：优先 PPTX→PDF→PNG（需转换后端），否则退回 svg_final/ 或 svg_output/ 的逐页 SVG。返回 (预览键列表, pdf 输出)。"""
    storage = get_storage()
    keys: list[str] = []
    pdf_out = None
    if primary_pptx:
        try:
            from app.services.convert import make_temp_dir, pdf_to_images, pptx_to_pdf
            tmp = make_temp_dir()
            pdf = pptx_to_pdf(primary_pptx, tmp)
            if pdf:
                pdf_key = f"pptmaster/{biz_id}/exports/preview.pdf"
                storage.put_file(pdf_key, pdf, "application/pdf")
                pdf_out = {"kind": "pdf", "name": "preview.pdf", "size": os.path.getsize(pdf), "key": pdf_key}
                for r in pdf_to_images(pdf, tmp):
                    key = f"pptmaster/{biz_id}/preview/{r['page']:03d}.png"
                    storage.put_file(key, r["image_path"], "image/png")
                    keys.append(key)
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("ppt-master 任务 %s PPTX 预览转换失败（降级为 SVG 预览）：%s", biz_id, e)
    if keys:
        return keys, pdf_out
    for sub in ("svg_final", "svg_output"):
        svgs = _list_page_svgs(os.path.join(project, sub))
        if not svgs:
            continue
        for i, f in enumerate(svgs, 1):
            key = f"pptmaster/{biz_id}/preview/{i:03d}.svg"
            storage.put_file(key, f, "image/svg+xml")
            keys.append(key)
        break
    return keys, pdf_out


def run_pptmaster_job(job_pk: int) -> None:
    """Celery 任务入口：完整执行一个 ppt-master 生成任务。"""
    s = get_settings()
    with db_session() as db:
        job = db.get(PptMasterJob, job_pk)
        if job is None:
            logger.warning("ppt-master 任务不存在 pk=%s", job_pk)
            return
        if job.status not in ("pending",):
            logger.info("ppt-master 任务 %s 状态为 %s，跳过执行", job.biz_id, job.status)
            return
        biz_id = job.biz_id
        params = dict(job.params or {})
        agent_requested = params.get("agent_requested") or job.agent or "auto"
        agent_key = job.agent
        model = job.model
        title = job.title
        source_files = list(job.source_files or [])
        template_key = job.template_key
        template_name = job.template_name
        prompt = job.prompt
        job.status = "running"
        job.started_at = _now()
        job.progress = 2
        job.stage = "准备工作区"
        job.error_message = None

    started = time.monotonic()
    project = project_dir_for(biz_id)
    log_path = os.path.join(project, "agent.log")
    monitor: _ProgressMonitor | None = None
    try:
        # API 与 Worker 分离时，只有 Worker 拥有 Agent CLI 与 ppt-master 仓库。
        info = resolve_worker_agent(agent_requested)
        agent_key = info.key
        _update(job_pk, agent=agent_key, stage=f"准备工作区（{agent_key}）")
        # ---- 1. 工作区与材料 ----
        ready, _ver = repo_ready()
        if agent_key != "mock" and not ready:
            raise RuntimeError(f"ppt-master 仓库不可用：{repo_dir()} 下未找到 skills/ppt-master/SKILL.md，"
                               f"请克隆 hugohe3/ppt-master 并设置 PPTMASTER_REPO_DIR")
        if ready:
            project = init_project_workspace(biz_id, params.get("canvas") or "ppt169",
                                             params.get("profile", "quick") == "quick"
                                             and params.get("route", "generate") in ("generate", "beautify"))
        else:
            os.makedirs(os.path.join(project, "sources"), exist_ok=True)
        log_path = os.path.join(project, "agent.log")
        project_rel = rel_to_repo(project)
        os.makedirs(os.path.join(project, "sources"), exist_ok=True)
        os.makedirs(os.path.join(project, "exports"), exist_ok=True)
        storage = get_storage()
        names: list[str] = []
        for sf in source_files:
            local = os.path.join(project, "sources", sf["name"])
            storage.download_to(sf["key"], local)
            names.append(sf["name"])
        if params.get("input_mode") == "text" and params.get("text"):
            local = os.path.join(project, "sources", "pasted_material.md")
            with open(local, "w", encoding="utf-8") as f:
                f.write(str(params["text"]))
            names.append("pasted_material.md")
        template_rel = None
        if template_key:
            local = os.path.join(project, "sources", template_name or "template.pptx")
            storage.download_to(template_key, local)
            template_rel = rel_to_repo(local)
        # 用真实工作区目录重建提示词（API 侧生成的是 projects/<biz> 预估版）
        p2 = dict(params)
        if p2.get("input_mode") == "text":
            p2["text"] = ""   # 文本已落成材料文件，不再内嵌到提示词
        prompt = build_prompt(biz_id, p2, [f"{project_rel}/sources/{n}" for n in names], template_rel,
                              project_rel=project_rel)
        _update(job_pk, prompt=prompt)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"[{_now().isoformat()}] ppt-master 任务 {biz_id} 开始，Agent={agent_key} model={model or '-'}\n")
            f.write("---- PROMPT ----\n" + prompt + "\n---- END PROMPT ----\n")
        _update(job_pk, project_dir=project, progress=5, stage="启动 Agent")

        # ---- 2. 运行 Agent ----
        binary = info.bin
        pages = params.get("pages")
        runner = make_runner(agent_key, binary, model, project_dir=project,
                             pages=int(pages) if pages else None, title=title)
        timeout_min = int(params.get("timeout_minutes") or s.pptmaster_timeout_minutes)
        timeout_min = max(3, min(timeout_min, s.pptmaster_timeout_max_minutes))
        monitor = _ProgressMonitor(job_pk, project, log_path, int(pages) if pages else None)
        monitor.start()

        result: RunResult = runner.run(
            prompt, repo_dir(), agent_env(repo_dir()), log_path,
            on_line=monitor.on_line,
            should_cancel=lambda: _cancel_requested(job_pk),
            timeout_s=timeout_min * 60,
            on_pid=lambda pid: _update(job_pk, agent_pid=pid),
        )
        monitor.stop()
        monitor.flush(force=True)

        # ---- 3. 收集产物 ----
        _update(job_pk, stage="收集并上传产物", progress=96)
        outputs, primary, page_count = _collect_outputs(project, biz_id)
        preview_keys, pdf_out = _collect_previews(project, biz_id, primary)
        if pdf_out:
            outputs.append(pdf_out)
        log_key = f"pptmaster/{biz_id}/agent.log"
        try:
            storage.put_file(log_key, log_path, "text/plain; charset=utf-8")
            outputs.append({"kind": "log", "name": "agent.log", "size": os.path.getsize(log_path), "key": log_key})
        except Exception as e:  # noqa: BLE001
            logger.warning("上传 Agent 日志失败：%s", e)
            log_key = None
        stream_path = log_path + ".stream.jsonl"
        if os.path.exists(stream_path) and os.path.getsize(stream_path) <= 30 * 1024 * 1024:
            try:
                skey = f"pptmaster/{biz_id}/agent.stream.jsonl"
                storage.put_file(skey, stream_path, "application/x-ndjson")
                outputs.append({"kind": "stream", "name": "agent.stream.jsonl",
                                "size": os.path.getsize(stream_path), "key": skey})
            except Exception as e:  # noqa: BLE001
                logger.debug("上传原始事件流失败（忽略）：%s", e)

        duration_ms = int((time.monotonic() - started) * 1000)
        final_text = (result.final_text or "").strip()
        failed_line = next((ln for ln in final_text.splitlines() if ln.strip().upper().startswith("FAILED:")), None)
        extra = {"cost_usd": result.cost_usd, "num_turns": result.num_turns,
                 "returncode": result.returncode, "final_text": final_text[-1000:]}
        if result.canceled:
            _update(job_pk, status="canceled", stage="已取消", finished_at=_now(), duration_ms=duration_ms,
                    outputs=outputs, preview_keys=preview_keys, log_key=log_key, log_tail=_tail(log_path),
                    page_count=page_count, agent_pid=None, params={**params, "_run": extra})
            logger.info("ppt-master 任务 %s 已取消", biz_id)
            return
        if primary:
            note = ""
            if result.timed_out:
                note = "（Agent 超时被终止，但已导出 PPTX）"
            elif result.returncode != 0 or result.error:
                note = "（Agent 退出异常，但已导出 PPTX）"
            _update(job_pk, status="succeeded", progress=100, stage=("完成" + note)[:120],
                    finished_at=_now(), duration_ms=duration_ms, outputs=outputs,
                    preview_keys=preview_keys, log_key=log_key, log_tail=_tail(log_path),
                    page_count=page_count, file_size=os.path.getsize(primary), agent_pid=None,
                    params={**params, "_run": extra})
            logger.info("ppt-master 任务 %s 成功：%s（%d 页，%.1fs，cost=%s）", biz_id,
                        os.path.basename(primary), page_count or 0, duration_ms / 1000, result.cost_usd)
            return
        # 失败
        if result.timed_out:
            msg = f"Agent 执行超过 {timeout_min} 分钟未产出 PPTX，已终止"
        elif failed_line:
            msg = failed_line.strip()[:800]
        elif result.error:
            msg = f"Agent 报错：{result.error[:600]}"
        else:
            msg = f"Agent 结束（退出码 {result.returncode}）但未在 exports/ 产出 PPTX；请查看执行日志"
        _update(job_pk, status="failed", stage="失败", finished_at=_now(), duration_ms=duration_ms,
                error_message=msg, outputs=outputs, preview_keys=preview_keys, log_key=log_key,
                log_tail=_tail(log_path), agent_pid=None, params={**params, "_run": extra})
        logger.warning("ppt-master 任务 %s 失败：%s", biz_id, msg)
    except Exception as e:  # noqa: BLE001
        if monitor:
            try:
                monitor.stop()
            except Exception:  # noqa: BLE001
                pass
        logger.exception("ppt-master 任务 %s 执行异常", biz_id)
        duration_ms = int((time.monotonic() - started) * 1000)
        _update(job_pk, status="failed", stage="失败", finished_at=_now(), duration_ms=duration_ms,
                error_message=f"执行异常：{str(e)[:800]}", agent_pid=None,
                log_tail=_tail(log_path) if os.path.exists(log_path) else None)


def cancel_local_process(job: PptMasterJob) -> None:
    """API 侧尽力而为：若 Worker 与 API 同机，直接结束记录的 Agent 进程（Worker 循环也会自行检测取消标记）。"""
    pid = job.agent_pid
    if not pid:
        return
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
    except Exception as e:  # noqa: BLE001
        logger.debug("结束 Agent 进程 pid=%s 失败（可能已退出或不在本机）：%s", pid, e)
