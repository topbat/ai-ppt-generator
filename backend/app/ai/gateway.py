"""LLM Gateway：Qwen、DeepSeek 与 Kimi 的 OpenAI 兼容接口统一接入。

职责（对应文档 §3.3）：
1. 路由：task_type + mode → (provider, model)，配置化；
2. 限流：Provider 级并发信号量（进程内，多任务共享）；
3. 重试：失败自动重试，最后一次切换备用 Provider；
4. JSON：json_mode 请求 + 本地修复器 + Pydantic 校验；
5. 熔断：Provider 连续失败进入 OPEN 状态，冷却后半开探测；
6. 计量：每次调用落库 llm_calls（provider/model/token/耗时/结果）。
"""
import json
import re
import threading
import time

from openai import APIStatusError, OpenAI

from app.core.config import get_settings, validate_selectable_model
from app.core.errors import PPTError
from app.core.logging import ctx_stage, get_logger

logger = get_logger(__name__)

def provider_of(model: str) -> str:
    """按模型名前缀识别 Provider；未识别的模型走 Qwen(DashScope)。"""
    normalized = model.lower()
    if normalized.startswith("deepseek"):
        return "deepseek"
    if normalized.startswith("kimi"):
        return "kimi"
    return "qwen"


def build_routes() -> dict[str, dict]:
    """任务路由表：task_type -> mode -> (provider, model)；fallback 为备用通道。
    具体模型名全部来自环境变量（LLM_MODEL_*），可不改代码切换模型。"""
    s = get_settings()
    fast = (provider_of(s.llm_model_fast), s.llm_model_fast)
    standard = (provider_of(s.llm_model_standard), s.llm_model_standard)
    premium = (provider_of(s.llm_model_premium), s.llm_model_premium)
    reasoner = (provider_of(s.llm_model_reasoner), s.llm_model_reasoner)
    fallback = (provider_of(s.llm_model_fallback), s.llm_model_fallback)
    vision = (provider_of(s.llm_model_vision), s.llm_model_vision)
    return {
        # 文档理解/页面文案：按模式档位取模型
        "doc_summary":  {"fast": fast, "standard": standard, "premium": premium,
                         "fallback": fallback},
        "page_content": {"fast": fast, "standard": standard, "premium": premium,
                         "fallback": fallback},
        # 大纲规划：极速/标准用标准档，专业用推理模型
        "outline":      {"fast": standard, "standard": standard, "premium": reasoner,
                         "fallback": fallback},
        # 修复改写：专业用推理模型
        "repair":       {"fast": fast, "standard": standard, "premium": reasoner,
                         "fallback": fallback},
        "vision_qa":    {"premium": vision, "fallback": vision},
    }


class _Breaker:
    """简单熔断器：连续 N 次失败 → OPEN 冷却 60s → 半开探测。"""

    def __init__(self, threshold: int = 5, cooldown: float = 60.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0.0
        self.lock = threading.Lock()

    def available(self) -> bool:
        with self.lock:
            return time.monotonic() >= self.open_until

    def record(self, success: bool):
        with self.lock:
            if success:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures >= self.threshold:
                    self.open_until = time.monotonic() + self.cooldown
                    self.failures = 0
                    logger.warning("Provider 触发熔断，冷却 %.0f 秒", self.cooldown)


class LLMGateway:
    def __init__(self):
        s = get_settings()
        self.settings = s
        self._clients: dict[str, OpenAI] = {}
        self._semaphores = {
            "qwen": threading.Semaphore(s.llm_max_concurrency_per_provider),
            "deepseek": threading.Semaphore(s.llm_max_concurrency_per_provider),
            "kimi": threading.Semaphore(s.llm_max_concurrency_per_provider),
        }
        self._breakers = {"qwen": _Breaker(), "deepseek": _Breaker(), "kimi": _Breaker()}
        self.routes = build_routes()
        logger.info("LLM 路由初始化：极速=%s 标准=%s 专业=%s 推理=%s 备用=%s",
                    s.llm_model_fast, s.llm_model_standard, s.llm_model_premium,
                    s.llm_model_reasoner, s.llm_model_fallback)

    def _client(self, provider: str) -> OpenAI:
        if provider not in self._clients:
            s = self.settings
            if provider == "qwen":
                self._clients[provider] = OpenAI(api_key=s.qwen_api_key, base_url=s.qwen_base_url,
                                                 timeout=s.llm_timeout_seconds)
            elif provider == "deepseek":
                self._clients[provider] = OpenAI(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url,
                                                 timeout=s.llm_timeout_seconds)
            elif provider == "kimi":
                self._clients[provider] = OpenAI(api_key=s.kimi_api_key, base_url=s.kimi_base_url,
                                                 timeout=s.llm_timeout_seconds)
            else:
                raise PPTError("E3001", f"未知 Provider: {provider}")
        return self._clients[provider]

    def _route(self, task_type: str, mode: str,
               model_override: str | None = None) -> list[tuple[str, str]]:
        """返回调用顺序：[主通道, 主通道(重试), 备用通道]，熔断中的 Provider 直接跳过。"""
        if model_override:
            model = validate_selectable_model(model_override, self.settings)
            primary = (provider_of(model), model)
            return [primary, primary] if self._breakers[primary[0]].available() else [primary]
        route = self.routes.get(task_type) or self.routes["page_content"]
        primary = route.get(mode) or route.get("standard") or next(iter(route.values()))
        fallback = route.get("fallback")
        chain = [primary, primary]
        if fallback and fallback != primary:
            chain.append(fallback)
        return [c for c in chain if self._breakers[c[0]].available()] or [primary]

    # ---- 核心入口 ----
    def chat_json(self, task_type: str, mode: str, system: str, user: str,
                  job_id: int | None = None, temperature: float = 0.4,
                  max_tokens: int = 4096, model_override: str | None = None) -> dict:
        """要求返回 JSON 对象；内部完成 json 修复与多通道重试。"""
        text = self.chat_text(task_type, mode, system, user, job_id=job_id,
                              temperature=temperature, max_tokens=max_tokens, json_mode=True,
                              model_override=model_override)
        obj = repair_json(text)
        if obj is None:
            logger.error("JSON 修复失败，原始返回前 300 字: %s", text[:300])
            raise PPTError("E3002", "JSON 解析与修复均失败")
        return obj

    def chat_text(self, task_type: str, mode: str, system: str, user: str,
                  job_id: int | None = None, temperature: float = 0.4,
                  max_tokens: int = 4096, json_mode: bool = False,
                  model_override: str | None = None) -> str:
        if self.settings.llm_mock:
            return _mock_response(task_type, user)

        chain = self._route(task_type, mode, model_override)
        last_error: Exception | None = None
        for i, (provider, model) in enumerate(chain):
            is_fallback = i == len(chain) - 1 and len(chain) > 1 and chain[i] != chain[0]
            started = time.monotonic()
            error_type = None
            try:
                with self._semaphores[provider]:  # Provider 级并发限流（全局共享）
                    kwargs: dict = dict(
                        model=model,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": user}],
                        temperature=temperature, max_tokens=max_tokens,
                    )
                    # deepseek-reasoner 不支持 json_object/temperature 等参数
                    if json_mode and model != "deepseek-reasoner":
                        kwargs["response_format"] = {"type": "json_object"}
                    if model == "deepseek-reasoner":
                        kwargs.pop("temperature", None)
                    # Qwen3 系混合思考模型：结构化任务显式关闭思考，显著降低时延
                    if provider == "qwen" and "vl" not in model:
                        kwargs["extra_body"] = {"enable_thinking": False}
                    resp = self._do_call(provider, kwargs)
                content = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                self._breakers[provider].record(True)
                self._log_call(job_id, task_type, provider, model, usage,
                               int((time.monotonic() - started) * 1000),
                               "fallback" if is_fallback else "success", None)
                logger.info("LLM 调用成功 task=%s provider=%s model=%s 耗时=%.1fs",
                            task_type, provider, model, time.monotonic() - started)
                return content
            except APIStatusError as e:
                # 内容安全拦截：不重试，直接抛业务错误
                if e.status_code == 400 and "content" in str(e).lower() and "filter" in str(e).lower():
                    raise PPTError("E3005", str(e)) from e
                error_type = f"http_{e.status_code}"
                last_error = e
            except Exception as e:
                error_type = type(e).__name__
                last_error = e
            # 失败路径统一处理
            self._breakers[provider].record(False)
            self._log_call(job_id, task_type, provider, model, None,
                           int((time.monotonic() - started) * 1000), "failed", error_type)
            logger.warning("LLM 调用失败(第%d通道) task=%s provider=%s model=%s: %s",
                           i + 1, task_type, provider, model, last_error)
        raise PPTError("E3001", f"全部通道失败: {last_error}")

    def _do_call(self, provider: str, kwargs: dict):
        """执行调用；个别模型不认 enable_thinking 参数时自动去掉重试一次。"""
        try:
            return self._client(provider).chat.completions.create(**kwargs)
        except APIStatusError as e:
            if e.status_code == 400 and "extra_body" in kwargs and "thinking" in str(e).lower():
                logger.info("模型不支持 enable_thinking 参数，去掉后重试")
                kwargs = {k: v for k, v in kwargs.items() if k != "extra_body"}
                return self._client(provider).chat.completions.create(**kwargs)
            raise

    def _log_call(self, job_id, task_type, provider, model, usage, duration_ms, status, error_type):
        """调用计量落库；失败不影响主流程。"""
        try:
            from app.core.database import db_session
            from app.models.models import LLMCall
            with db_session() as db:
                db.add(LLMCall(
                    job_id=job_id, stage_code=ctx_stage.get(), task_type=task_type,
                    provider=provider, model=model,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    duration_ms=duration_ms, status=status, error_type=error_type,
                ))
        except Exception as e:
            logger.warning("LLM 计量落库失败(忽略): %s", e)


# ---- JSON 修复器：处理大模型常见的格式瑕疵 ----
def repair_json(text: str) -> dict | None:
    if not text:
        return None
    # 1) 剥离 markdown 代码围栏
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    # 2) 截取首个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    text = text[start:end + 1]
    for candidate in (text, re.sub(r",\s*([}\]])", r"\1", text)):  # 3) 去尾逗号再试
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def _mock_response(task_type: str, user: str) -> str:
    """Mock 模式：无 API Key 的本地联调用。

    从提示词中解析章节名/页码，返回结构合法的占位内容，保证整条流水线
    （大纲→规划→内容→渲染→质检→归档）可完整走通。仅用于联调，内容无业务含义。
    """
    if task_type in ("outline", "doc_summary"):
        chapters = re.findall(r"【章节\d+：(.+?)】", user) or re.findall(r"【(.+?)】", user)
        chapters = [c[:20] for c in chapters[:6]] or ["项目背景", "建设方案", "实施计划"]
        if task_type == "doc_summary":
            return json.dumps({"chapters": [{"title": c, "summary": f"{c}（Mock 摘要）",
                                             "key_points": ["要点一", "要点二"]} for c in chapters]},
                              ensure_ascii=False)
        return json.dumps({"outline": [{"chapter": c, "pages": 2, "summary": f"{c}（Mock）",
                                        "source_chapter_idx": i + 1}
                                       for i, c in enumerate(chapters)],
                           "slides": []}, ensure_ascii=False)
    if task_type == "page_content":
        page_nos = sorted({int(x) for x in re.findall(r"第\s*(\d+)\s*页", user)})
        slides = [{"page": p, "type": "title_content", "title": f"Mock 页面 {p}", "subtitle": None,
                   "elements": [{"type": "bullet_group",
                                 "items": ["Mock 模式占位要点（未配置 LLM Key）",
                                           "配置 QWEN_API_KEY、DEEPSEEK_API_KEY 或 KIMI_API_KEY 后生成真实内容"]}]}
                  for p in page_nos] or [{"page": 1, "type": "title_content", "title": "Mock",
                                          "elements": []}]
        # generate_page 期望单页对象；generate_chapter_batch 期望 {"slides": [...]}
        return json.dumps(slides[0] if len(slides) == 1 else {"slides": slides}, ensure_ascii=False)
    if task_type == "repair":
        # 修复 Agent 期望与输入同结构：把提示词内嵌的页面 JSON 原样返回
        embedded = repair_json(user)
        if embedded:
            return json.dumps(embedded, ensure_ascii=False)
    return json.dumps({"slides": [], "mock": True}, ensure_ascii=False)


_gateway: LLMGateway | None = None
_gateway_lock = threading.Lock()


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        with _gateway_lock:
            if _gateway is None:
                _gateway = LLMGateway()
    return _gateway
