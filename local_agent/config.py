"""Client configuration. Importing Core never requires credentials."""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Settings:
    base_url: str = 'http://192.168.1.77:4000/v1'
    api_key: str = field(default='', repr=False)
    model: str = 'local-agent-coder'
    data_dir: Path = ROOT
    local_token: str = field(default='', repr=False)
    port: int = 8765
    max_steps: int = 30
    timeout: float = 60

    @classmethod
    def load(cls):
        from .client_config import read_config
        frozen = getattr(sys, 'frozen', False)
        default_dir = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'LocalAgent' if frozen else ROOT
        legacy = {} if frozen else dotenv_values(ROOT / '.env')
        data_dir = Path(os.getenv('AGENT_DATA_DIR', legacy.get('AGENT_DATA_DIR') or str(default_dir))).expanduser().resolve()
        saved = read_config(data_dir)
        def value(env, key, default):
            return os.getenv(env, saved.get(key, legacy.get(env) or default))
        import json
        selected = {}
        try:
            selected = json.loads((data_dir / 'model-selection.json').read_text(encoding='utf-8'))
            if not isinstance(selected, dict):
                selected = {}
        except (OSError, ValueError):
            pass
        endpoint = value('LITELLM_BASE_URL', 'base_url', cls.base_url).rstrip('/')
        preferred = selected.get('model') if selected.get('base_url') == endpoint else None
        return cls(
            base_url=value('LITELLM_BASE_URL', 'base_url', cls.base_url).rstrip('/'),
            api_key=value('LITELLM_API_KEY', 'api_key', ''),
            model=preferred if isinstance(preferred, str) and preferred.strip() else value('AGENT_MODEL', 'model', cls.model),
            data_dir=data_dir,
            local_token=os.getenv('AGENT_LOCAL_TOKEN', legacy.get('AGENT_LOCAL_TOKEN') or ''),
            port=int(os.getenv('AGENT_PORT', legacy.get('AGENT_PORT') or '8765')),
        )

    def validate_model(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid LITELLM_BASE_URL')
        if not self.api_key:
            raise ValueError('Configure this client’s LITELLM_API_KEY (Virtual Key)')
