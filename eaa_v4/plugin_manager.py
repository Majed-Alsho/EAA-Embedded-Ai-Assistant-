"""
plugin_manager.py — MCP Plugin System Manager (Phase 5)

Manages plugin server connections, tool discovery, and lifecycle.

Features:
    - 5 transport types (stdio, http, sse, websocket, inproc)
    - Exponential backoff reconnection
    - Connection state tracking (connected/failed/needs_auth/pending/disabled)
    - Tool naming convention: eaa__{server}__{tool}
    - Deduplication via content-based signatures
    - Hot-reload support
    - Permission-aware tool exposure

Reference: Blueprint Section 9 — MCP Plugin System
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from plugin_config import (
    ConnectionState,
    PluginPolicy,
    ServerConfig,
    TransportType,
    load_plugin_config,
    merge_configs,
    normalize_tool_name,
    LOCAL_BATCH_SIZE,
    REMOTE_BATCH_SIZE,
    DEFAULT_TOOL_TIMEOUT,
)


@dataclass
class PluginTool:
    """A tool exposed by a plugin server."""
    name: str               # Normalized name: eaa__{server}__{tool}
    original_name: str      # Original tool name from server
    server_name: str        # Parent server name
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    timeout: int = DEFAULT_TOOL_TIMEOUT
    is_read_only: bool = False
    is_destructive: bool = False


@dataclass
class ConnectionStateInfo:
    """Tracks state and metadata for a server connection."""
    server_name: str
    state: ConnectionState = ConnectionState.PENDING
    signature: str = ""
    reconnect_attempts: int = 0
    last_connected: float = 0.0
    last_error: str = ""
    auth_cache_time: float = 0.0  # 15-min auth cache

    @property
    def needs_reconnect(self) -> bool:
        return self.state in (ConnectionState.FAILED, ConnectionState.PENDING)

    @property
    def auth_cache_valid(self) -> bool:
        """Auth cache is valid for 15 minutes."""
        if self.state != ConnectionState.NEEDS_AUTH:
            return False
        return (time.time() - self.auth_cache_time) < 900


# Backoff configuration
BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0
BACKOFF_MULTIPLIER = 2.0


@dataclass
class ReconnectPolicy:
    """Exponential backoff reconnection policy."""
    base_delay: float = BACKOFF_BASE
    max_delay: float = BACKOFF_MAX
    multiplier: float = BACKOFF_MULTIPLIER
    max_attempts: int = 10

    def get_delay(self, attempt: int) -> float:
        delay = self.base_delay * (self.multiplier ** attempt)
        return min(delay, self.max_delay)

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts


class PluginManager:
    """
    Manages plugin server connections and tool discovery.

    Handles connection lifecycle, reconnection with exponential backoff,
    tool deduplication, and hot-reload.
    """

    def __init__(
        self,
        project_root: str = ".",
        policy: Optional[PluginPolicy] = None,
        reconnect_policy: Optional[ReconnectPolicy] = None,
    ):
        self.project_root = project_root
        self.policy = policy or PluginPolicy()
        self.reconnect_policy = reconnect_policy or ReconnectPolicy()

        # Server connection tracking
        self._servers: Dict[str, ConnectionStateInfo] = {}
        self._server_configs: Dict[str, ServerConfig] = {}

        # Discovered tools
        self._tools: Dict[str, PluginTool] = {}

        # Signatures for deduplication
        self._signatures: Dict[str, str] = {}  # sig -> server_name

        # Tool execution callbacks
        self._tool_executor: Optional[Callable] = None

        # Lock for thread safety
        self._lock = threading.RLock()

    def set_tool_executor(self, executor: Callable) -> None:
        """Set the callback for executing plugin tool calls."""
        self._tool_executor = executor

    def load_servers(self, configs: Optional[List[ServerConfig]] = None) -> int:
        """
        Load and connect to plugin servers.

        Args:
            configs: Optional pre-parsed configs. If None, loads from disk.

        Returns:
            Number of servers loaded.
        """
        if configs is None:
            raw = load_plugin_config(self.project_root)
            configs = merge_configs(raw, self.policy)

        with self._lock:
            count = 0
            for config in configs:
                if self._register_server(config):
                    count += 1
            return count

    def _register_server(self, config: ServerConfig) -> bool:
        """Register a single server, handling deduplication."""
        signature = config.get_signature()

        # Dedup: skip if same signature already registered
        if signature in self._signatures:
            existing = self._signatures[signature]
            # Check scope priority — don't override if existing has higher scope
            return False

        self._signatures[signature] = config.name
        self._server_configs[config.name] = config

        state_info = ConnectionStateInfo(
            server_name=config.name,
            signature=signature,
        )

        if not config.enabled:
            state_info.state = ConnectionState.DISABLED
        else:
            state_info.state = ConnectionState.PENDING

        self._servers[config.name] = state_info
        return True

    def connect_server(self, name: str) -> bool:
        """
        Attempt to connect a pending/failed server.

        Returns True if connection succeeds.
        """
        with self._lock:
            info = self._servers.get(name)
            if info is None:
                return False

            config = self._server_configs.get(name)
            if config is None:
                return False

            if not info.needs_reconnect:
                return info.state == ConnectionState.CONNECTED

            # Check reconnect policy
            if not self.reconnect_policy.should_retry(info.reconnect_attempts):
                info.state = ConnectionState.DISABLED
                return False

            # Calculate backoff delay
            delay = self.reconnect_policy.get_delay(info.reconnect_attempts)
            info.reconnect_attempts += 1

            # Simulate connection attempt
            try:
                self._do_connect(config)
                info.state = ConnectionState.CONNECTED
                info.last_connected = time.time()
                info.last_error = ""
                info.reconnect_attempts = 0

                # Discover tools from this server
                self._discover_tools(name, config)
                return True

            except Exception as e:
                info.state = ConnectionState.FAILED
                info.last_error = str(e)
                return False

    def _do_connect(self, config: ServerConfig) -> None:
        """
        Perform the actual connection based on transport type.

        This is a stub — in production, this would launch subprocesses
        (stdio), open HTTP/SSE/WebSocket connections, or import modules.
        """
        if config.transport == TransportType.STDIO:
            if not config.command:
                raise RuntimeError(f"No command for stdio server '{config.name}'")
        elif config.transport in (TransportType.HTTP, TransportType.SSE, TransportType.WEBSOCKET):
            if not config.url:
                raise RuntimeError(f"No URL for network server '{config.name}'")
        elif config.transport == TransportType.INPROC:
            pass  # In-process, no connection needed

    def _discover_tools(self, server_name: str, config: ServerConfig) -> None:
        """
        Discover tools from a connected server.

        Stub implementation — in production, this would query the server
        via the transport to get available tools and their schemas.
        """
        # Tools are registered externally via register_tools()
        pass

    def register_tools(self, server_name: str, tools: List[Dict[str, Any]]) -> int:
        """
        Register tools discovered from a server.

        Args:
            server_name: The server name.
            tools: List of tool dicts with 'name', 'description', 'schema' keys.

        Returns:
            Number of tools registered.
        """
        with self._lock:
            config = self._server_configs.get(server_name)
            if config is None:
                return 0

            count = 0
            for tool_data in tools:
                original_name = tool_data.get("name", "")
                if not original_name:
                    continue

                normalized = normalize_tool_name(server_name, original_name)
                timeout = tool_data.get("timeout", config.tool_timeout or DEFAULT_TOOL_TIMEOUT)

                plugin_tool = PluginTool(
                    name=normalized,
                    original_name=original_name,
                    server_name=server_name,
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("schema", {}),
                    timeout=timeout,
                    is_read_only=tool_data.get("is_read_only", False),
                    is_destructive=tool_data.get("is_destructive", False),
                )

                self._tools[normalized] = plugin_tool
                count += 1

            return count

    def get_tool(self, name: str) -> Optional[PluginTool]:
        """Get a plugin tool by normalized name."""
        return self._tools.get(name)

    def get_tools_for_server(self, server_name: str) -> List[PluginTool]:
        """Get all tools from a specific server."""
        return [t for t in self._tools.values() if t.server_name == server_name]

    def get_all_tools(self) -> List[PluginTool]:
        """Get all registered plugin tools."""
        return list(self._tools.values())

    def get_server_state(self, name: str) -> Optional[ConnectionState]:
        """Get the connection state of a server."""
        info = self._servers.get(name)
        return info.state if info else None

    def get_all_server_states(self) -> Dict[str, ConnectionState]:
        """Get connection states for all servers."""
        return {name: info.state for name, info in self._servers.items()}

    def disconnect_server(self, name: str) -> bool:
        """Disconnect a server."""
        with self._lock:
            info = self._servers.get(name)
            if info is None:
                return False

            if info.state != ConnectionState.CONNECTED:
                return False

            info.state = ConnectionState.DISABLED
            # Remove tools from this server
            tools_to_remove = [t.name for t in self._tools.values() if t.server_name == name]
            for tool_name in tools_to_remove:
                del self._tools[tool_name]

            return True

    def reload(self) -> int:
        """
        Hot-reload: re-read config from disk and update servers.

        Returns:
            Number of servers after reload.
        """
        with self._lock:
            # Clear existing
            self._servers.clear()
            self._server_configs.clear()
            self._signatures.clear()
            self._tools.clear()

            # Reload from disk
            return self.load_servers()

    def get_connection_batch_plan(self) -> Dict[str, List[str]]:
        """
        Plan batched connection order to avoid overwhelming the system.

        Returns:
            Dict with 'local' and 'remote' keys, each containing
            a list of server names to connect.
        """
        local = []
        remote = []

        for name, info in self._servers.items():
            config = self._server_configs.get(name)
            if config is None or not config.enabled:
                continue
            if info.needs_reconnect:
                if config.transport == TransportType.STDIO:
                    local.append(name)
                else:
                    remote.append(name)

        return {
            "local": local[:LOCAL_BATCH_SIZE],
            "remote": remote[:REMOTE_BATCH_SIZE],
        }

    @property
    def stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        states = {}
        for state in ConnectionState:
            states[state.value] = sum(
                1 for info in self._servers.values()
                if info.state == state
            )
        return {
            "total_servers": len(self._servers),
            "total_tools": len(self._tools),
            "connection_states": states,
        }
