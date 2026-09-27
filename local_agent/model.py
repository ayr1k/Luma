"""OpenAI-compatible LAN transport; no filesystem operations on the host."""
from openai import OpenAI
from .tool_schema import TOOLS
from .preferences import Preferences, allowed_tools
from .streaming import StreamCancelled

class LANModel:
    def __init__(self, settings, options=None):
        self.settings = settings
        self.options = options or Preferences()
        self.extension_tools = set()

    def _client(self):
        self.settings.validate_model()
        return OpenAI(base_url=self.settings.base_url, api_key=self.settings.api_key,
                      timeout=self.options.timeout, max_retries=0)

    def complete(self, messages):
        with self._client() as client:
            names = allowed_tools(self.options) | self.extension_tools
            tools = [t for t in TOOLS if t['function']['name'] in names]
            kwargs = dict(model=self.settings.model, messages=messages,
                          temperature=self.options.temperature, top_p=self.options.top_p,
                          max_tokens=self.options.max_tokens)
            if self.options.mode != 'chat' or self.options.web_enabled or self.extension_tools:
                kwargs.update(tools=tools, tool_choice='auto', parallel_tool_calls=False)
            if self.options.reasoning_effort != 'default':
                kwargs['reasoning_effort'] = self.options.reasoning_effort
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.model_dump(exclude_none=True)

    def list_models(self):
        with self._client() as client:
            return sorted({m.id for m in client.models.list().data if isinstance(m.id, str) and m.id.strip()})

    def stream_complete(self, messages, on_text, cancel_event, on_reasoning=None):
        """Assemble streamed tool arguments; never execute incomplete calls."""
        names = allowed_tools(self.options) | self.extension_tools
        kwargs = dict(model=self.settings.model, messages=messages, stream=True,
                      temperature=self.options.temperature, top_p=self.options.top_p,
                      max_tokens=self.options.max_tokens)
        if self.options.mode != 'chat' or self.options.web_enabled or self.extension_tools:
            kwargs.update(tools=[t for t in TOOLS if t['function']['name'] in names],
                          tool_choice='auto', parallel_tool_calls=False)
        if self.options.reasoning_effort != 'default':
            kwargs['reasoning_effort'] = self.options.reasoning_effort
        content, calls, reason = [], {}, None
        reasoning = []
        with self._client() as client:
            with client.chat.completions.create(**kwargs) as stream:
                for chunk in stream:
                    if cancel_event.is_set():
                        raise StreamCancelled()
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.index != 0:
                        continue
                    delta = choice.delta
                    thought = getattr(delta, 'reasoning_content', None) or getattr(delta, 'thinking', None)
                    if isinstance(thought, str) and thought:
                        reasoning.append(thought)
                        if on_reasoning:
                            on_reasoning(thought)
                    if delta.content:
                        content.append(delta.content)
                        on_text(delta.content)
                    for part in delta.tool_calls or []:
                        call = calls.setdefault(part.index, {'id': '', 'type': 'function',
                            'function': {'name': '', 'arguments': ''}})
                        if part.id:
                            call['id'] += part.id
                        if part.function:
                            call['function']['name'] += part.function.name or ''
                            call['function']['arguments'] += part.function.arguments or ''
                    if choice.finish_reason:
                        reason = choice.finish_reason
        if cancel_event.is_set():
            raise StreamCancelled()
        if reason not in {'stop', 'tool_calls'}:
            raise RuntimeError('Model stream was interrupted or reached its output limit')
        result = {'role': 'assistant', 'content': ''.join(content) or None}
        if reasoning:
            result['reasoning_content'] = ''.join(reasoning)
        if calls:
            if reason != 'tool_calls' or any(not c['id'] or not c['function']['name'] for c in calls.values()):
                raise RuntimeError('Incomplete streamed tool call')
            result['tool_calls'] = [calls[i] for i in sorted(calls)]
        return result

    def check(self, inference=False):
        with self._client() as client:
            models = [m.id for m in client.models.list().data]
            if self.settings.model not in models:
                return {'ok': False, 'models': models, 'detail': 'Configured model is not visible to this key'}
            if inference:
                client.chat.completions.create(model=self.settings.model,
                    messages=[{'role': 'user', 'content': 'Reply with OK.'}], max_tokens=8)
            return {'ok': True, 'models': models, 'inference_tested': inference}
