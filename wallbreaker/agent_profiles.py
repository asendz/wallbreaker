from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from .config import AgentAssignment, AgentProfile, Config, ConfigError, Endpoint, resolve_target_modality

ROLES = ("attacker", "target", "judge")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_TABLE_RE = re.compile(r"(?m)^[ \t]*\[\[?[^\r\n]+?\]\]?[ \t]*(?:#.*)?$")


def _toml(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _prompt_text(profile: AgentProfile) -> str:
    if profile.prompt_source == "inline":
        return profile.system_prompt.strip()
    if profile.prompt_source == "file":
        path = Path(profile.system_prompt_file).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Cannot read system prompt file '{path}': {exc}") from exc
    return ""


def normalize_profile(config: Config, role: str, name: str, body: dict) -> AgentProfile:
    if role not in ROLES:
        raise ConfigError(f"Unknown agent role '{role}'")
    if not _NAME_RE.fullmatch(name):
        raise ConfigError("Profile name must use letters, numbers, spaces, dot, dash, or underscore")
    provider = str(body.get("provider", "")).strip()
    model = str(body.get("model", "")).strip()
    source = str(body.get("prompt_source", "none")).lower()
    inline = str(body.get("system_prompt", ""))
    file_name = str(body.get("system_prompt_file", "")).strip()
    if provider not in config.profiles:
        raise ConfigError(f"Unknown or disabled provider '{provider}'")
    if not model:
        raise ConfigError("model is required")
    if source not in ("none", "inline", "file"):
        raise ConfigError("prompt_source must be none, inline, or file")
    if source == "inline" and not inline.strip():
        raise ConfigError("Inline system prompt text is required")
    if source == "file" and not file_name:
        raise ConfigError("System prompt file is required")
    if source == "inline" and file_name:
        raise ConfigError("Inline text and a system prompt file cannot both be set")
    if source == "file" and inline.strip():
        raise ConfigError("Inline text and a system prompt file cannot both be set")
    profile = AgentProfile(name, role, provider, model, source, inline if source == "inline" else "", file_name if source == "file" else "")
    _prompt_text(profile)
    return profile


def _fallback(config: Config, role: str) -> tuple[str, Endpoint]:
    if role == "attacker":
        return config.default_profile, config.profile()
    endpoint = config.target if role == "target" else config.judge
    endpoint = endpoint or config.profile()
    for name, provider in config.profiles.items():
        if (provider.protocol, provider.base_url, provider.api_key_env) == (endpoint.protocol, endpoint.base_url, endpoint.api_key_env):
            return name, endpoint
    return config.default_profile, endpoint


def resolve_role(config: Config, role: str) -> tuple[Endpoint, dict]:
    if role not in ROLES:
        raise ConfigError(f"Unknown agent role '{role}'")
    assignment = config.active_agents.get(role, AgentAssignment())
    profile = config.agent_profiles.get(role, {}).get(assignment.profile) if assignment.profile else None
    if assignment.profile and profile is None:
        raise ConfigError(f"Active {role} profile '{assignment.profile}' does not exist")
    if profile:
        provider_name, model, prompt = profile.provider, profile.model, _prompt_text(profile)
        profile_name, prompt_source = profile.name, profile.prompt_source
    elif assignment.provider or assignment.model:
        provider_name, model = assignment.provider, assignment.model
        if provider_name not in config.profiles:
            raise ConfigError(f"Active {role} assignment references unknown or disabled provider '{provider_name}'")
        if not model:
            raise ConfigError(f"Active {role} assignment requires a model")
        prompt, profile_name, prompt_source = "", "", "none"
    else:
        provider_name, fallback = _fallback(config, role)
        model = fallback.model
        prompt = getattr(fallback, "system_prompt", "")
        profile_name, prompt_source = "", "file" if fallback.system_prompt_file else ("inline" if prompt else "none")
    provider = config.profiles.get(provider_name)
    if provider is None:
        _, provider = _fallback(config, role)
    endpoint = dataclasses.replace(
        provider, name=role, model=model, system_prompt=prompt,
        system_prompt_file="", modality=resolve_target_modality(model) if role == "target" else provider.modality,
    )
    for attr in ("_catalog_path", "_provider_id"):
        if hasattr(provider, attr):
            setattr(endpoint, attr, getattr(provider, attr))
    return endpoint, {
        "role": role, "profile": profile_name, "custom": not bool(profile_name),
        "provider": provider_name, "model": model, "prompt_source": prompt_source,
        "has_system_prompt": bool(prompt),
    }


def resolved_config(config: Config) -> tuple[Config, dict[str, dict]]:
    endpoints: dict[str, Endpoint] = {}
    summaries: dict[str, dict] = {}
    for role in ROLES:
        endpoints[role], summaries[role] = resolve_role(config, role)
    profiles = dict(config.profiles)
    profiles["__resolved_attacker__"] = endpoints["attacker"]
    run_config = dataclasses.replace(
        config, default_profile="__resolved_attacker__", profiles=profiles,
        target=endpoints["target"], judge=endpoints["judge"],
    )
    return run_config, summaries


def _block_span(text: str, prefix: str) -> tuple[int, int] | None:
    match = re.search(rf"(?m)^[ \t]*\[{re.escape(prefix)}\][ \t]*(?:#.*)?$", text)
    if not match:
        return None
    nxt = _TABLE_RE.search(text, match.end())
    return match.start(), nxt.start() if nxt else len(text)


def _write_block(config: Config, prefix: str, values: dict[str, str] | None) -> None:
    if config.path is None:
        return
    path = Path(config.path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        from .provider_registry import _profile_block
        text = f"default_profile = {_toml(config.default_profile)}\n\n"
        for name, endpoint in config.all_profiles.items():
            text += _profile_block(name, endpoint, name not in config.disabled_profiles) + "\n"
    span = _block_span(text, prefix)
    block = ""
    if values is not None:
        lines = [f"[{prefix}]"] + [f"{key} = {_toml(value)}" for key, value in values.items() if value != ""]
        block = "\n".join(lines) + "\n\n"
    if span:
        text = text[:span[0]] + block + text[span[1]:]
    elif block:
        text = text.rstrip() + "\n\n" + block
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


class AgentProfileRegistry:
    def __init__(self, config: Config):
        self.config = config

    def view(self) -> dict:
        roles = {}
        for role in ROLES:
            _, active = resolve_role(self.config, role)
            roles[role] = {
                "active": active,
                "profiles": [dataclasses.asdict(item) for item in sorted(self.config.agent_profiles.get(role, {}).values(), key=lambda p: p.name.casefold())],
            }
        return {"roles": roles}

    def save(self, role: str, name: str, body: dict) -> AgentProfile:
        profile = normalize_profile(self.config, role, name, body)
        self.config.agent_profiles.setdefault(role, {})[name] = profile
        values = {"provider": profile.provider, "model": profile.model, "prompt_source": profile.prompt_source}
        if profile.system_prompt:
            values["system_prompt"] = profile.system_prompt
        if profile.system_prompt_file:
            values["system_prompt_file"] = profile.system_prompt_file
        _write_block(self.config, f"agent_profiles.{role}.{_toml(name)}", values)
        return profile

    def delete(self, role: str, name: str) -> None:
        if self.config.active_agents.get(role, AgentAssignment()).profile == name:
            raise ConfigError("Select another profile or Custom before deleting the active profile")
        if name not in self.config.agent_profiles.get(role, {}):
            raise KeyError(name)
        del self.config.agent_profiles[role][name]
        _write_block(self.config, f"agent_profiles.{role}.{_toml(name)}", None)

    def activate(self, role: str, body: dict) -> dict:
        if role not in ROLES:
            raise ConfigError(f"Unknown agent role '{role}'")
        profile_name = str(body.get("profile", "")).strip()
        if profile_name:
            if profile_name not in self.config.agent_profiles.get(role, {}):
                raise ConfigError(f"Unknown {role} profile '{profile_name}'")
            assignment = AgentAssignment(profile=profile_name)
        else:
            provider = str(body.get("provider", "")).strip()
            model = str(body.get("model", "")).strip()
            if provider not in self.config.profiles:
                raise ConfigError(f"Unknown or disabled provider '{provider}'")
            if not model:
                raise ConfigError("model is required")
            assignment = AgentAssignment(provider=provider, model=model)
        self.config.active_agents[role] = assignment
        _write_block(self.config, f"agents.{role}", dataclasses.asdict(assignment))
        return resolve_role(self.config, role)[1]
