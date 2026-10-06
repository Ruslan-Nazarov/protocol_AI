"""Small text-only provider adapter; credentials never leave the server contract."""
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


def credentials(root: Path) -> dict:
    """Read only documented key/model names; project env > process > neighbours."""
    allowed = {key for _, key in PROVIDERS.values()} | {p.upper() + "_MODEL" for p in PROVIDERS}
    values = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    paths = [root / ".env", root.parent / "dialecticalai/.env",
             root.parent / "conspect/conspect/.env"]
    for index, path in enumerate(paths):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=\s*(.*)", line)
            if not match or match[1] not in allowed:
                continue
            value = match[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].strip()
            if value and (index == 0 or match[1] not in values):
                values[match[1]] = value
    return values


def saved_connection(root: Path) -> dict | None:
    """Read the user's editor connection without starting an editor worker."""
    path = root / 'data/editor-settings.json'
    if not path.is_file():
        return None
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Недопустимый путь настроек ИИ.')
    from protocol_atlas.editor_ai import DEFAULT_SETTINGS
    settings = {**DEFAULT_SETTINGS, **json.loads(path.read_text(encoding='utf-8'))}
    if not settings['api_key'] and settings['provider'] in PROVIDERS:
        settings['api_key'] = credentials(root).get(PROVIDERS[settings['provider']][1], '')
    return settings


def public_providers(root: Path) -> list[dict]:
    values = credentials(root)
    result = [{"id": provider, "configured": bool(values.get(key)),
             "model": values.get(provider.upper() + "_MODEL", ""),
             "endpoint": endpoint, "access_verified": False}
            for provider, (endpoint, key) in PROVIDERS.items()]
    settings = saved_connection(root)
    if settings:
        result.append({'id': 'saved', 'label': 'Мой ИИ',
                       'configured': bool(settings['endpoint'] and settings['model'] and
                           (settings['provider'] == 'custom' or settings['api_key'])),
                       'model': settings['model'], 'endpoint': settings['endpoint'], 'access_verified': False})
    return result


def call_model(root: Path, provider: str, model: str, messages: list[dict], max_output: int, json_mode=False) -> dict:
    if provider == 'saved':
        from protocol_atlas.editor_ai import model_call
        settings = saved_connection(root)
        if not settings or model != settings['model']:
            raise ValueError('Подключение «Мой ИИ» изменилось. Обновите настройки испытания.')
        result = model_call({**settings, 'max_output': max_output, 'json_mode': json_mode}, messages)
        key = settings.get('api_key', '')
        actual = result.get('model')
        if key and isinstance(actual, str):
            actual = actual.replace(key, '[REDACTED]')
        return {'text': result['text'], 'actual_model': actual, 'finish_reason': result.get('finish_reason'),
                'input_tokens': result.get('input_tokens'), 'output_tokens': result.get('output_tokens'),
                'request_parameters': {'model': model, 'max_output_tokens': max_output, 'json_mode': json_mode}}
    if provider not in PROVIDERS or not re.fullmatch(r"[A-Za-z0-9_./:\-]{1,160}", model):
        raise ValueError("Выберите поддерживаемый сервис и допустимое имя модели.")
    base, key_name = PROVIDERS[provider]
    values = credentials(root)
    key = values.get(key_name)
    if not key:
        raise ValueError(f"Для {provider} не найден ключ в настройках проекта или соседних проектов.")
    payload = {"model": model, "messages": messages, "stream": False}
    parameter = "max_completion_tokens" if provider in ("openai", "cerebras", "groq") else "max_tokens"
    payload[parameter] = max_output
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    if provider == 'cerebras' and model in ('gpt-oss-120b', 'qwen-3.8-27b'):
        payload['reasoning_format'] = 'parsed'
    if provider == 'groq' and model.startswith(('qwen/', 'openai/gpt-oss-')):
        payload['reasoning_format'] = 'parsed'
    request = urllib.request.Request(base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key,
                 "User-Agent": "protocol-atlas/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A provider error can echo request data. Do not expose its raw body.
        hints = {401: "Ключ не принят сервисом.", 403: "Сервис отклонил доступ.",
                 413: "Сервис отклонил объём одного запроса. Выберите сервис с подходящим пределом входа; материал не сокращается автоматически.",
                 429: "Достигнута квота или предел частоты сервиса."}
        hint = hints.get(exc.code, "Проверьте доступ, модель и квоту сервиса.")
        raise RuntimeError(f"{provider}: HTTP {exc.code}. {hint}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError(f"{provider}: сеть недоступна или превышено время ожидания.") from None
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider}: сервис не вернул ответ модели.")
    redacted = False
    secrets = [value for name, value in values.items() if name.endswith('_API_KEY') and value]
    def redact(value):
        nonlocal redacted
        if isinstance(value, str):
            for secret in secrets:
                if secret in value:
                    value = value.replace(secret, '[REDACTED]')
                    redacted = True
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {redact(name): redact(item) for name, item in value.items()}
        return value
    result = redact(result)
    choices = result['choices']
    usage = result.get("usage") or {}
    return {"text": choices[0].get("message", {}).get("content") or "",
            "actual_model": result.get("model"), "finish_reason": choices[0].get("finish_reason"),
            "usage_raw": usage, "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "request_parameters": {key: value for key, value in payload.items() if key != 'messages'},
            "response_raw": result,
            "credentials_redacted": redacted,
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")}
