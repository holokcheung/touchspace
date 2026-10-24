from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class TouchspaceSettings:
    upload_token: str
    llm_key: str
    llm_model: str


@lru_cache
def get_touchspace_settings() -> TouchspaceSettings:
    return TouchspaceSettings(
        upload_token=os.environ.get('TOUCHSPACE_UPLOAD_TOKEN', ''),
        llm_key=os.environ.get('TOUCHSPACE_GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEY', ''),
        llm_model=os.environ.get('TOUCHSPACE_GEMINI_MODEL', 'gemini-3.8-flash'),
    )
