"""API 数据传输对象与统一响应包裹。"""
from typing import Any

from pydantic import BaseModel, Field


def ok(data: Any = None) -> dict:
    """统一成功响应包裹：{code: 0, message: "ok", data: ...}"""
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, message: str, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}


class JobCreateReq(BaseModel):
    template_id: str = Field(description="模板 biz_id")
    document_id: str = Field(description="文档 biz_id")
    pages: int = Field(ge=5, le=100)
    mode: str = Field(default="fast", pattern="^(fast|standard|premium)$")
    density: str = Field(default="medium", pattern="^(low|medium|high)$")
    options: dict = Field(default_factory=dict)


class JobRetryReq(BaseModel):
    strategy: str = Field(default="resume", pattern="^(resume|restart|restart_with_input)$")
    document_id: str | None = None
    template_id: str | None = None


class DecisionReq(BaseModel):
    choice: str
