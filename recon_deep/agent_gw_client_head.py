"""Kimi agent-gw 的同步客户端。

覆盖的路由（除标注外均为 POST）：
    GET  /v1/models
    POST /v1/chat/completions       （OpenAI 兼容）
    POST /v1/messages               （Anthropic 兼容）
    POST /v1/messages/count_tokens
    POST /v1/embeddings
    POST /v1/search
    POST /v1/fetch
    POST /v1/files                  （multipart 文件上传，透传到 OpenGW）
    POST /v1/tools                  （分发器：get_stock_realtime_price、nlp_*、call_data_source_tool 等）
"""

from __future__ import annotations

import json as _json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Mapping, Optional, Tuple, Union

import requests

from . import __version__
from .errors import (
    APIError,
    AuthenticationError,
    NotFoundError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    ToolError,
    TransportError,
)

DEFAULT_BASE_URL = "https://agent-gw-dev.dev.kimi.team/coding"
DEFAULT_TIMEOUT = 30.0
DEFAULT_USER_AGENT = f"Kimi AgentGW PySDK/{__version__}"

API_KEY_ENV_VAR = "KIMI_API_KEY"
BASE_URL_ENV_VAR = "KIMI_BASE_URL"
CHAT_ID_ENV_VAR = "KIMI_CHAT_ID"
SESSION_ID_ENV_VAR = "KIMI_SESSION_ID"
THREAD_ID_ENV_VAR = "KIMI_THREAD_ID"
EVENT_ID_ENV_VAR = "KIMI_EVENT_ID"
CONFIG_FILE = Path("~/.kimi/agent-gw.json")  # 用户家目录下的固定路径


def _load_config_file() -> Dict[str, Any]:
    """读 ``~/.kimi/agent-gw.json``，文件不存在返回 ``{}``。

    JSON 必须是 ``{"api_key": "...", "base_url": "..."}`` 形式的对象，否则抛
    ``ValueError`` —— 这是配置错误，不该静默吃掉。
    """
    path = CONFIG_FILE.expanduser()
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(
            f"agent-gw config file {path} exists but could not be read: {e}"
        ) from e
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError as e:
        raise ValueError(
            f"agent-gw config file {path} is not valid JSON: {e}"
        ) from e
    if not isinstance(data, dict):
        raise ValueError(
            f"agent-gw config file {path} must be a JSON object, got {type(data).__name__}"
        )
    return data


def _cfg_str(cfg: Mapping[str, Any], *keys: str) -> Optional[str]:
    """从 ``cfg`` 取首个非空字符串字段（自动 strip），都没值返回 ``None``。"""
    for key in keys:
        v = cfg.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _resolve_api_key(explicit: Optional[str], cfg: Mapping[str, Any]) -> str:
    """``显式参数 > KIMI_API_KEY env > JSON 配置 > 报错``"""
    if explicit:
        return explicit
    env = os.environ.get(API_KEY_ENV_VAR)
    if env and env.strip():
        return env.strip()
    file_val = _cfg_str(cfg, "api_key")
    if file_val:
        return file_val
    raise ValueError(
        "agent-gw API key not provided. Supply it via the api_key= argument, "
        f"the {API_KEY_ENV_VAR} env var, or put it in {CONFIG_FILE} as "
        '{"api_key": "sk-..."}.'
    )


def _resolve_base_url(explicit: Optional[str], cfg: Mapping[str, Any]) -> str:
    """``显式参数 > KIMI_BASE_URL env > JSON 配置 ``base_url`` > DEFAULT_BASE_URL``"""
    if explicit:
        return explicit
    env = os.environ.get(BASE_URL_ENV_VAR)
    if env and env.strip():
        return env.strip()
    file_val = _cfg_str(cfg, "base_url")
    if file_val:
        return file_val
    return DEFAULT_BASE_URL


def _resolve_kimi_chat_id(explicit: Optional[str], cfg: Mapping[str, Any]) -> Optional[str]:
    """``显式参数 > KIMI_CHAT_ID env > JSON 配置 ``kimi_chat_id`` > None``"""
