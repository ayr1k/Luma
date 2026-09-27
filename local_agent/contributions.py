"""Declarative UI extensions. Packages cannot inject JavaScript, CSS or native code."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Config(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Palette(Config):
    palette: Literal['graphite','white','midnight','warm'] = 'graphite'
    accent: str = Field(default='#b7dbc8', pattern=r'^#[0-9a-fA-F]{6}$')

class Typography(Config):
    ui_font: str = Field(default='Segoe UI', pattern=r'^[\w \-\u3400-\u9fff]{1,80}$')
    body_font: str = Field(default='Microsoft YaHei', pattern=r'^[\w \-\u3400-\u9fff]{1,80}$')
    code_font: str = Field(default='Consolas', pattern=r'^[\w \-\u3400-\u9fff]{1,80}$')
    size: int = Field(default=14, ge=12, le=24)
    line_height: float = Field(default=1.9, ge=1.3, le=2.5)
    width: int = Field(default=780, ge=520, le=1200)

class Icons(Config):
    style: Literal['thin','rounded'] = 'rounded'

class Material(Config):
    opacity: float = Field(default=.88, ge=.7, le=1)
    blur: int = Field(default=12, ge=0, le=20)

class Widget(Config):
    topmost: bool = True

from .native_features import HOTKEYS

class Hotkey(Config):
    shortcut: str = Field(default='Ctrl+Alt+L', json_schema_extra={'enum':list(HOTKEYS)})

    @field_validator('shortcut')
    @classmethod
    def supported_shortcut(cls,value):
        from .native_features import HOTKEYS
        if value not in HOTKEYS:raise ValueError('请选择受支持的快捷键组合')
        return value

class Phrase(Config):
    title: str = Field(min_length=1, max_length=80)
    category: str = Field(default='常用', max_length=40)
    text: str = Field(min_length=1, max_length=8000)

class Snippets(Config):
    phrases: list[Phrase] = Field(default_factory=lambda:[
        Phrase(title='解释这段内容',text='请用清楚易懂的语言解释以下内容，并举一个例子：\n'),
        Phrase(title='检查并改进',category='开发',text='请检查当前实现的问题，先说明原因，再给出最小修改方案。'),
        Phrase(title='总结行动项',text='请总结以下内容，列出关键结论和下一步行动：\n')], max_length=50)

SLOTS = {'palette':('appearance',Palette),'typography':('appearance',Typography),
         'icons':('appearance',Icons),'material':('appearance',Material),
         'widget':('software',Widget),'hotkey':('software',Hotkey),'snippets':('software',Snippets)}

def validate_contribution(manifest):
    c = manifest.get('contribution')
    if not isinstance(c,dict) or set(c)-{'slot','defaults'} or c.get('slot') not in SLOTS:
        raise ValueError('插件需声明受支持的 contribution.slot 和 defaults')
    category, model = SLOTS[c['slot']]
    if manifest.get('category') != category or manifest.get('tools') or manifest.get('skills') or manifest.get('runtime'):
        raise ValueError('声明式插件不能包含工具、Skill 或代码 runtime')
    model.model_validate(c.get('defaults',{}))
    return c

def configuration(manifest, values=None):
    c = validate_contribution(manifest)
    model = SLOTS[c['slot']][1]
    return model.model_validate({**c.get('defaults',{}),**(values or {})}).model_dump()

def schema(manifest):
    return SLOTS[validate_contribution(manifest)['slot']][1].model_json_schema()
