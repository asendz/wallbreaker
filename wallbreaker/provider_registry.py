from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path

from .config import Config, ConfigError, Endpoint

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROTOCOLS = {"openai", "anthropic", "claude-code"}
_ENDPOINT_FIELDS = tuple(field.name for field in dataclasses.fields(Endpoint))
_TABLE_RE = re.compile(r"(?m)^[ \t]*\[\[?[^\r\n]+?\]\]?[ \t]*(?:#.*)?$")
_PROFILE_RE = re.compile(
    r'(?m)^[ \t]*\[profiles\.(?P<name>"(?:[^"\\]|\\.)*"|[A-Za-z0-9_-]+)\][ \t]*(?:#.*)?$'
)


def env_path_for(config: Config) -> Path:
    base = config.path.parent if config.path else Path.cwd()
    return base / ".env"


def _endpoint_data(endpoint: Endpoint) -> dict:
    data = dataclasses.asdict(endpoint)
    data.pop("api_key", None)
    data["provider"] = list(data.get("provider") or [])
    data["has_api_key"] = bool(endpoint.resolved_key())
    return data


def _normalize(name: str, body: dict, current: Endpoint | None = None) -> Endpoint:
    if not _NAME_RE.fullmatch(name):
        raise ConfigError("Provider name must use letters, numbers, dot, dash, or underscore")
    base = dataclasses.asdict(current) if current else {}
    base.update({key: value for key, value in body.items() if key in _ENDPOINT_FIELDS})
    protocol = str(base.get("protocol") or "").lower()
    if protocol not in _PROTOCOLS:
        raise ConfigError("protocol must be openai, anthropic, or claude-code")
    model = str(base.get("model") or "").strip()
    base_url = str(base.get("base_url") or "").strip().rstrip("/")
    if protocol != "claude-code" and not base_url:
        raise ConfigError("base_url is required")
    provider = base.get("provider") or ()
    if isinstance(provider, str):
        provider = tuple(part.strip() for part in provider.split(",") if part.strip())
    else:
        provider = tuple(str(part) for part in provider)
    return Endpoint(
        name=name,
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key_env=str(base.get("api_key_env") or ""),
        api_key=str(base.get("api_key") or ""),
        provider=provider,
        timeout=float(base.get("timeout") or 0),
        modality=str(base.get("modality") or "text"),
        reasoning=bool(base.get("reasoning", False)),
        system_mode=str(base.get("system_mode") or "default"),
        system_prompt_file=str(base.get("system_prompt_file") or ""),
        auth_style=str(base.get("auth_style") or "x-api-key"),
        inference_path=str(base.get("inference_path") or ""),
        models_path=str(base.get("models_path") or ""),
    )


def _set_env(path: Path, key: str, value: str) -> None:
    if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ConfigError("A valid api_key_env is required when saving an API key")
    from dotenv import set_key

    path.touch(exist_ok=True)
    set_key(str(path), key, value, quote_mode="always")
    os.environ[key] = value


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _profile_block(name: str, endpoint: Endpoint, enabled: bool) -> str:
    values: list[tuple[str, object]] = [
        ("protocol", endpoint.protocol),
        ("base_url", endpoint.base_url),
        ("api_key_env", endpoint.api_key_env),
        ("model", endpoint.model),
    ]
    if endpoint.api_key and not endpoint.api_key_env:
        values.append(("api_key", endpoint.api_key))
    if endpoint.provider:
        values.append(("provider", list(endpoint.provider)))
    if endpoint.timeout:
        values.append(("timeout", endpoint.timeout))
    if endpoint.modality != "text":
        values.append(("modality", endpoint.modality))
    if endpoint.reasoning:
        values.append(("reasoning", True))
    if endpoint.system_mode != "default":
        values.append(("system_mode", endpoint.system_mode))
    if endpoint.system_prompt_file:
        values.append(("system_prompt_file", endpoint.system_prompt_file))
    if endpoint.auth_style != "x-api-key":
        values.append(("auth_style", endpoint.auth_style))
    if endpoint.inference_path:
        values.append(("inference_path", endpoint.inference_path))
    if endpoint.models_path:
        values.append(("models_path", endpoint.models_path))
    if not enabled:
        values.append(("enabled", False))
    lines = [f"[profiles.{json.dumps(name, ensure_ascii=False)}]"]
    lines.extend(f"{key} = {_toml_value(value)}" for key, value in values if value != "")
    return "\n".join(lines) + "\n"


def _profile_span(text: str, name: str) -> tuple[int, int] | None:
    for match in _PROFILE_RE.finditer(text):
        raw_name = match.group("name")
        parsed_name = json.loads(raw_name) if raw_name.startswith('"') else raw_name
        if parsed_name != name:
            continue
        next_table = _TABLE_RE.search(text, match.end())
        return match.start(), next_table.start() if next_table else len(text)
    return None


def _persist_profile(config: Config, name: str, endpoint: Endpoint | None, enabled: bool = True) -> None:
    if config.path is None:
        return
    path = Path(config.path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = f"default_profile = {_toml_value(config.default_profile)}\n\n"
        for existing_name, existing_endpoint in config.all_profiles.items():
            if existing_name != name:
                text += _profile_block(
                    existing_name,
                    existing_endpoint,
                    existing_name not in config.disabled_profiles,
                ) + "\n"
    span = _profile_span(text, name)
    block = _profile_block(name, endpoint, enabled) + "\n" if endpoint is not None else ""
    if span:
        text = text[:span[0]] + block + text[span[1]:]
    elif endpoint is not None:
        text = text.rstrip() + "\n\n" + block
    default_line = f"default_profile = {_toml_value(config.default_profile)}"
    if re.search(r"(?m)^default_profile\s*=.*$", text):
        text = re.sub(r"(?m)^default_profile\s*=.*$", default_line, text, count=1)
    else:
        text = default_line + "\n\n" + text.lstrip()
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        self.env_path = env_path_for(config)
        self.attach_catalog_context()

    def attach_catalog_context(self) -> None:
        from .model_catalog import attach_catalog, catalog_path_for

        path = catalog_path_for(self.config)
        for name, endpoint in self.config.profiles.items():
            attach_catalog(endpoint, path, name)

    def list(self) -> list[dict]:
        out = []
        for name, endpoint in sorted(self.config.all_profiles.items(), key=lambda item: item[0].casefold()):
            item = _endpoint_data(endpoint)
            item.update({"name": name, "enabled": name not in self.config.disabled_profiles})
            out.append(item)
        return out

    def get(self, name: str) -> dict | None:
        return next((item for item in self.list() if item["name"] == name), None)

    def save(self, name: str, body: dict) -> dict:
        current = self.config.all_profiles.get(name)
        endpoint = _normalize(name, body, current)
        enabled = bool(body.get("enabled", name not in self.config.disabled_profiles))
        if not enabled:
            self._require_unreferenced(name)
        if not enabled and name in self.config.profiles and len(self.config.profiles) == 1:
            raise ConfigError("At least one provider must remain enabled")
        api_key = str(body.get("api_key") or "")
        if api_key:
            _set_env(self.env_path, endpoint.api_key_env, api_key)
        if enabled:
            self.config.profiles[name] = endpoint
            self.config.disabled_profiles.discard(name)
        else:
            self.config.profiles.pop(name, None)
            self.config.disabled_profiles.add(name)
        self.config.all_profiles[name] = endpoint
        if self.config.default_profile not in self.config.profiles and self.config.profiles:
            self.config.default_profile = next(iter(self.config.profiles))
        _persist_profile(self.config, name, endpoint, enabled)
        self.attach_catalog_context()
        return self.get(name) or {}

    def delete(self, name: str) -> None:
        if name not in self.config.all_profiles:
            raise KeyError(name)
        if name in self.config.profiles and len(self.config.profiles) == 1:
            raise ConfigError("At least one provider must remain enabled")
        self._require_unreferenced(name)
        self.config.all_profiles.pop(name)
        self.config.profiles.pop(name, None)
        self.config.disabled_profiles.discard(name)
        if self.config.default_profile == name and self.config.profiles:
            self.config.default_profile = next(iter(self.config.profiles))
        _persist_profile(self.config, name, None)

    def _require_unreferenced(self, name: str) -> None:
        references = []
        for role, profiles in self.config.agent_profiles.items():
            references.extend(f"{role}/{profile.name}" for profile in profiles.values() if profile.provider == name)
        for role, assignment in self.config.active_agents.items():
            if not assignment.profile and assignment.provider == name:
                references.append(f"active {role}")
        if references:
            raise ConfigError(
                f"Provider '{name}' is used by {', '.join(references)}. Reassign those agents before disabling or removing it."
            )
