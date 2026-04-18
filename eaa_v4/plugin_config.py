"""
plugin_config.py — Plugin Configuration System (Phase 5)

Manages loading and validation of plugin server configurations from
.eaa_plugins.json, inspired by Claude Code's .mcp.json system.

Supports scope-specific settings:
    local, user, project, dynamic, enterprise

Each server config specifies:
    - Transport type (stdio, http, sse, websocket, inproc)
    - Connection parameters (command+args or url+headers)
    - Optional environment variables
    - Tool-specific timeout overrides
    - Allowed/denied server policies

Reference: Blueprint Section 9.2 — Server Configuration
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TransportType(Enum):
    """Supported plugin transport types."""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    WEBSOCKET = "websocket"
    INPROC = "inproc"


class PluginScope(Enum):
    """Configuration scope levels."""
    LOCAL = "local"
    USER = "user"
    PROJECT = "project"
    DYNAMIC = "dynamic"
    ENTERPRISE = "enterprise"


class ConnectionState(Enum):
    """Server connection states."""
    CONNECTED = "connected"
    FAILED = "failed"
    NEEDS_AUTH = "needs_auth"
    PENDING = "pending"
    DISABLED = "disabled"


# Default config file name
PLUGIN_CONFIG_FILE = ".eaa_plugins.json"

# Scope priority (higher = overrides lower)
SCOPE_PRIORITY = {
    PluginScope.LOCAL: 0,
    PluginScope.USER: 1,
    PluginScope.PROJECT: 2,
    PluginScope.DYNAMIC: 3,
    PluginScope.ENTERPRISE: 4,
}

# Connection batch limits
LOCAL_BATCH_SIZE = 3
REMOTE_BATCH_SIZE = 20

# Default timeout (seconds)
DEFAULT_TOOL_TIMEOUT = 30


@dataclass
class ServerConfig:
    """Configuration for a single plugin server."""
    name: str
    transport: TransportType
    scope: PluginScope = PluginScope.LOCAL

    # stdio transport params
    command: str = ""
    args: List[str] = field(default_factory=list)

    # network transport params
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    # Common params
    env: Dict[str, str] = field(default_factory=dict)
    tool_timeout: Optional[int] = None
    enabled: bool = True

    # OAuth
    oauth_client_id: str = ""
    oauth_client_secret: str = ""

    def get_signature(self) -> str:
        """
        Content-based signature for deduplication.

        stdio: JSON(command + sorted args)
        network: url
        """
        if self.transport == TransportType.STDIO:
            return f"stdio:{json.dumps({'cmd': self.command, 'args': sorted(self.args)})}"
        elif self.transport in (TransportType.HTTP, TransportType.SSE, TransportType.WEBSOCKET):
            return f"url:{self.url}"
        else:
            return f"inproc:{self.name}"

    def validate(self) -> List[str]:
        """Validate config and return list of errors (empty = valid)."""
        errors = []
        if not self.name.strip():
            errors.append("Server name cannot be empty")

        if self.transport == TransportType.STDIO:
            if not self.command:
                errors.append(f"'{self.name}': stdio transport requires 'command'")
        elif self.transport in (TransportType.HTTP, TransportType.SSE, TransportType.WEBSOCKET):
            if not self.url:
                errors.append(f"'{self.name}': network transport requires 'url'")
        elif self.transport == TransportType.INPROC:
            if not self.name:
                errors.append(f"InProc transport requires a module name")

        return errors


@dataclass
class PluginPolicy:
    """Enterprise-level allowed/denied server policies."""
    allowed_servers: List[str] = field(default_factory=list)
    denied_servers: List[str] = field(default_factory=list)

    def is_allowed(self, server_name: str) -> bool:
        """Check if a server is allowed. Denied always takes precedence."""
        if server_name in self.denied_servers:
            return False
        if not self.allowed_servers:
            return True  # No allowlist = everything allowed
        return server_name in self.allowed_servers


def parse_server_config(name: str, data: dict, scope: PluginScope = PluginScope.LOCAL) -> Optional[ServerConfig]:
    """
    Parse a server config from a JSON dict.

    Returns None if the config is invalid.
    """
    if not isinstance(data, dict):
        return None

    transport_str = data.get("transport", "stdio")
    try:
        transport = TransportType(transport_str)
    except ValueError:
        # Fallback to stdio
        transport = TransportType.STDIO

    # Check if explicitly disabled
    if data.get("disabled", False):
        return None

    config = ServerConfig(
        name=name,
        transport=transport,
        scope=scope,
        command=data.get("command", ""),
        args=data.get("args", []),
        url=data.get("url", ""),
        headers=data.get("headers", {}),
        env=data.get("env", {}),
        tool_timeout=data.get("tool_timeout", None),
        enabled=True,
        oauth_client_id=data.get("oauth_client_id", ""),
        oauth_client_secret=data.get("oauth_client_secret", ""),
    )

    return config


def load_plugin_config(project_root: str = ".") -> Dict[str, List[ServerConfig]]:
    """
    Load plugin configurations from all scope levels.

    Searches for .eaa_plugins.json in:
        - Project root
        - User home (~/.eaa/)

    Returns:
        Dict mapping scope name to list of ServerConfig.
    """
    configs: Dict[str, List[ServerConfig]] = {}
    search_paths = [
        (os.path.abspath(project_root), PluginScope.LOCAL),
        (os.path.expanduser("~/.eaa"), PluginScope.USER),
    ]

    for dir_path, scope in search_paths:
        config_file = os.path.join(dir_path, PLUGIN_CONFIG_FILE)
        if not os.path.isfile(config_file):
            continue

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        servers = data.get("servers", data.get("mcpServers", {}))
        if not isinstance(servers, dict):
            continue

        scope_key = scope.value
        configs[scope_key] = []

        for name, server_data in servers.items():
            if not isinstance(server_data, dict):
                continue
            config = parse_server_config(name, server_data, scope)
            if config is not None:
                configs[scope_key].append(config)

    return configs


def merge_configs(
    configs_by_scope: Dict[str, List[ServerConfig]],
    policy: Optional[PluginPolicy] = None,
) -> List[ServerConfig]:
    """
    Merge server configs across scopes with deduplication.

    Higher scope overrides lower scope. Deduplication uses
    content-based signatures: first-loaded-wins for same scope,
    higher-scope overrides lower-scope for same signature.

    Returns:
        Deduplicated, merged list of ServerConfig.
    """
    seen_signatures: Dict[str, ServerConfig] = {}

    # Process scopes in priority order (lowest first)
    for scope_name, priority in sorted(
        SCOPE_PRIORITY.items(), key=lambda x: x[1]
    ):
        configs = configs_by_scope.get(scope_name.value, [])
        for config in configs:
            sig = config.get_signature()

            # Apply policy check
            if policy and not policy.is_allowed(config.name):
                config.enabled = False

            # Higher scope overrides same signature
            if sig in seen_signatures:
                existing_priority = SCOPE_PRIORITY.get(
                    seen_signatures[sig].scope, 0
                )
                if priority > existing_priority:
                    seen_signatures[sig] = config
                # else: first-loaded-wins within same scope
            else:
                seen_signatures[sig] = config

    return list(seen_signatures.values())


def normalize_tool_name(server_name: str, tool_name: str) -> str:
    """
    Normalize plugin tool name: eaa__{server}__{tool}

    Non-alphanumeric characters are replaced with underscores.
    """
    def norm(s: str) -> str:
        return ''.join(c if c.isalnum() else '_' for c in s)

    return f"eaa__{norm(server_name)}__{norm(tool_name)}"
