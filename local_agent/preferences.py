"""Validated, non-secret desktop preferences and execution policy."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .storage import atomic_json

class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    mode: Literal['chat', 'plan', 'work'] = 'work'
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    max_tokens: int = Field(default=4096, ge=128, le=32768)
    max_steps: int = Field(default=30, ge=1, le=100)
    no_tool_limit: int = Field(default=6, ge=3, le=20)
    reasoning_effort: Literal['default', 'none', 'low', 'medium', 'high'] = 'default'
    timeout: int = Field(default=120, ge=10, le=600)
    web_enabled: bool = False
    search_results: int = Field(default=5, ge=1, le=10)
    theme: Literal['dark', 'light', 'system'] = 'dark'
    font_size: int = Field(default=14, ge=12, le=20)
    enter_send: bool = False

def load_preferences(root):
    path = root / 'preferences.json'
    try:
        return Preferences.model_validate_json(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return Preferences()

def save_preferences(root, value):
    atomic_json(root / 'preferences.json', value.model_dump())

def allowed_tools(options):
    names = {'finish'}
    if options.mode in {'plan', 'work'}:
        names |= {'list_files', 'read_file', 'search_files', 'git_diff'}
    if options.mode == 'work':
        names |= {'write_file', 'apply_patch', 'run_command'}
    if options.web_enabled:
        names.add('web_search')
    return names
