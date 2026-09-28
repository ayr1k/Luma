from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ProjectCreate(StrictModel):
    path: str = Field(min_length=1)

class ConversationCreate(StrictModel):
    name: str = Field(default='新任务',min_length=1,max_length=80)

class ContextSettings(StrictModel):
    window: int = Field(default=0, ge=0, le=2000000)

class SummaryApply(StrictModel):
    summary: str = Field(min_length=1, max_length=12000)

class DraftInput(StrictModel):
    text: str = Field(default='', max_length=100000)
    attachments: list['AttachmentInput'] = Field(default_factory=list, max_length=4)
    skills: list[str] = Field(default_factory=list, max_length=8)
    plugins: list[str] = Field(default_factory=list, max_length=12)

class ProjectUpdate(StrictModel):
    default_skills: list[str] | None = Field(default=None, max_length=8)
    default_plugins: list[str] | None = Field(default=None, max_length=12)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    pinned: bool | None = None
    archived: bool | None = None

class Project(BaseModel):
    branch_of: str | None = None
    branch_name: str | None = None
    group_id: str | None = None
    session_id: str | None = None
    project_name: str | None = None
    kind: str = 'project'
    status: str = 'idle'
    updated_at: str | None = None
    default_skills: list[str] = Field(default_factory=list)
    default_plugins: list[str] = Field(default_factory=list)
    pinned: bool = False
    archived: bool = False
    match_excerpt: str | None = None
    id: str
    name: str
    path: str
    created_at: str | None = None
    last_opened: str | None = None

class AttachmentInput(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=14000000, repr=False)

class MessageCreate(StrictModel):
    content: str = Field(default='', max_length=100000)
    plugins: list[str] = Field(default_factory=list, max_length=12)
    skills: list[str] = Field(default_factory=list, max_length=8)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=4)

class MessageRevision(StrictModel):
    message_index: int = Field(ge=0)
    content: str = Field(default='', max_length=100000)

class Approval(StrictModel):
    approval_id: str
    allow: bool

class PendingCommand(BaseModel):
    kind: str = "command"
    approval_id: str
    command: str
    workspace: str
    tool_call_id: str
    arguments: str

class Session(BaseModel):
    context_memory: dict[str, Any] | None = None
    summary_candidate: dict[str, Any] | None = None
    summary_error: str | None = None
    context_usage: dict[str, Any] = Field(default_factory=dict)
    branch_origin: dict[str, Any] | None = None
    session_id: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    turn_id: str | None = None
    active_plugins: list[str] = Field(default_factory=list)
    active_skills: list[dict[str, Any]] = Field(default_factory=list)
    workspace: str
    status: Literal['idle', 'paused', 'running', 'waiting_approval', 'completed', 'failed', 'interrupted', 'cancelled']
    visible_messages: list[dict[str, Any]]
    agent_messages: list[dict[str, Any]]
    tool_logs: list[dict[str, Any]]
    pending_command: PendingCommand | None
    agent_changes: dict[str, Any]
    tool_queue: list[dict[str, Any]]
    steps: int
    pause_reason: str | None = None
    no_tool_streak: int

class ReviewSelection(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    revision: str = Field(min_length=64, max_length=64)

class ReviewAction(StrictModel):
    action: Literal['keep', 'revert']
    files: list[ReviewSelection] = Field(min_length=1, max_length=1000)

class ConnectionRequest(StrictModel):
    inference: bool = False

class Configuration(StrictModel):
    base_url: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    remember_key: bool = True

class TaskState(BaseModel):
    id: str
    project_id: str
    running: bool
    cancel_requested: bool
    error: str | None = None
    session: Session

class ModelSelection(StrictModel):
    model: str = Field(min_length=1, max_length=512)

class ExtensionAction(StrictModel):
    config: dict[str, Any] = Field(default_factory=dict)
    action: Literal['rollback','sync-bundled','details','diagnose','validate','export-config','preview-config','import-config','inspect','install','toggle','uninstall','read-skill','save-skill','delete-skill','configure','reset-appearance']
    id: str = Field(default='', max_length=150)
    data: str | None = Field(default=None, max_length=11200000, repr=False)
    directory: str | None = Field(default=None, max_length=2000)
    digest: str | None = Field(default=None, max_length=64)
    enabled: bool = False
    trusted: bool = False
    content: str = Field(default='', max_length=24000)


class GitPath(StrictModel):
    path: str = Field(default='', max_length=4096)

class GitAction(StrictModel):
    action: Literal['init','stage','unstage','commit','identity','switch','branch','suggest','remote-add','remote-edit','remote-remove','fetch','pull','push','test-remote']
    root: str = Field(default='', max_length=4096)
    token: str = Field(default='', max_length=64)
    paths: list[str] = Field(default_factory=list, max_length=1000)
    branch: str = Field(default='', max_length=200)
    message: str = Field(default='', max_length=16000)
    name: str = Field(default='', max_length=200)
    email: str = Field(default='', max_length=320)
    remote: str = Field(default='', max_length=100)
    url: str = Field(default='', max_length=2000)
    remote_token: str = Field(default='', max_length=64)
    global_identity: bool = False
    ignore: bool = False


class GitClone(StrictModel):
    url: str = Field(min_length=1,max_length=2000)
    parent: str = Field(min_length=1,max_length=4096)
    name: str = Field(min_length=1,max_length=100)

class UpdateOptions(StrictModel):
    automatic: bool = True
    channel: Literal['Latest','LTS'] = 'Latest'
