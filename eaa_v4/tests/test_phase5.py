"""
Phase 5 Tests — Plugin System + VRAM Lifecycle

Tests for:
    - plugin_config.py: Server configs, parsing, validation, merging, normalization
    - plugin_manager.py: Plugin manager, connections, tool discovery, hot-reload
    - model_registry.py: Model registry, VRAM estimates, swap planning
    - vram_lifecycle.py: Hot-swap, watchdog, CPU fallback, context manager

Run: python test_phase5.py
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import shutil
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugin_config import (
    ConnectionState,
    DEFAULT_TOOL_TIMEOUT,
    LOCAL_BATCH_SIZE,
    REMOTE_BATCH_SIZE,
    PluginPolicy,
    PluginScope,
    SCOPE_PRIORITY,
    ServerConfig,
    TransportType,
    load_plugin_config,
    merge_configs,
    normalize_tool_name,
    parse_server_config,
    PLUGIN_CONFIG_FILE,
)


# ============================================================
# plugin_config.py Tests
# ============================================================

class TestTransportType(unittest.TestCase):
    """Tests for TransportType enum."""

    def test_all_types(self):
        self.assertEqual(TransportType.STDIO.value, "stdio")
        self.assertEqual(TransportType.HTTP.value, "http")
        self.assertEqual(TransportType.SSE.value, "sse")
        self.assertEqual(TransportType.WEBSOCKET.value, "websocket")
        self.assertEqual(TransportType.INPROC.value, "inproc")

    def test_from_string(self):
        t = TransportType("stdio")
        self.assertEqual(t, TransportType.STDIO)

    def test_invalid_string_raises(self):
        with self.assertRaises(ValueError):
            TransportType("invalid")


class TestConnectionState(unittest.TestCase):
    """Tests for ConnectionState enum."""

    def test_all_states(self):
        states = [ConnectionState.CONNECTED, ConnectionState.FAILED,
                  ConnectionState.NEEDS_AUTH, ConnectionState.PENDING,
                  ConnectionState.DISABLED]
        self.assertEqual(len(states), 5)


class TestServerConfig(unittest.TestCase):
    """Tests for ServerConfig dataclass."""

    def test_stdio_signature(self):
        config = ServerConfig(
            name="test", transport=TransportType.STDIO,
            command="python", args=["-m", "server"]
        )
        sig = config.get_signature()
        self.assertTrue(sig.startswith("stdio:"))
        self.assertIn("python", sig)

    def test_http_signature(self):
        config = ServerConfig(
            name="api", transport=TransportType.HTTP,
            url="http://localhost:8080"
        )
        sig = config.get_signature()
        self.assertEqual(sig, "url:http://localhost:8080")

    def test_inproc_signature(self):
        config = ServerConfig(
            name="mymod", transport=TransportType.INPROC
        )
        sig = config.get_signature()
        self.assertEqual(sig, "inproc:mymod")

    def test_stdio_validate_ok(self):
        config = ServerConfig(
            name="test", transport=TransportType.STDIO,
            command="node"
        )
        self.assertEqual(config.validate(), [])

    def test_stdio_validate_no_command(self):
        config = ServerConfig(
            name="test", transport=TransportType.STDIO
        )
        errors = config.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("command", errors[0])

    def test_http_validate_ok(self):
        config = ServerConfig(
            name="test", transport=TransportType.HTTP,
            url="http://localhost:8080"
        )
        self.assertEqual(config.validate(), [])

    def test_http_validate_no_url(self):
        config = ServerConfig(
            name="test", transport=TransportType.HTTP
        )
        errors = config.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("url", errors[0])

    def test_empty_name_invalid(self):
        config = ServerConfig(
            name="", transport=TransportType.STDIO,
            command="x"
        )
        errors = config.validate()
        self.assertTrue(any("name" in e for e in errors))

    def test_same_command_same_signature(self):
        c1 = ServerConfig(name="a", transport=TransportType.STDIO, command="python", args=["-m", "s"])
        c2 = ServerConfig(name="b", transport=TransportType.STDIO, command="python", args=["-m", "s"])
        self.assertEqual(c1.get_signature(), c2.get_signature())

    def test_different_command_different_signature(self):
        c1 = ServerConfig(name="a", transport=TransportType.STDIO, command="python")
        c2 = ServerConfig(name="b", transport=TransportType.STDIO, command="node")
        self.assertNotEqual(c1.get_signature(), c2.get_signature())


class TestParseServerConfig(unittest.TestCase):
    """Tests for parse_server_config."""

    def test_basic_stdio(self):
        data = {"transport": "stdio", "command": "python", "args": ["-m", "server"]}
        config = parse_server_config("test", data)
        self.assertIsNotNone(config)
        self.assertEqual(config.name, "test")
        self.assertEqual(config.transport, TransportType.STDIO)
        self.assertEqual(config.command, "python")
        self.assertEqual(config.args, ["-m", "server"])

    def test_http_server(self):
        data = {"transport": "http", "url": "http://localhost:8080/mcp"}
        config = parse_server_config("api", data)
        self.assertIsNotNone(config)
        self.assertEqual(config.transport, TransportType.HTTP)
        self.assertEqual(config.url, "http://localhost:8080/mcp")

    def test_disabled_server_skipped(self):
        data = {"transport": "stdio", "command": "python", "disabled": True}
        config = parse_server_config("test", data)
        self.assertIsNone(config)

    def test_with_env(self):
        data = {"transport": "stdio", "command": "node", "env": {"PORT": "3000"}}
        config = parse_server_config("test", data)
        self.assertEqual(config.env, {"PORT": "3000"})

    def test_with_timeout(self):
        data = {"transport": "stdio", "command": "python", "tool_timeout": 60}
        config = parse_server_config("test", data)
        self.assertEqual(config.tool_timeout, 60)

    def test_with_headers(self):
        data = {"transport": "sse", "url": "http://x.com", "headers": {"Auth": "Bearer x"}}
        config = parse_server_config("test", data)
        self.assertEqual(config.headers, {"Auth": "Bearer x"})

    def test_unknown_transport_defaults_stdio(self):
        data = {"transport": "unknown_type", "command": "x"}
        config = parse_server_config("test", data)
        self.assertIsNotNone(config)
        self.assertEqual(config.transport, TransportType.STDIO)

    def test_invalid_data_returns_none(self):
        config = parse_server_config("test", "not a dict")
        self.assertIsNone(config)

    def test_scope_default_local(self):
        data = {"transport": "stdio", "command": "x"}
        config = parse_server_config("test", data)
        self.assertEqual(config.scope, PluginScope.LOCAL)

    def test_explicit_scope(self):
        data = {"transport": "stdio", "command": "x"}
        config = parse_server_config("test", data, scope=PluginScope.ENTERPRISE)
        self.assertEqual(config.scope, PluginScope.ENTERPRISE)


class TestLoadPluginConfig(unittest.TestCase):
    """Tests for load_plugin_config."""

    def test_empty_project(self):
        configs = load_plugin_config(tempfile.mkdtemp())
        self.assertIsInstance(configs, dict)

    def test_loads_from_project(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config_data = {
                "servers": {
                    "test": {"transport": "stdio", "command": "python"}
                }
            }
            with open(os.path.join(tmpdir, PLUGIN_CONFIG_FILE), 'w') as f:
                json.dump(config_data, f)

            configs = load_plugin_config(tmpdir)
            self.assertIn("local", configs)
            self.assertEqual(len(configs["local"]), 1)
            self.assertEqual(configs["local"][0].name, "test")
        finally:
            shutil.rmtree(tmpdir)

    def test_loads_mcpServers_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config_data = {
                "mcpServers": {
                    "test": {"transport": "stdio", "command": "node"}
                }
            }
            with open(os.path.join(tmpdir, PLUGIN_CONFIG_FILE), 'w') as f:
                json.dump(config_data, f)

            configs = load_plugin_config(tmpdir)
            self.assertEqual(len(configs["local"]), 1)
        finally:
            shutil.rmtree(tmpdir)

    def test_invalid_json_skipped(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, PLUGIN_CONFIG_FILE), 'w') as f:
                f.write("not json {{{{")

            configs = load_plugin_config(tmpdir)
            self.assertEqual(len(configs), 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_disabled_servers_not_loaded(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config_data = {
                "servers": {
                    "active": {"transport": "stdio", "command": "python"},
                    "disabled_one": {"transport": "stdio", "command": "node", "disabled": True}
                }
            }
            with open(os.path.join(tmpdir, PLUGIN_CONFIG_FILE), 'w') as f:
                json.dump(config_data, f)

            configs = load_plugin_config(tmpdir)
            self.assertEqual(len(configs["local"]), 1)
            self.assertEqual(configs["local"][0].name, "active")
        finally:
            shutil.rmtree(tmpdir)


class TestMergeConfigs(unittest.TestCase):
    """Tests for merge_configs."""

    def test_empty_inputs(self):
        result = merge_configs({})
        self.assertEqual(result, [])

    def test_single_scope(self):
        configs = {
            "local": [
                ServerConfig(name="a", transport=TransportType.STDIO, command="python")
            ]
        }
        result = merge_configs(configs)
        self.assertEqual(len(result), 1)

    def test_dedup_same_signature(self):
        configs = {
            "local": [
                ServerConfig(name="a", transport=TransportType.STDIO, command="python", args=["-m", "s"]),
                ServerConfig(name="b", transport=TransportType.STDIO, command="python", args=["-m", "s"]),
            ]
        }
        result = merge_configs(configs)
        self.assertEqual(len(result), 1)

    def test_different_signatures_both_kept(self):
        configs = {
            "local": [
                ServerConfig(name="a", transport=TransportType.STDIO, command="python"),
                ServerConfig(name="b", transport=TransportType.STDIO, command="node"),
            ]
        }
        result = merge_configs(configs)
        self.assertEqual(len(result), 2)

    def test_higher_scope_overrides_lower(self):
        configs = {
            "local": [
                ServerConfig(name="local-srv", transport=TransportType.STDIO, command="python", scope=PluginScope.LOCAL)
            ],
            "enterprise": [
                ServerConfig(name="ent-srv", transport=TransportType.STDIO, command="python", scope=PluginScope.ENTERPRISE)
            ]
        }
        result = merge_configs(configs)
        # Same signature (same command), enterprise should override
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scope, PluginScope.ENTERPRISE)

    def test_policy_denied_server_disabled(self):
        policy = PluginPolicy(denied_servers=["bad_server"])
        configs = {
            "local": [
                ServerConfig(name="bad_server", transport=TransportType.STDIO, command="python")
            ]
        }
        result = merge_configs(configs, policy=policy)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].enabled)

    def test_policy_allowed_servers(self):
        policy = PluginPolicy(allowed_servers=["good"])
        configs = {
            "local": [
                ServerConfig(name="good", transport=TransportType.STDIO, command="python"),
                ServerConfig(name="bad", transport=TransportType.STDIO, command="node"),
            ]
        }
        result = merge_configs(configs, policy=policy)
        enabled = [c for c in result if c.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "good")


class TestPluginPolicy(unittest.TestCase):
    """Tests for PluginPolicy."""

    def test_no_restrictions(self):
        policy = PluginPolicy()
        self.assertTrue(policy.is_allowed("anything"))

    def test_denied_precedence(self):
        policy = PluginPolicy(
            allowed_servers=["server"],
            denied_servers=["server"]
        )
        self.assertFalse(policy.is_allowed("server"))

    def test_allowlist(self):
        policy = PluginPolicy(allowed_servers=["a", "b"])
        self.assertTrue(policy.is_allowed("a"))
        self.assertTrue(policy.is_allowed("b"))
        self.assertFalse(policy.is_allowed("c"))


class TestNormalizeToolName(unittest.TestCase):
    """Tests for normalize_tool_name."""

    def test_basic(self):
        self.assertEqual(normalize_tool_name("myserver", "mytool"), "eaa__myserver__mytool")

    def test_special_chars(self):
        self.assertEqual(normalize_tool_name("my-server", "my_tool"), "eaa__my_server__my_tool")

    def test_spaces(self):
        self.assertEqual(normalize_tool_name("my server", "my tool"), "eaa__my_server__my_tool")

    def test_dashes_and_dots(self):
        self.assertEqual(normalize_tool_name("my.server", "my-tool"), "eaa__my_server__my_tool")

    def test_empty_name(self):
        self.assertEqual(normalize_tool_name("", "tool"), "eaa____tool")


class TestScopePriority(unittest.TestCase):
    """Tests for SCOPE_PRIORITY."""

    def test_order(self):
        self.assertLess(SCOPE_PRIORITY[PluginScope.LOCAL], SCOPE_PRIORITY[PluginScope.USER])
        self.assertLess(SCOPE_PRIORITY[PluginScope.USER], SCOPE_PRIORITY[PluginScope.PROJECT])
        self.assertLess(SCOPE_PRIORITY[PluginScope.PROJECT], SCOPE_PRIORITY[PluginScope.DYNAMIC])
        self.assertLess(SCOPE_PRIORITY[PluginScope.DYNAMIC], SCOPE_PRIORITY[PluginScope.ENTERPRISE])

    def test_all_scopes_present(self):
        self.assertEqual(len(SCOPE_PRIORITY), 5)


# ============================================================
# plugin_manager.py Tests
# ============================================================

from plugin_manager import (
    ConnectionStateInfo,
    PluginManager,
    PluginTool,
    ReconnectPolicy,
)


class TestPluginTool(unittest.TestCase):
    """Tests for PluginTool dataclass."""

    def test_basic(self):
        tool = PluginTool(
            name="eaa__srv__tool",
            original_name="tool",
            server_name="srv",
            description="A tool"
        )
        self.assertEqual(tool.name, "eaa__srv__tool")
        self.assertFalse(tool.is_read_only)
        self.assertFalse(tool.is_destructive)


class TestConnectionStateInfo(unittest.TestCase):
    """Tests for ConnectionStateInfo."""

    def test_needs_reconnect_on_failed(self):
        info = ConnectionStateInfo(server_name="test", state=ConnectionState.FAILED)
        self.assertTrue(info.needs_reconnect)

    def test_needs_reconnect_on_pending(self):
        info = ConnectionStateInfo(server_name="test", state=ConnectionState.PENDING)
        self.assertTrue(info.needs_reconnect)

    def test_no_reconnect_on_connected(self):
        info = ConnectionStateInfo(server_name="test", state=ConnectionState.CONNECTED)
        self.assertFalse(info.needs_reconnect)

    def test_no_reconnect_on_disabled(self):
        info = ConnectionStateInfo(server_name="test", state=ConnectionState.DISABLED)
        self.assertFalse(info.needs_reconnect)

    def test_auth_cache_valid(self):
        info = ConnectionStateInfo(
            server_name="test",
            state=ConnectionState.NEEDS_AUTH,
            auth_cache_time=time.time()
        )
        self.assertTrue(info.auth_cache_valid)

    def test_auth_cache_expired(self):
        info = ConnectionStateInfo(
            server_name="test",
            state=ConnectionState.NEEDS_AUTH,
            auth_cache_time=time.time() - 1000  # 1000 seconds ago
        )
        self.assertFalse(info.auth_cache_valid)

    def test_auth_cache_not_applicable(self):
        info = ConnectionStateInfo(
            server_name="test",
            state=ConnectionState.CONNECTED
        )
        self.assertFalse(info.auth_cache_valid)


class TestReconnectPolicy(unittest.TestCase):
    """Tests for ReconnectPolicy."""

    def test_get_delay_increases(self):
        policy = ReconnectPolicy()
        d0 = policy.get_delay(0)
        d1 = policy.get_delay(1)
        d2 = policy.get_delay(2)
        self.assertLess(d0, d1)
        self.assertLess(d1, d2)

    def test_delay_capped_at_max(self):
        policy = ReconnectPolicy(max_delay=10.0)
        d100 = policy.get_delay(100)
        self.assertEqual(d100, 10.0)

    def test_should_retry(self):
        policy = ReconnectPolicy(max_attempts=5)
        self.assertTrue(policy.should_retry(0))
        self.assertTrue(policy.should_retry(4))
        self.assertFalse(policy.should_retry(5))
        self.assertFalse(policy.should_retry(10))


class TestPluginManager(unittest.TestCase):
    """Tests for PluginManager."""

    def _make_manager(self, **kwargs) -> PluginManager:
        return PluginManager(tempfile.mkdtemp(), **kwargs)

    def _make_stdio_config(self, name="test", command="python", scope=PluginScope.LOCAL):
        return ServerConfig(name=name, transport=TransportType.STDIO, command=command, scope=scope)

    def _make_http_config(self, name="api", url="http://localhost:8080"):
        return ServerConfig(name=name, transport=TransportType.HTTP, url=url)

    def test_load_servers_manual(self):
        mgr = self._make_manager()
        configs = [self._make_stdio_config()]
        count = mgr.load_servers(configs)
        self.assertEqual(count, 1)

    def test_dedup_same_server(self):
        mgr = self._make_manager()
        configs = [
            self._make_stdio_config(name="a", command="python"),
            self._make_stdio_config(name="b", command="python"),  # Same signature
        ]
        count = mgr.load_servers(configs)
        self.assertEqual(count, 1)

    def test_connect_stdio_server(self):
        mgr = self._make_manager()
        configs = [self._make_stdio_config()]
        mgr.load_servers(configs)
        success = mgr.connect_server("test")
        self.assertTrue(success)
        self.assertEqual(mgr.get_server_state("test"), ConnectionState.CONNECTED)

    def test_connect_nonexistent(self):
        mgr = self._make_manager()
        success = mgr.connect_server("nonexistent")
        self.assertFalse(success)

    def test_connect_disabled(self):
        mgr = self._make_manager()
        config = self._make_stdio_config()
        config.enabled = False
        mgr.load_servers([config])
        self.assertEqual(mgr.get_server_state("test"), ConnectionState.DISABLED)

    def test_register_tools(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        mgr.connect_server("test")

        tools = [
            {"name": "read_file", "description": "Read a file", "schema": {"type": "object"}},
            {"name": "write_file", "description": "Write a file", "schema": {"type": "object"}},
        ]
        count = mgr.register_tools("test", tools)
        self.assertEqual(count, 2)

    def test_get_tool_normalized(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        mgr.connect_server("test")
        mgr.register_tools("test", [{"name": "my_tool", "description": "test"}])

        tool = mgr.get_tool("eaa__test__my_tool")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.original_name, "my_tool")

    def test_get_tools_for_server(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        mgr.connect_server("test")
        mgr.register_tools("test", [
            {"name": "tool_a", "description": "a"},
            {"name": "tool_b", "description": "b"},
        ])

        tools = mgr.get_tools_for_server("test")
        self.assertEqual(len(tools), 2)

    def test_get_all_tools(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config(name="s1"), self._make_stdio_config(name="s2", command="node")])
        mgr.connect_server("s1")
        mgr.connect_server("s2")
        mgr.register_tools("s1", [{"name": "t1", "description": ""}])
        mgr.register_tools("s2", [{"name": "t2", "description": ""}])

        all_tools = mgr.get_all_tools()
        self.assertEqual(len(all_tools), 2)

    def test_disconnect_server(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        mgr.connect_server("test")
        mgr.register_tools("test", [{"name": "tool1", "description": ""}])

        success = mgr.disconnect_server("test")
        self.assertTrue(success)
        self.assertEqual(mgr.get_server_state("test"), ConnectionState.DISABLED)
        self.assertIsNone(mgr.get_tool("eaa__test__tool1"))

    def test_disconnect_nonexistent(self):
        mgr = self._make_manager()
        self.assertFalse(mgr.disconnect_server("nonexistent"))

    def test_disconnect_not_connected(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        self.assertFalse(mgr.disconnect_server("test"))

    def test_reload(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        self.assertEqual(len(mgr.get_all_tools()), 0)

        mgr.register_tools("test", [{"name": "t1", "description": ""}])
        self.assertEqual(len(mgr.get_all_tools()), 1)

        mgr.reload()
        self.assertEqual(len(mgr.get_all_tools()), 0)

    def test_get_all_server_states(self):
        mgr = self._make_manager()
        mgr.load_servers([
            self._make_stdio_config(name="a", command="python"),
            self._make_stdio_config(name="b", command="node"),
        ])
        mgr.connect_server("a")
        mgr.connect_server("b")

        states = mgr.get_all_server_states()
        self.assertEqual(len(states), 2)
        self.assertEqual(states["a"], ConnectionState.CONNECTED)
        self.assertEqual(states["b"], ConnectionState.CONNECTED)

    def test_get_connection_batch_plan(self):
        mgr = self._make_manager()
        mgr.load_servers([
            self._make_stdio_config(name="s1", command="p1"),
            self._make_stdio_config(name="s2", command="p2"),
            self._make_http_config(name="api1"),
        ])
        # All pending

        plan = mgr.get_connection_batch_plan()
        self.assertIn("local", plan)
        self.assertIn("remote", plan)
        self.assertEqual(len(plan["local"]), 2)  # Both stdio, under LOCAL_BATCH_SIZE=3
        self.assertEqual(len(plan["remote"]), 1)

    def test_stats(self):
        mgr = self._make_manager()
        mgr.load_servers([self._make_stdio_config()])
        mgr.connect_server("test")
        mgr.register_tools("test", [{"name": "t1", "description": ""}])

        stats = mgr.stats
        self.assertEqual(stats["total_servers"], 1)
        self.assertEqual(stats["total_tools"], 1)
        self.assertEqual(stats["connection_states"]["connected"], 1)

    def test_connection_failed_reconnect(self):
        """Test that a failed connection can be retried."""
        mgr = self._make_manager()
        # Use a config that will fail (no command)
        config = ServerConfig(name="bad", transport=TransportType.STDIO, command="")
        mgr.load_servers([config])

        success = mgr.connect_server("bad")
        self.assertFalse(success)
        self.assertEqual(mgr.get_server_state("bad"), ConnectionState.FAILED)


# ============================================================
# model_registry.py Tests
# ============================================================

from model_registry import (
    ModelInfo,
    ModelRegistry,
    QuantType,
    VRAM_FOOTPRINT_TABLE,
)


class TestQuantType(unittest.TestCase):
    """Tests for QuantType enum."""

    def test_all_types(self):
        types = [QuantType.FP32, QuantType.FP16, QuantType.INT8,
                 QuantType.INT4, QuantType.BNB_INT4, QuantType.BNB_INT8,
                 QuantType.GPTQ_INT4, QuantType.AWQ_INT4]
        self.assertEqual(len(types), 8)


class TestModelInfo(unittest.TestCase):
    """Tests for ModelInfo dataclass."""

    def test_auto_vram_estimate_7b_bnb4(self):
        info = ModelInfo(name="qwen7b", path="/model", params_b=7, quant=QuantType.BNB_INT4)
        self.assertGreater(info.vram_footprint_gb, 0)
        self.assertAlmostEqual(info.vram_footprint_gb, 4.5, delta=1.0)

    def test_auto_vram_estimate_1_5b(self):
        info = ModelInfo(name="tiny", path="/model", params_b=1.5, quant=QuantType.INT4)
        self.assertAlmostEqual(info.vram_footprint_gb, 0.9, delta=0.5)

    def test_explicit_vram_override(self):
        info = ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4, vram_footprint_gb=5.0)
        self.assertEqual(info.vram_footprint_gb, 5.0)

    def test_is_resident_small_model(self):
        info = ModelInfo(name="classifier", path="/m", params_b=1.5, quant=QuantType.INT4)
        self.assertTrue(info.is_resident)

    def test_is_not_resident_large_model(self):
        info = ModelInfo(name="coder", path="/m", params_b=7, quant=QuantType.BNB_INT4)
        self.assertFalse(info.is_resident)

    def test_is_loaded_defaults_false(self):
        info = ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4)
        self.assertFalse(info.is_loaded)


class TestVRAMFootprintTable(unittest.TestCase):
    """Tests for the VRAM footprint lookup table."""

    def test_has_entries(self):
        self.assertGreater(len(VRAM_FOOTPRINT_TABLE), 0)

    def test_7b_bnb4_exists(self):
        self.assertIn((7, QuantType.BNB_INT4), VRAM_FOOTPRINT_TABLE)

    def test_7b_fp16_exists(self):
        self.assertIn((7, QuantType.FP16), VRAM_FOOTPRINT_TABLE)


class TestModelRegistry(unittest.TestCase):
    """Tests for ModelRegistry."""

    def test_register_and_get(self):
        reg = ModelRegistry()
        info = ModelInfo(name="qwen7b", path="/model", params_b=7, quant=QuantType.BNB_INT4)
        reg.register(info)
        result = reg.get("qwen7b")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "qwen7b")

    def test_unregister(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4))
        self.assertTrue(reg.unregister("x"))
        self.assertIsNone(reg.get("x"))

    def test_unregister_loaded_fails(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4))
        reg.mark_loaded("x")
        self.assertFalse(reg.unregister("x"))

    def test_mark_loaded(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4))
        self.assertTrue(reg.mark_loaded("x"))
        self.assertIn("x", reg.current_loaded)
        self.assertTrue(reg.get("x").is_loaded)

    def test_mark_loaded_nonexistent(self):
        reg = ModelRegistry()
        self.assertFalse(reg.mark_loaded("nonexistent"))

    def test_mark_unloaded(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="x", path="/m", params_b=7, quant=QuantType.INT4))
        reg.mark_loaded("x")
        self.assertTrue(reg.mark_unloaded("x"))
        self.assertEqual(len(reg.current_loaded), 0)
        self.assertFalse(reg.get("x").is_loaded)

    def test_mark_unloaded_not_loaded(self):
        reg = ModelRegistry()
        self.assertFalse(reg.mark_unloaded("nonexistent"))

    def test_resident_model(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="classifier", path="/m", params_b=1.5, quant=QuantType.INT4))
        self.assertTrue(reg.register_as_resident("classifier"))
        self.assertIn("classifier", reg.resident_models)

    def test_resident_too_large(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="big", path="/m", params_b=7, quant=QuantType.BNB_INT4))
        self.assertFalse(reg.register_as_resident("big"))

    def test_get_resident_vram(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="cls", path="/m", params_b=1.5, quant=QuantType.INT4))
        reg.register_as_resident("cls")
        self.assertGreater(reg.get_resident_vram(), 0)

    def test_get_available_vram(self):
        reg = ModelRegistry(total_vram_gb=8.0)
        reg.register(ModelInfo(name="cls", path="/m", params_b=1.5, quant=QuantType.INT4))
        reg.register_as_resident("cls")
        available = reg.get_available_vram()
        self.assertLess(available, 8.0)
        self.assertGreater(available, 6.0)

    def test_can_fit(self):
        reg = ModelRegistry(total_vram_gb=8.0)
        reg.register(ModelInfo(name="qwen7b", path="/m", params_b=7, quant=QuantType.BNB_INT4))
        reg.register(ModelInfo(name="cls", path="/m", params_b=1.5, quant=QuantType.INT4))
        reg.register_as_resident("cls")
        reg.register(ModelInfo(name="classifier", path="/m", params_b=1.5, quant=QuantType.INT4))
        self.assertTrue(reg.can_fit("qwen7b"))

    def test_cannot_fit_too_large(self):
        reg = ModelRegistry(total_vram_gb=4.0)
        reg.register(ModelInfo(name="big", path="/m", params_b=14, quant=QuantType.INT4))
        self.assertFalse(reg.can_fit("big"))

    def test_get_swap_plan_fits(self):
        reg = ModelRegistry(total_vram_gb=8.0)
        reg.register(ModelInfo(name="master", path="/m", params_b=7, quant=QuantType.BNB_INT4))
        reg.register(ModelInfo(name="coder", path="/m", params_b=7, quant=QuantType.BNB_INT4))
        reg.mark_loaded("master")

        plan = reg.get_swap_plan("coder")
        self.assertTrue(plan["fits"])
        self.assertIn("master", plan["unload"])
        self.assertEqual(plan["load"], "coder")

    def test_get_swap_plan_unknown(self):
        reg = ModelRegistry()
        plan = reg.get_swap_plan("nonexistent")
        self.assertFalse(plan["fits"])

    def test_all_models(self):
        reg = ModelRegistry()
        reg.register(ModelInfo(name="a", path="/m", params_b=7, quant=QuantType.INT4))
        reg.register(ModelInfo(name="b", path="/m", params_b=3, quant=QuantType.INT4))
        self.assertEqual(len(reg.all_models), 2)


# ============================================================
# vram_lifecycle.py Tests
# ============================================================

from vram_lifecycle import (
    SwapContext,
    SwapError,
    SwapPhase,
    SwapRecord,
    SwapStats,
    VRAMLifecycleManager,
    VRAMMetrics,
    WatchdogTimeoutError,
    InsufficientVRAMError,
    DEFAULT_WATCHDOG_TIMEOUT,
)


class TestSwapPhase(unittest.TestCase):
    """Tests for SwapPhase enum."""

    def test_all_phases(self):
        phases = [SwapPhase.IDLE, SwapPhase.SAVING_STATE, SwapPhase.UNLOADING,
                  SwapPhase.LOADING, SwapPhase.EXECUTING, SwapPhase.CAPTURING_RESULT,
                  SwapPhase.UNLOADING_TARGET, SwapPhase.RELOADING, SwapPhase.RESTORING_STATE]
        self.assertEqual(len(phases), 9)


class TestSwapRecord(unittest.TestCase):
    """Tests for SwapRecord."""

    def test_auto_duration(self):
        record = SwapRecord(
            source_model="master",
            target_model="coder",
            start_time=100.0,
            end_time=101.5,
            success=True
        )
        self.assertAlmostEqual(record.duration_ms, 1500.0)

    def test_no_end_time_zero_duration(self):
        record = SwapRecord(
            source_model="master",
            target_model="coder",
            start_time=100.0,
        )
        self.assertEqual(record.duration_ms, 0.0)


class TestSwapStats(unittest.TestCase):
    """Tests for SwapStats."""

    def test_zero_stats(self):
        stats = SwapStats()
        self.assertEqual(stats.success_rate, 0.0)

    def test_success_rate(self):
        stats = SwapStats(total_swaps=10, successful_swaps=8)
        self.assertAlmostEqual(stats.success_rate, 0.8)

    def test_no_swaps_zero_rate(self):
        stats = SwapStats()
        self.assertEqual(stats.success_rate, 0.0)


class TestVRAMMetrics(unittest.TestCase):
    """Tests for VRAMMetrics."""

    def test_defaults(self):
        m = VRAMMetrics()
        self.assertEqual(m.total_gb, 0.0)
        self.assertEqual(m.used_gb, 0.0)
        self.assertEqual(m.free_gb, 0.0)


class TestVRAMLifecycleManager(unittest.TestCase):
    """Tests for VRAMLifecycleManager."""

    def _make_registry(self, total_vram=8.0) -> ModelRegistry:
        reg = ModelRegistry(total_vram_gb=total_vram)
        reg.register(ModelInfo(
            name="master", path="/models/master",
            params_b=7, quant=QuantType.BNB_INT4
        ))
        reg.register(ModelInfo(
            name="coder", path="/models/coder",
            params_b=7, quant=QuantType.BNB_INT4
        ))
        reg.register(ModelInfo(
            name="classifier", path="/models/cls",
            params_b=1.5, quant=QuantType.INT4
        ))
        reg.register_as_resident("classifier")
        return reg

    def _make_manager(self, total_vram=8.0, watchdog=30.0) -> VRAMLifecycleManager:
        reg = self._make_registry(total_vram)
        return VRAMLifecycleManager(reg, watchdog_timeout=watchdog)

    def test_initial_state(self):
        mgr = self._make_manager()
        self.assertEqual(mgr.current_phase, SwapPhase.IDLE)
        self.assertFalse(mgr.is_swapping)
        self.assertIsNone(mgr.active_model)

    def test_swap_context_manager_success(self):
        mgr = self._make_manager()
        load_log = []
        unload_log = []
        mgr.set_load_callback(lambda n: load_log.append(n))
        mgr.set_unload_callback(lambda n: unload_log.append(n))

        with mgr.swap("coder"):
            self.assertEqual(mgr.current_phase, SwapPhase.EXECUTING)
            self.assertEqual(mgr.active_model, "coder")

        # After context exit, master should be restored
        self.assertFalse(mgr.is_swapping)
        self.assertEqual(mgr.current_phase, SwapPhase.IDLE)
        self.assertIn("coder", load_log)
        # Master should be reloaded (if it was active before)
        # Since no model was active initially, no reload

    def test_begin_and_commit(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        self.assertIsInstance(ctx, SwapContext)
        self.assertEqual(ctx.target_model, "coder")
        self.assertTrue(mgr.is_swapping)

        record = mgr.commit_swap(ctx)
        self.assertTrue(record.success)
        self.assertFalse(mgr.is_swapping)

    def test_rollback(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        mgr.rollback_swap(ctx)
        self.assertFalse(mgr.is_swapping)
        self.assertEqual(mgr.current_phase, SwapPhase.IDLE)

    def test_swap_unknown_model_raises(self):
        mgr = self._make_manager()
        with self.assertRaises(SwapError):
            mgr.begin_swap("nonexistent")

    def test_double_swap_raises(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        try:
            with self.assertRaises(SwapError):
                mgr.begin_swap("master")
        finally:
            mgr.rollback_swap(ctx)

    def test_insufficient_vram_raises(self):
        # 2GB VRAM can't fit 7B model
        mgr = self._make_manager(total_vram=2.0)
        with self.assertRaises(InsufficientVRAMError):
            mgr.begin_swap("coder")

    def test_stats_tracking(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        mgr.commit_swap(ctx)

        stats = mgr.stats
        self.assertEqual(stats.total_swaps, 1)
        self.assertEqual(stats.successful_swaps, 1)
        self.assertEqual(stats.failed_swaps, 0)

    def test_failed_swap_tracking(self):
        mgr = self._make_manager()
        try:
            mgr.begin_swap("nonexistent")
        except SwapError:
            pass
        stats = mgr.stats
        self.assertEqual(stats.failed_swaps, 1)

    def test_history_records(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        mgr.commit_swap(ctx)

        self.assertEqual(len(mgr.history), 1)
        self.assertTrue(mgr.history[0].success)

    def test_get_swap_plan(self):
        mgr = self._make_manager()
        plan = mgr.get_swap_plan("coder")
        self.assertIn("unload", plan)
        self.assertIn("fits", plan)

    def test_state_save_restore(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        # First set an active model so save callback fires
        mgr.registry.mark_loaded("master")
        mgr._active_model = "master"

        saved_states = []
        restored_states = []

        mgr.set_state_callbacks(
            save=lambda: saved_states.append("saved") or {"key": "value"},
            restore=lambda state, result: restored_states.append((state, result))
        )

        ctx = mgr.begin_swap("coder")
        self.assertEqual(len(saved_states), 1)

        mgr.commit_swap(ctx, result="task_result")
        self.assertEqual(len(restored_states), 1)
        self.assertEqual(restored_states[0][0], {"key": "value"})
        self.assertEqual(restored_states[0][1], "task_result")

    def test_context_manager_exception_rollback(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        try:
            with mgr.swap("coder"):
                raise RuntimeError("task failed")
        except RuntimeError:
            pass

        self.assertFalse(mgr.is_swapping)
        self.assertEqual(mgr.current_phase, SwapPhase.IDLE)
        # Check history records failure
        self.assertEqual(len(mgr.history), 1)
        self.assertFalse(mgr.history[0].success)

    def test_cpu_fallback(self):
        mgr = self._make_manager()
        fallback_called = []
        mgr._cpu_fallback = lambda name, task: fallback_called.append((name, task))

        result = mgr.execute_with_cpu_fallback("big_model", {"prompt": "test"})
        self.assertEqual(len(fallback_called), 1)
        stats = mgr.stats
        self.assertEqual(stats.cpu_fallback_count, 1)

    def test_cpu_fallback_not_configured(self):
        mgr = self._make_manager()
        with self.assertRaises(SwapError):
            mgr.execute_with_cpu_fallback("model", "task")

    def test_vram_metrics(self):
        mgr = self._make_manager()
        metrics = mgr.get_vram_metrics()
        self.assertIsInstance(metrics, VRAMMetrics)

    def test_active_model_tracking(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        self.assertEqual(mgr.active_model, "coder")
        mgr.commit_swap(ctx)

    def test_swap_record_timing(self):
        mgr = self._make_manager()
        mgr.set_load_callback(lambda n: None)
        mgr.set_unload_callback(lambda n: None)

        ctx = mgr.begin_swap("coder")
        time.sleep(0.01)  # Small delay for measurable duration
        record = mgr.commit_swap(ctx)

        self.assertGreater(record.duration_ms, 0)
        self.assertTrue(record.success)

    def test_watchdog_timeout_short(self):
        """Test with very short watchdog to verify it doesn't hang."""
        mgr = self._make_manager(watchdog=0.05)
        mgr.set_load_callback(lambda n: time.sleep(0.2))  # Longer than watchdog
        mgr.set_unload_callback(lambda n: None)

        # This should still work since the watchdog just sets phase to IDLE
        # but the swap operation completes normally
        ctx = mgr.begin_swap("coder")
        mgr.commit_swap(ctx)


class TestSwapContext(unittest.TestCase):
    """Tests for SwapContext."""

    def test_basic(self):
        ctx = SwapContext(
            manager=None,
            target_model="coder",
            source_model="master",
            saved_state={"data": "test"},
            start_time=100.0
        )
        self.assertEqual(ctx.target_model, "coder")
        self.assertEqual(ctx.source_model, "master")


class TestExceptions(unittest.TestCase):
    """Tests for custom exceptions."""

    def test_swap_error(self):
        e = SwapError("test error")
        self.assertEqual(str(e), "test error")
        self.assertIsInstance(e, Exception)

    def test_watchdog_timeout(self):
        e = WatchdogTimeoutError("timeout")
        self.assertIsInstance(e, SwapError)

    def test_insufficient_vram(self):
        e = InsufficientVRAMError("oom")
        self.assertIsInstance(e, SwapError)


# ============================================================
# Integration Tests
# ============================================================

class TestPluginVRAMIntegration(unittest.TestCase):
    """Integration tests combining plugin system and VRAM lifecycle."""

    def test_plugin_tools_dont_affect_vram_registry(self):
        """Plugin manager and VRAM lifecycle are independent systems."""
        mgr = PluginManager()
        reg = ModelRegistry()
        lifecycle = VRAMLifecycleManager(reg)

        # Plugin tools don't appear in model registry
        self.assertEqual(len(reg.all_models), 0)

        # VRAM manager stats are independent
        self.assertEqual(lifecycle.stats.total_swaps, 0)
        self.assertEqual(mgr.stats["total_tools"], 0)

    def test_full_plugin_lifecycle(self):
        """Test full plugin lifecycle: load -> connect -> register tools -> disconnect."""
        mgr = PluginManager()
        configs = [
            ServerConfig(name="files", transport=TransportType.STDIO, command="python", args=["-m", "file_server"]),
            ServerConfig(name="http_api", transport=TransportType.HTTP, url="http://localhost:8080"),
        ]
        count = mgr.load_servers(configs)
        self.assertEqual(count, 2)

        # Connect all
        self.assertTrue(mgr.connect_server("files"))
        self.assertTrue(mgr.connect_server("http_api"))

        # Register tools
        mgr.register_tools("files", [
            {"name": "read", "description": "Read file"},
            {"name": "write", "description": "Write file"},
        ])
        mgr.register_tools("http_api", [
            {"name": "search", "description": "Search API"},
        ])

        self.assertEqual(len(mgr.get_all_tools()), 3)

        # Disconnect one
        mgr.disconnect_server("files")
        self.assertEqual(len(mgr.get_all_tools()), 1)

        stats = mgr.stats
        self.assertEqual(stats["total_servers"], 2)
        self.assertEqual(stats["total_tools"], 1)

    def test_vram_swap_chain(self):
        """Test multiple sequential swaps between models."""
        reg = ModelRegistry(total_vram_gb=8.0)
        reg.register(ModelInfo(name="master", path="/m", params_b=7, quant=QuantType.BNB_INT4))
        reg.register(ModelInfo(name="coder", path="/c", params_b=7, quant=QuantType.BNB_INT4))
        reg.register(ModelInfo(name="analyst", path="/a", params_b=7, quant=QuantType.BNB_INT4))
        reg.register(ModelInfo(name="cls", path="/cl", params_b=1.5, quant=QuantType.INT4))
        reg.register_as_resident("cls")

        lifecycle = VRAMLifecycleManager(reg)
        lifecycle.set_load_callback(lambda n: None)
        lifecycle.set_unload_callback(lambda n: None)

        # Swap to coder and back
        with lifecycle.swap("coder"):
            self.assertEqual(lifecycle.active_model, "coder")

        # Swap to analyst and back
        with lifecycle.swap("analyst"):
            self.assertEqual(lifecycle.active_model, "analyst")

        stats = lifecycle.stats
        self.assertEqual(stats.total_swaps, 2)
        self.assertEqual(stats.successful_swaps, 2)
        self.assertEqual(len(lifecycle.history), 2)


# ============================================================
# Run all tests
# ============================================================

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    loader = unittest.TestLoader()
    suite = loader.discover(".", pattern="test_phase5.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors
    print(f"Phase 5 Test Results: {passed}/{total} passed")
    if failures or errors:
        print(f"  Failures: {failures}")
        print(f"  Errors: {errors}")
    print("=" * 60)

    sys.exit(0 if (failures == 0 and errors == 0) else 1)
