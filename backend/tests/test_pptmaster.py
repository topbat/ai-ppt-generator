"""ppt-master 集成模块冒烟（不依赖 DB/Redis/MinIO/Agent）：目录/提示词/运行器/Mock 端到端/进度启发式。

运行：cd backend && python tests/test_pptmaster.py
"""
import json
import os
import shutil
import sys
import tempfile
import asyncio
import inspect
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pptmaster import catalog  # noqa: E402
from app.pptmaster.prompt import build_prompt  # noqa: E402
from app.pptmaster.runner import (AgentInfo, ClaudeRunner, CodexRunner, MockRunner,  # noqa: E402
                                  agent_env, detect_agents)
from app.pptmaster import service as pptmaster_service  # noqa: E402
from app.pptmaster.service import _ProgressMonitor, _classify_pptx  # noqa: E402


@contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def test_catalog():
    assert {"files", "topic", "text", "url"} == catalog.VALID["input_mode"]
    assert len(catalog.STYLES) == 21          # auto + template lock + 18 内置 + custom
    assert len(catalog.CANVAS_FORMATS) == 8
    assert {"pyramid", "narrative", "instructional", "showcase", "briefing", "auto"} == catalog.VALID["narrative_mode"]
    assert catalog.ROUTE_BY_KEY["template_fill"]["needs_template"]
    assert catalog.ROUTE_BY_KEY["image_to_pptx"]["agents"] == ["codex"]
    print("[ok] catalog")


def test_template_fill_style_is_locked_by_backend_and_prompt():
    assert "template" in catalog.VALID["style"]
    prompt = build_prompt(
        "pm_template",
        {"input_mode": "topic", "topic": "年度复盘", "route": "template_fill", "style": "template"},
        [],
        "projects/pm_template/sources/company.pptx",
    )
    assert "完全由上传的 PPTX 模板决定" in prompt
    assert "不得改动模板" in prompt


def test_prompt():
    params = {"input_mode": "files", "route": "generate", "profile": "quick", "pages": 8,
              "canvas": "ppt169", "style": "swiss-minimal", "narrative_mode": "pyramid",
              "reading_mode": "presentation", "language": "zh", "image_source": "none",
              "native_charts": True, "speaker_notes": True, "extra_instructions": "封面用公司蓝"}
    p = build_prompt("pm_20260817_abc123", params, ["projects/pm_20260817_abc123/sources/a.pdf"], None)
    for must in ("quick-generate", "projects/pm_20260817_abc123/sources/a.pdf", "正好 8 页", "swiss-minimal",
                 "pyramid", "presentation", "输出语言：中文", "不使用外部图片", "--native-charts-and-tables",
                 "讲者备注", "封面用公司蓝", "DONE:", "FAILED:", "exports/"):
        assert must in p, must
    assert "旁白" not in p.split("参数要求")[1].split("附加要求")[0]
    # 模板路线 / 美化路线 / 主题模式
    p2 = build_prompt("pm_x", {"input_mode": "files", "route": "template_fill", "profile": "quick"},
                      ["projects/pm_x/sources/m.docx"], "projects/pm_x/sources/tpl.pptx")
    assert "template-fill-pptx" in p2 and "tpl.pptx" in p2
    p3 = build_prompt("pm_x", {"input_mode": "files", "route": "beautify", "profile": "default"},
                      ["projects/pm_x/sources/old.pptx"], None)
    assert "beautify-pptx" in p3 and "1:1" in p3
    p4 = build_prompt("pm_x", {"input_mode": "topic", "topic": "碳中和路线图", "route": "generate"}, [], None)
    assert "topic-research" in p4 and "碳中和路线图" in p4
    p5 = build_prompt("pm_x", {"input_mode": "text", "text": "hello", "route": "generate"}, [], None)
    assert "<<<MATERIAL>>>" in p5
    print("[ok] prompt")


def test_runner_cmds():
    c = ClaudeRunner("claude", "opus").build_cmd("提示", "/repo")
    assert c[:2] == ["claude", "-p"] and "--output-format" in c and "stream-json" in c \
        and "--dangerously-skip-permissions" in c and "--model" in c
    x = CodexRunner("codex", None).build_cmd("提示", "/repo")
    assert x[:3] == ["codex", "exec", "--json"] and "-C" in x and x[-1] == "提示"
    # 最终文本解析
    r = ClaudeRunner("claude")
    from app.pptmaster.runner import RunResult
    rr = RunResult(0)
    r.extract_final([{"type": "assistant", "message": {"content": [{"type": "text", "text": "工作中"}]}},
                     {"type": "result", "result": "DONE: projects/x/exports/a.pptx", "total_cost_usd": 1.2,
                      "num_turns": 7}], rr)
    assert rr.final_text.startswith("DONE:") and rr.cost_usd == 1.2 and rr.num_turns == 7
    agents = {a.key: a for a in detect_agents(force=True)}
    assert agents["mock"].available
    print("[ok] runner cmds; agents:", {k: v.available for k, v in agents.items()})


def test_worker_resolves_requested_agent():
    assert hasattr(pptmaster_service, "resolve_worker_agent"), \
        "Agent 必须在 pptmaster-worker 内解析，而不是在 API 容器内解析"
    available = [
        AgentInfo("claude", "Claude", True, "/usr/bin/claude", "test"),
        AgentInfo("codex", "Codex", False, None, "missing"),
        AgentInfo("mock", "Mock", True, None, "builtin"),
    ]
    with patched(pptmaster_service, "detect_agents", lambda force=False: available):
        info = pptmaster_service.resolve_worker_agent("auto")
    assert info.key == "claude" and info.bin == "/usr/bin/claude"
    print("[ok] worker-side agent resolution")


def test_api_defers_agent_availability_to_worker():
    from app.api import pptmaster_api
    from app.services import storage as storage_module
    from app import worker as worker_module

    class FakeStorage:
        def put_bytes(self, *_args, **_kwargs):
            return None

    class FakeDb:
        job = None

        def add(self, job):
            self.job = job

        def commit(self):
            return None

        def refresh(self, job):
            job.id = 1

    kwargs = {}
    for name, param in inspect.signature(pptmaster_api.create_job).parameters.items():
        default = param.default
        kwargs[name] = getattr(default, "default", default)
    db = FakeDb()
    kwargs.update({
        "input_mode": "topic", "topic": "控制面回归测试", "route": "generate",
        "profile": "quick", "pages": "1", "agent": "claude", "model": "qwen3.7-plus",
        "files": [], "template": None, "db": db,
    })
    unavailable = lambda *_args: (_ for _ in ()).throw(ValueError("API 容器无 Claude CLI"))
    with patched(pptmaster_api, "select_agent", unavailable), \
            patched(storage_module, "get_storage", lambda: FakeStorage()), \
            patched(worker_module.pptmaster_generate, "delay", lambda _job_id: None):
        result = asyncio.run(pptmaster_api.create_job(**kwargs))
    assert result["code"] == 0, result
    assert db.job.agent == "claude"
    assert db.job.params["agent_requested"] == "claude"
    print("[ok] API defers Agent availability to worker")


def test_api_requires_configured_model_and_forces_template_style():
    from app.api import pptmaster_api
    from app.services import storage as storage_module
    from app import worker as worker_module

    class FakeStorage:
        def put_bytes(self, *_args, **_kwargs):
            return None

    class FakeDb:
        job = None

        def add(self, job):
            self.job = job

        def commit(self):
            return None

        def refresh(self, job):
            job.id = 1

    class FakeUpload:
        filename = "company.pptx"

        async def read(self):
            return b"pptx-template"

    def kwargs_for(**overrides):
        kwargs = {}
        for name, param in inspect.signature(pptmaster_api.create_job).parameters.items():
            default = param.default
            kwargs[name] = getattr(default, "default", default)
        kwargs.update({
            "input_mode": "topic", "topic": "年度复盘", "route": "template_fill",
            "profile": "quick", "pages": "8", "agent": "claude", "files": [],
            "template": FakeUpload(), "db": FakeDb(),
        })
        kwargs.update(overrides)
        return kwargs

    invalid = asyncio.run(pptmaster_api.create_job(**kwargs_for(model="qwen-max")))
    assert invalid["code"] == 1001 and "可选模型" in invalid["message"]

    valid_kwargs = kwargs_for(model="qwen3.8-max", style="swiss-minimal")
    db = valid_kwargs["db"]
    with patched(storage_module, "get_storage", lambda: FakeStorage()), \
            patched(worker_module.pptmaster_generate, "delay", lambda _job_id: None):
        result = asyncio.run(pptmaster_api.create_job(**valid_kwargs))
    assert result["code"] == 0, result
    assert db.job.model == "qwen3.8-max"
    assert db.job.params["style"] == "template"


def test_options_reports_worker_managed_capabilities():
    from app.api import pptmaster_api

    settings = SimpleNamespace(
        pptmaster_execution_scope="worker", pptmaster_default_agent="auto",
        pptmaster_max_files=10, pptmaster_max_upload_mb=200,
        pptmaster_timeout_minutes=40, pptmaster_timeout_max_minutes=120,
        llm_selectable_models="deepseek-v4,qwen3.7-plus,qwen3.8-max",
        llm_default_selectable_model="qwen3.7-plus",
        pptmaster_max_concurrent_jobs=3,
    )
    unavailable = [
        AgentInfo("claude", "Claude", False, None, "API missing"),
        AgentInfo("codex", "Codex", False, None, "API missing"),
        AgentInfo("mock", "Mock", True, None, "builtin"),
    ]
    old_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        with patched(pptmaster_api, "get_settings", lambda: settings), \
                patched(pptmaster_api, "repo_ready", lambda: (False, None)), \
                patched(pptmaster_api, "detect_agents", lambda: unavailable):
            result = pptmaster_api.get_options()
    finally:
        if old_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old_key
    data = result["data"]
    agents = {a["key"]: a for a in data["agents"]}
    assert data.get("execution_scope") == "worker", data
    assert data["repo"].get("delegated") is True
    assert agents["claude"]["available"] is True
    assert data["default_agent"] == "claude"
    assert data["models"] == ["deepseek-v4", "qwen3.7-plus", "qwen3.8-max"]
    assert data["default_model"] == "qwen3.7-plus"
    print("[ok] options reports worker-managed capabilities")


def test_agent_env_normalizes_anthropic_base_url():
    old = os.environ.get("ANTHROPIC_BASE_URL")
    os.environ["ANTHROPIC_BASE_URL"] = "gateway.example.com"
    try:
        env = agent_env("/repo")
        assert env["ANTHROPIC_BASE_URL"] == "https://gateway.example.com"
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_BASE_URL", None)
        else:
            os.environ["ANTHROPIC_BASE_URL"] = old
    print("[ok] anthropic base url normalization")


def test_pptmaster_image_runs_as_non_root():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    stage = dockerfile.split("FROM worker-base AS pptmaster-worker", 1)[1]
    assert "USER pptmaster" in stage, \
        "pptmaster-worker 必须以非 root 用户运行，否则 Claude Code 会拒绝 --dangerously-skip-permissions"
    print("[ok] pptmaster-worker runs as non-root")


def test_mock_end_to_end():
    tmp = tempfile.mkdtemp(prefix="pm_test_")
    try:
        repo = os.path.join(tmp, "repo")
        proj = os.path.join(repo, "projects", "pm_test")
        os.makedirs(proj)
        log = os.path.join(proj, "agent.log")
        events = []
        runner = MockRunner(project_dir=proj, pages=4, title="单测")
        res = runner.run("prompt", repo, dict(os.environ), log,
                         on_line=lambda raw, ev: events.append(ev), should_cancel=lambda: False,
                         timeout_s=60)
        assert res.returncode == 0 and res.final_text.startswith("DONE:")
        exports = [f for f in os.listdir(os.path.join(proj, "exports")) if f.endswith(".pptx")]
        assert len(exports) == 1
        svgs = sorted(os.listdir(os.path.join(proj, "svg_output")))
        assert svgs == ["P01.svg", "P02.svg", "P03.svg", "P04.svg"]
        assert len(events) == 4 and events[-1]["page"] == 4
        from pptx import Presentation
        assert len(Presentation(os.path.join(proj, "exports", exports[0])).slides) == 4
        # 取消
        proj2 = os.path.join(repo, "projects", "pm_cancel")
        os.makedirs(proj2)
        res2 = MockRunner(project_dir=proj2, pages=6).run("p", repo, dict(os.environ),
                                                            os.path.join(proj2, "agent.log"),
                                                            should_cancel=lambda: True, timeout_s=60)
        assert res2.canceled
        print("[ok] mock end-to-end")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_progress_heuristics():
    m = _ProgressMonitor.__new__(_ProgressMonitor)  # 不启动线程，只测静态映射
    st = _ProgressMonitor._stage_from_tool
    assert st("Bash", {"command": "python3 skills/ppt-master/scripts/svg_to_pptx.py projects/x"}) == "编译导出 PPTX"
    assert st("Write", {"file_path": "projects/x/svg_output/P07.svg"}) == "撰写第 7 页 SVG"
    assert st("Bash", {"command": "python3 scripts/source_to_md.py a.pdf"}) == "转换材料为 Markdown"
    assert st("Read", {"file_path": "skills/ppt-master/SKILL.md"}) == "读取 ppt-master 工作流"
    assert st("Bash", {"command": "ls"}) is None
    assert _classify_pptx("deck_20260817_native_charts_tables.pptx") == "pptx_native"
    assert _classify_pptx("deck_narrated.pptx") == "pptx_narrated"
    assert _classify_pptx("deck.pptx") == "pptx"
    # 事件驱动进度（mock_progress / claude assistant tool_use）
    tmp = tempfile.mkdtemp(prefix="pm_mon_")
    try:
        mon = _ProgressMonitor(0, tmp, os.path.join(tmp, "agent.log"), 10)
        mon.on_line("", {"type": "mock_progress", "page": 5, "total": 10})
        assert mon.progress == 50 and "第 5" in mon.stage
        mon.on_line("", {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "python3 x/svg_quality_checker.py p"}}]}})
        assert mon.stage == "SVG 质量检查"
        os.makedirs(os.path.join(tmp, "svg_output"))
        for i in range(1, 11):
            open(os.path.join(tmp, "svg_output", f"P{i:02d}.svg"), "w").close()
        os.makedirs(os.path.join(tmp, "exports"))
        open(os.path.join(tmp, "exports", "a.pptx"), "w").close()
        mon._scan()
        assert mon.progress == 95 and "导出" in mon.stage
        print("[ok] progress heuristics")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_catalog()
    test_prompt()
    test_runner_cmds()
    test_worker_resolves_requested_agent()
    test_api_defers_agent_availability_to_worker()
    test_options_reports_worker_managed_capabilities()
    test_agent_env_normalizes_anthropic_base_url()
    test_pptmaster_image_runs_as_non_root()
    test_mock_end_to_end()
    test_progress_heuristics()
    print("ALL PASSED")
