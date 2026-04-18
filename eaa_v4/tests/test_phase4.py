"""
Phase 4 Tests — System Prompt Optimization

Tests for:
    - prompt_cache.py: Cache splitting, cache keys, cache store
    - memory_loader.py: File loading, includes, frontmatter, path conditions
    - tool_instructions.py: Registry, preferences, generation
    - prompt_assembler.py: 6-layer assembly, dynamic sections, custom prompts

Run: python test_phase4.py
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompt_cache import (
    CacheScope,
    PromptBlock,
    CacheSplitResult,
    PromptCacheStore,
    split_prompt_blocks,
    create_cache_key,
    CACHE_BOUNDARY_MARKER,
)


# ============================================================
# prompt_cache.py Tests
# ============================================================

class TestPromptBlock(unittest.TestCase):
    """Tests for PromptBlock dataclass."""

    def test_token_estimate_basic(self):
        block = PromptBlock(content="Hello world", scope=CacheScope.GLOBAL)
        # "Hello world" = 11 chars, ~2.75 tokens -> floor to 2
        self.assertEqual(block.token_estimate, 2)

    def test_token_estimate_empty(self):
        block = PromptBlock(content="", scope=CacheScope.GLOBAL)
        self.assertEqual(block.token_estimate, 0)

    def test_token_estimate_long(self):
        content = "word " * 100  # 500 chars
        block = PromptBlock(content=content, scope=CacheScope.GLOBAL)
        self.assertEqual(block.token_estimate, 125)

    def test_block_with_label(self):
        block = PromptBlock(
            content="test",
            scope=CacheScope.NEVER,
            label="attribution"
        )
        self.assertEqual(block.label, "attribution")
        self.assertEqual(block.scope, CacheScope.NEVER)


class TestCacheSplitResult(unittest.TestCase):
    """Tests for CacheSplitResult."""

    def test_empty_blocks(self):
        result = CacheSplitResult()
        self.assertEqual(result.total_tokens, 0)
        self.assertEqual(result.cacheable_tokens, 0)
        self.assertEqual(len(result.get_prefix_blocks()), 0)
        self.assertEqual(len(result.get_suffix_blocks()), 0)

    def test_total_tokens(self):
        blocks = [
            PromptBlock(content="a" * 100, scope=CacheScope.GLOBAL),
            PromptBlock(content="b" * 200, scope=CacheScope.SESSION),
        ]
        result = CacheSplitResult(blocks=blocks)
        # 100//4 + 200//4 = 25 + 50 = 75
        self.assertEqual(result.total_tokens, 75)

    def test_cacheable_tokens_excludes_never_and_session(self):
        blocks = [
            PromptBlock(content="a" * 100, scope=CacheScope.NEVER),
            PromptBlock(content="b" * 100, scope=CacheScope.GLOBAL),
            PromptBlock(content="c" * 100, scope=CacheScope.ORG),
            PromptBlock(content="d" * 100, scope=CacheScope.SESSION),
        ]
        result = CacheSplitResult(blocks=blocks)
        # Only GLOBAL and ORG are cacheable: 25 + 25 = 50
        self.assertEqual(result.cacheable_tokens, 50)

    def test_get_prefix_blocks_with_boundary(self):
        blocks = [
            PromptBlock(content="a", scope=CacheScope.GLOBAL, label="static"),
            PromptBlock(content="b", scope=CacheScope.GLOBAL, label="static2"),
            PromptBlock(content="c", scope=CacheScope.SESSION, label="dynamic"),
        ]
        result = CacheSplitResult(blocks=blocks, boundary_index=1)
        prefix = result.get_prefix_blocks()
        self.assertEqual(len(prefix), 2)
        self.assertEqual(prefix[0].label, "static")
        self.assertEqual(prefix[1].label, "static2")

    def test_get_suffix_blocks_with_boundary(self):
        blocks = [
            PromptBlock(content="a", scope=CacheScope.GLOBAL),
            PromptBlock(content="b", scope=CacheScope.SESSION),
        ]
        result = CacheSplitResult(blocks=blocks, boundary_index=0)
        suffix = result.get_suffix_blocks()
        self.assertEqual(len(suffix), 1)
        self.assertEqual(suffix[0].content, "b")

    def test_no_boundary_returns_all_as_prefix(self):
        blocks = [
            PromptBlock(content="a", scope=CacheScope.GLOBAL),
            PromptBlock(content="b", scope=CacheScope.SESSION),
        ]
        result = CacheSplitResult(blocks=blocks, boundary_index=-1)
        self.assertEqual(len(result.get_prefix_blocks()), 2)
        self.assertEqual(len(result.get_suffix_blocks()), 0)


class TestSplitPromptBlocks(unittest.TestCase):
    """Tests for split_prompt_blocks function."""

    def test_split_with_boundary_marker(self):
        prompt = f"static content{CACHE_BOUNDARY_MARKER}dynamic content"
        result = split_prompt_blocks(prompt)
        self.assertGreater(len(result.blocks), 1)

        # Find the global and session blocks
        scopes = [b.scope for b in result.blocks]
        self.assertIn(CacheScope.GLOBAL, scopes)
        self.assertIn(CacheScope.SESSION, scopes)

    def test_split_without_boundary(self):
        prompt = "all content no boundary"
        result = split_prompt_blocks(prompt)
        self.assertEqual(len(result.blocks), 1)
        self.assertEqual(result.blocks[0].scope, CacheScope.GLOBAL)

    def test_split_with_attribution_header(self):
        prompt = f"static{CACHE_BOUNDARY_MARKER}dynamic"
        result = split_prompt_blocks(
            prompt,
            attribution_header="Agent v1.0"
        )
        scopes = [b.scope for b in result.blocks]
        self.assertIn(CacheScope.NEVER, scopes)
        self.assertIn(CacheScope.GLOBAL, scopes)

    def test_split_with_cli_prefix(self):
        prompt = f"static{CACHE_BOUNDARY_MARKER}dynamic"
        result = split_prompt_blocks(
            prompt,
            cli_prefix="mode=full"
        )
        scopes = [b.scope for b in result.blocks]
        self.assertIn(CacheScope.ORG, scopes)

    def test_split_empty_prompt(self):
        result = split_prompt_blocks("")
        self.assertEqual(len(result.blocks), 0)

    def test_split_preserves_boundary_index(self):
        prompt = f"before{CACHE_BOUNDARY_MARKER}after"
        result = split_prompt_blocks(prompt)
        self.assertGreaterEqual(result.boundary_index, 0)

    def test_boundary_label_on_static_block(self):
        prompt = f"instructions{CACHE_BOUNDARY_MARKER}dynamic"
        result = split_prompt_blocks(prompt)
        # Find the global block
        global_block = next(b for b in result.blocks if b.scope == CacheScope.GLOBAL)
        self.assertEqual(global_block.label, "static_instructions")

    def test_multiple_boundaries_uses_first(self):
        prompt = f"a{CACHE_BOUNDARY_MARKER}b{CACHE_BOUNDARY_MARKER}c"
        result = split_prompt_blocks(prompt)
        # Should split at first boundary
        before_blocks = result.get_prefix_blocks()
        after_blocks = result.get_suffix_blocks()
        self.assertGreater(len(before_blocks), 0)
        self.assertGreater(len(after_blocks), 0)


class TestCreateCacheKey(unittest.TestCase):
    """Tests for create_cache_key function."""

    def test_never_scope(self):
        block = PromptBlock(content="x", scope=CacheScope.NEVER, label="header")
        key = create_cache_key(block)
        self.assertTrue(key.startswith("nocache:"))

    def test_global_scope_includes_hash(self):
        block = PromptBlock(content="static content here", scope=CacheScope.GLOBAL, label="static")
        key = create_cache_key(block)
        self.assertTrue(key.startswith("global:"))
        # Should have a hash component
        parts = key.split(":")
        self.assertEqual(len(parts), 3)

    def test_session_scope_includes_session_id(self):
        block = PromptBlock(content="x", scope=CacheScope.SESSION, label="dyn")
        key = create_cache_key(block, session_id="abc123")
        self.assertIn("abc123", key)
        self.assertTrue(key.startswith("session:"))

    def test_same_content_same_hash(self):
        block1 = PromptBlock(content="same content", scope=CacheScope.GLOBAL, label="a")
        block2 = PromptBlock(content="same content", scope=CacheScope.GLOBAL, label="b")
        # Same content, different labels -> different keys
        key1 = create_cache_key(block1)
        key2 = create_cache_key(block2)
        self.assertNotEqual(key1, key2)


class TestPromptCacheStore(unittest.TestCase):
    """Tests for PromptCacheStore."""

    def test_put_and_get(self):
        store = PromptCacheStore()
        store.put("key1", "value1")
        self.assertEqual(store.get("key1"), "value1")

    def test_get_miss_returns_none(self):
        store = PromptCacheStore()
        self.assertIsNone(store.get("nonexistent"))

    def test_hit_tracking(self):
        store = PromptCacheStore()
        store.put("k", "v")
        store.get("k")  # hit
        store.get("k")  # hit
        store.get("missing")  # miss
        stats = store.stats
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)

    def test_hit_rate(self):
        store = PromptCacheStore()
        store.put("k", "v")
        store.get("k")  # hit
        store.get("missing")  # miss
        stats = store.stats
        self.assertAlmostEqual(stats["hit_rate"], 0.5)

    def test_size_tracking(self):
        store = PromptCacheStore()
        store.put("a", "1")
        store.put("b", "2")
        self.assertEqual(store.stats["size"], 2)

    def test_invalidate_all(self):
        store = PromptCacheStore()
        store.put("a", "1")
        store.put("b", "2")
        count = store.invalidate()
        self.assertEqual(count, 2)
        self.assertEqual(store.stats["size"], 0)

    def test_invalidate_by_scope(self):
        store = PromptCacheStore()
        store.put("global:lbl:12345678", "val1")
        store.put("session:id:lbl", "val2")
        store.put("org:lbl:87654321", "val3")

        count = store.invalidate(CacheScope.GLOBAL)
        self.assertEqual(count, 1)
        self.assertEqual(store.stats["size"], 2)

    def test_invalidate_missing_scope(self):
        store = PromptCacheStore()
        store.put("global:x:11111111", "v")
        count = store.invalidate(CacheScope.SESSION)
        self.assertEqual(count, 0)
        self.assertEqual(store.stats["size"], 1)

    def test_overwrite_existing_key(self):
        store = PromptCacheStore()
        store.put("k", "old")
        store.put("k", "new")
        self.assertEqual(store.get("k"), "new")
        self.assertEqual(store.stats["size"], 1)


# ============================================================
# memory_loader.py Tests
# ============================================================

from memory_loader import (
    MAX_MEMORY_FILE_SIZE,
    MAX_INCLUDE_DEPTH,
    MemoryFile,
    MemoryLoadResult,
    _strip_html_comments,
    _parse_yaml_frontmatter,
    _process_includes,
    _check_path_conditions,
    _load_single_file,
    load_all_memory,
)


class TestStripHtmlComments(unittest.TestCase):
    """Tests for _strip_html_comments."""

    def test_removes_single_line_comment(self):
        text = "before<!-- comment -->after"
        result = _strip_html_comments(text)
        self.assertEqual(result, "beforeafter")

    def test_removes_multi_line_comment(self):
        text = "before<!--\nmulti\nline\n-->after"
        result = _strip_html_comments(text)
        self.assertEqual(result, "beforeafter")

    def test_no_comments(self):
        text = "no comments here"
        result = _strip_html_comments(text)
        self.assertEqual(result, "no comments here")

    def test_multiple_comments(self):
        text = "a<!-- x -->b<!-- y -->c"
        result = _strip_html_comments(text)
        self.assertEqual(result, "abc")

    def test_empty_string(self):
        self.assertEqual(_strip_html_comments(""), "")

    def test_only_comment(self):
        self.assertEqual(_strip_html_comments("<!-- everything -->"), "")


class TestParseYamlFrontmatter(unittest.TestCase):
    """Tests for _parse_yaml_frontmatter."""

    def test_valid_frontmatter(self):
        text = "---\nkey: value\n---\nbody content"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata["key"], "value")
        self.assertEqual(body, "body content")

    def test_no_frontmatter(self):
        text = "just body content"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, "just body content")

    def test_incomplete_frontmatter(self):
        text = "---\nkey: value\nno closing"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, text)

    def test_multiple_keys(self):
        text = "---\npaths: src/**\nauthor: test\n---\ncontent"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata["paths"], "src/**")
        self.assertEqual(metadata["author"], "test")
        self.assertEqual(body, "content")

    def test_quoted_values(self):
        text = "---\ntitle: \"Hello World\"\n---\nbody"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata["title"], "Hello World")
        self.assertEqual(body, "body")

    def test_single_quoted_values(self):
        text = "---\ntitle: 'Hello'\n---\nbody"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata["title"], "Hello")

    def test_empty_frontmatter(self):
        text = "---\n---\nbody"
        metadata, body = _parse_yaml_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, "body")


class TestProcessIncludes(unittest.TestCase):
    """Tests for _process_includes."""

    def test_no_includes(self):
        content = "no includes here"
        processed, paths = _process_includes(content, "/tmp")
        self.assertEqual(processed, content)
        self.assertEqual(paths, [])

    def test_single_include(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("included content")
            inc_path = f.name

        try:
            content = f"@include {inc_path}"
            processed, paths = _process_includes(content, "/tmp")
            self.assertEqual(processed, "included content")
            self.assertEqual(len(paths), 1)
        finally:
            os.unlink(inc_path)

    def test_missing_include(self):
        content = "@include /nonexistent/file.md"
        processed, paths = _process_includes(content, "/tmp")
        self.assertIn("not found", processed)
        self.assertEqual(paths, [])

    def test_nested_include(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("outer")
            outer_path = f.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("inner")
            inner_path = f.name

        try:
            # Outer includes inner
            with open(outer_path, 'w') as f:
                f.write(f"@include {inner_path}")

            content = f"@include {outer_path}"
            processed, paths = _process_includes(content, "/tmp")
            self.assertEqual(processed, "inner")
            # Both paths should be recorded
            self.assertEqual(len(paths), 2)
        finally:
            os.unlink(outer_path)
            os.unlink(inner_path)

    def test_circular_include_detection(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(f"@include {f.name}")  # Includes itself
            inc_path = f.name

        try:
            content = f"@include {inc_path}"
            processed, paths = _process_includes(content, "/tmp")
            self.assertIn("circular", processed)
        finally:
            os.unlink(inc_path)

    def test_max_depth_include(self):
        # Create a chain of MAX_INCLUDE_DEPTH + 1 files
        files = []
        try:
            for i in range(MAX_INCLUDE_DEPTH + 2):
                f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
                files.append(f.name)

            # Each file includes the next (must start at line beginning for regex)
            for i in range(len(files) - 1):
                with open(files[i], 'w') as f:
                    f.write(f"level{i}\n@include {files[i + 1]}")

            # Last file has no include
            with open(files[-1], 'w') as f:
                f.write("deepest")

            content = f"@include {files[0]}"
            processed, paths = _process_includes(content, "/tmp")
            self.assertIn("max include depth", processed)
        finally:
            for fp in files:
                os.unlink(fp)

    def test_include_too_large(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("x" * (MAX_MEMORY_FILE_SIZE + 1))
            inc_path = f.name

        try:
            content = f"@include {inc_path}"
            processed, paths = _process_includes(content, "/tmp")
            self.assertIn("too large", processed)
            self.assertEqual(paths, [])
        finally:
            os.unlink(inc_path)


class TestCheckPathConditions(unittest.TestCase):
    """Tests for _check_path_conditions."""

    def test_no_paths_condition(self):
        self.assertTrue(_check_path_conditions({}, "/any/path"))

    def test_exact_match(self):
        metadata = {"paths": "/home/user/project"}
        self.assertTrue(_check_path_conditions(metadata, "/home/user/project"))
        self.assertFalse(_check_path_conditions(metadata, "/other/path"))

    def test_glob_pattern_match(self):
        metadata = {"paths": "/home/user/**"}
        self.assertTrue(_check_path_conditions(metadata, "/home/user/src"))
        self.assertTrue(_check_path_conditions(metadata, "/home/user/src/lib"))
        self.assertFalse(_check_path_conditions(metadata, "/other/path"))

    def test_comma_separated_patterns(self):
        metadata = {"paths": "/home/user/project, /home/user/other"}
        self.assertTrue(_check_path_conditions(metadata, "/home/user/project"))
        self.assertTrue(_check_path_conditions(metadata, "/home/user/other"))
        self.assertFalse(_check_path_conditions(metadata, "/home/user/third"))

    def test_extension_glob(self):
        # Create a temp dir with a .py file
        tmpdir = tempfile.mkdtemp()
        try:
            Path(os.path.join(tmpdir, "test.py")).touch()
            metadata = {"paths": "*.py"}
            self.assertTrue(_check_path_conditions(metadata, tmpdir))

            # No .py file
            tmpdir2 = tempfile.mkdtemp()
            self.assertFalse(_check_path_conditions(metadata, tmpdir2))
            os.rmdir(tmpdir2)
        finally:
            shutil.rmtree(tmpdir)


class TestLoadSingleFile(unittest.TestCase):
    """Tests for _load_single_file."""

    def test_nonexistent_file(self):
        result = _load_single_file("/nonexistent/file.md", "user", 1)
        self.assertIsNone(result)

    def test_basic_file_load(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Test\n\nContent here")
            path = f.name

        try:
            result = _load_single_file(path, "user", 1)
            self.assertIsNotNone(result)
            self.assertIn("Content here", result.content)
            self.assertEqual(result.scope, "user")
            self.assertEqual(result.priority, 1)
        finally:
            os.unlink(path)

    def test_file_with_html_comments(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("before<!-- hidden -->after")
            path = f.name

        try:
            result = _load_single_file(path, "user", 1)
            self.assertIsNotNone(result)
            self.assertEqual(result.content, "beforeafter")
        finally:
            os.unlink(path)

    def test_file_with_frontmatter(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("---\npaths: /nonexistent\n---\nContent")
            path = f.name

        try:
            result = _load_single_file(path, "user", 1)
            # Path condition doesn't match cwd, so should return None
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_file_too_large(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("x" * (MAX_MEMORY_FILE_SIZE + 1))
            path = f.name

        try:
            result = _load_single_file(path, "user", 1)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_tilde_expansion(self):
        # Test that ~ is expanded
        result = _load_single_file("~/nonexistent_eaa_test.md", "user", 1)
        self.assertIsNone(result)
        # Should not crash trying to resolve ~

    def test_file_size_recorded(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("hello world")
            path = f.name

        try:
            result = _load_single_file(path, "user", 1)
            self.assertIsNotNone(result)
            self.assertEqual(result.size, 11)
        finally:
            os.unlink(path)


class TestLoadAllMemory(unittest.TestCase):
    """Tests for load_all_memory."""

    def test_empty_project(self):
        result = load_all_memory(tempfile.mkdtemp())
        self.assertIsInstance(result, MemoryLoadResult)
        # Should have empty combined content since no memory files exist
        # (managed and user dirs don't have EAA.md by default)

    def test_project_memory_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            # Create project EAA.md
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("# Project Rules\n\nAlways use type hints.")

            result = load_all_memory(tmpdir)
            self.assertIn("Always use type hints", result.combined_content)
            # Find the project-scoped file
            project_files = [f for f in result.files if f.scope == "project"]
            self.assertGreater(len(project_files), 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_local_memory_overrides_project(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("Project rule")

            with open(os.path.join(tmpdir, "EAA.local.md"), 'w') as f:
                f.write("Local override")

            result = load_all_memory(tmpdir)
            self.assertIn("Project rule", result.combined_content)
            self.assertIn("Local override", result.combined_content)

            # Local should have higher priority
            local_files = [f for f in result.files if f.scope == "local"]
            project_files = [f for f in result.files if f.scope == "project"]
            self.assertTrue(local_files[0].priority > project_files[0].priority)
        finally:
            shutil.rmtree(tmpdir)

    def test_nested_project_memory(self):
        """Test that EAA.md files are loaded from project root to CWD."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Root EAA.md
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("Root rule")

            # Subdirectory EAA.md
            subdir = os.path.join(tmpdir, "src")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "EAA.md"), 'w') as f:
                f.write("Sub rule")

            # Load from subdirectory
            result = load_all_memory(subdir)
            self.assertIn("Root rule", result.combined_content)
            self.assertIn("Sub rule", result.combined_content)

            project_files = [f for f in result.files if f.scope == "project"]
            self.assertEqual(len(project_files), 2)
        finally:
            shutil.rmtree(tmpdir)

    def test_combined_content_includes_scope_info(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("Test content")

            result = load_all_memory(tmpdir)
            self.assertIn("<!-- memory:", result.combined_content)
        finally:
            shutil.rmtree(tmpdir)

    def test_get_scoped_content(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("Project specific")

            with open(os.path.join(tmpdir, "EAA.local.md"), 'w') as f:
                f.write("Local specific")

            result = load_all_memory(tmpdir)
            local_content = result.get_scoped_content("local")
            self.assertEqual(local_content, "Local specific")
        finally:
            shutil.rmtree(tmpdir)


class TestMemoryFile(unittest.TestCase):
    """Tests for MemoryFile dataclass."""

    def test_size_auto_calculated(self):
        mf = MemoryFile(path="/test", content="hello", scope="user", priority=1)
        self.assertEqual(mf.size, 5)

    def test_includes_default_empty(self):
        mf = MemoryFile(path="/test", content="x", scope="user", priority=1)
        self.assertEqual(mf.includes, [])


class TestMemoryLoadResult(unittest.TestCase):
    """Tests for MemoryLoadResult."""

    def test_empty_result(self):
        result = MemoryLoadResult()
        self.assertEqual(result.combined_content, "")
        self.assertEqual(result.total_size, 0)
        self.assertEqual(result.errors, [])

    def test_get_scoped_content_empty(self):
        result = MemoryLoadResult()
        self.assertEqual(result.get_scoped_content("user"), "")


# ============================================================
# tool_instructions.py Tests
# ============================================================

from tool_instructions import (
    ToolInstruction,
    ToolPreference,
    DEFAULT_PREFERENCES,
    ToolInstructionRegistry,
    create_default_registry,
)


class TestToolInstruction(unittest.TestCase):
    """Tests for ToolInstruction dataclass."""

    def test_basic_creation(self):
        ti = ToolInstruction(
            name="Read",
            description="Read files",
            usage="Provide path"
        )
        self.assertEqual(ti.name, "Read")
        self.assertFalse(ti.is_read_only)
        self.assertFalse(ti.is_destructive)
        self.assertEqual(ti.examples, [])
        self.assertEqual(ti.warnings, [])

    def test_with_examples_and_warnings(self):
        ti = ToolInstruction(
            name="Bash",
            description="Run commands",
            usage="Provide command",
            examples=["echo hello", "ls -la"],
            warnings=["Dangerous"],
            is_destructive=True
        )
        self.assertEqual(len(ti.examples), 2)
        self.assertEqual(len(ti.warnings), 1)
        self.assertTrue(ti.is_destructive)


class TestToolPreference(unittest.TestCase):
    """Tests for ToolPreference."""

    def test_basic_preference(self):
        pref = ToolPreference(
            preferred="Read",
            inferior=["cat", "head"],
            reason="Safer"
        )
        self.assertEqual(pref.preferred, "Read")
        self.assertEqual(len(pref.inferior), 2)

    def test_empty_inferior(self):
        pref = ToolPreference(preferred="Bash", inferior=[], reason="reserved")
        self.assertEqual(pref.inferior, [])


class TestDefaultPreferences(unittest.TestCase):
    """Tests for DEFAULT_PREFERENCES."""

    def test_six_preferences(self):
        self.assertEqual(len(DEFAULT_PREFERENCES), 6)

    def test_read_preference(self):
        read_pref = DEFAULT_PREFERENCES[0]
        self.assertEqual(read_pref.preferred, "Read")
        self.assertIn("cat", read_pref.inferior)

    def test_edit_preference(self):
        edit_pref = DEFAULT_PREFERENCES[1]
        self.assertEqual(edit_pref.preferred, "Edit")
        self.assertIn("sed", edit_pref.inferior)

    def test_bash_preference_no_inferior(self):
        bash_pref = DEFAULT_PREFERENCES[5]
        self.assertEqual(bash_pref.preferred, "Bash")
        self.assertEqual(bash_pref.inferior, [])


class TestToolInstructionRegistry(unittest.TestCase):
    """Tests for ToolInstructionRegistry."""

    def test_register_and_get(self):
        reg = ToolInstructionRegistry()
        ti = ToolInstruction(name="Test", description="desc", usage="use")
        reg.register(ti)
        result = reg.get("Test")
        self.assertIsNotNone(result)
        self.assertEqual(result.description, "desc")

    def test_unregister(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(name="X", description="", usage=""))
        reg.unregister("X")
        self.assertIsNone(reg.get("X"))

    def test_registered_tools_list(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(name="A", description="", usage=""))
        reg.register(ToolInstruction(name="B", description="", usage=""))
        self.assertEqual(sorted(reg.registered_tools), ["A", "B"])

    def test_get_nonexistent(self):
        reg = ToolInstructionRegistry()
        self.assertIsNone(reg.get("nonexistent"))

    def test_add_preference(self):
        reg = ToolInstructionRegistry()
        pref = ToolPreference(
            preferred="Custom",
            inferior=["old"],
            reason="testing"
        )
        reg.add_preference(pref)
        result = reg.get_preference("old")
        self.assertIsNotNone(result)
        self.assertEqual(result.preferred, "Custom")

    def test_get_preference_not_found(self):
        reg = ToolInstructionRegistry()
        self.assertIsNone(reg.get_preference("nonexistent_command"))

    def test_get_preference_matches_prefix(self):
        reg = ToolInstructionRegistry()
        result = reg.get_preference("cat -n file.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result.preferred, "Read")

    def test_generate_tool_section_empty(self):
        reg = ToolInstructionRegistry()
        self.assertEqual(reg.generate_tool_section(), "")

    def test_generate_tool_section_with_tools(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(
            name="Read",
            description="Read files",
            usage="Provide path",
            examples=["Read a file"]
        ))
        section = reg.generate_tool_section()
        self.assertIn("## Tool Usage Guide", section)
        self.assertIn("### Read", section)
        self.assertIn("Read files", section)
        self.assertIn("Read a file", section)

    def test_generate_tool_section_filtered(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(name="Read", description="R", usage="U"))
        reg.register(ToolInstruction(name="Write", description="W", usage="U"))
        section = reg.generate_tool_section(tool_names=["Read"])
        self.assertIn("### Read", section)
        self.assertNotIn("### Write", section)

    def test_generate_tool_section_read_only_flag(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(
            name="Read", description="R", usage="U", is_read_only=True
        ))
        section = reg.generate_tool_section()
        self.assertIn("read-only", section)

    def test_generate_tool_section_destructive_flag(self):
        reg = ToolInstructionRegistry()
        reg.register(ToolInstruction(
            name="Bash", description="B", usage="U", is_destructive=True
        ))
        section = reg.generate_tool_section()
        self.assertIn("destructive", section)

    def test_generate_preference_section(self):
        reg = ToolInstructionRegistry()
        section = reg.generate_preference_section()
        self.assertIn("## Tool Preference Rules", section)
        self.assertIn("Read", section)
        self.assertIn("Edit", section)
        self.assertIn("parallel", section)

    def test_generate_preference_section_has_reasons(self):
        reg = ToolInstructionRegistry()
        section = reg.generate_preference_section()
        # At least one preference should have a reason
        self.assertIn("fuzzy matching", section)

    def test_bash_reserved_message(self):
        reg = ToolInstructionRegistry()
        section = reg.generate_preference_section()
        self.assertIn("reserved for shell execution", section)


class TestCreateDefaultRegistry(unittest.TestCase):
    """Tests for create_default_registry."""

    def test_creates_registry_with_tools(self):
        reg = create_default_registry()
        self.assertGreater(len(reg.registered_tools), 0)

    def test_has_core_tools(self):
        reg = create_default_registry()
        for name in ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]:
            self.assertIn(name, reg.registered_tools)

    def test_read_is_read_only(self):
        reg = create_default_registry()
        read = reg.get("Read")
        self.assertTrue(read.is_read_only)

    def test_bash_is_destructive(self):
        reg = create_default_registry()
        bash = reg.get("Bash")
        self.assertTrue(bash.is_destructive)

    def test_edit_has_warnings(self):
        reg = create_default_registry()
        edit = reg.get("Edit")
        self.assertGreater(len(edit.warnings), 0)

    def test_bash_mentions_dedicated_tools(self):
        reg = create_default_registry()
        bash = reg.get("Bash")
        self.assertTrue(any("dedicated" in w.lower() or "ALWAYS" in w for w in bash.warnings))

    def test_preference_lookup_works(self):
        reg = create_default_registry()
        # Looking up "cat" should recommend Read
        pref = reg.get_preference("cat")
        self.assertIsNotNone(pref)
        self.assertEqual(pref.preferred, "Read")


# ============================================================
# prompt_assembler.py Tests
# ============================================================

from prompt_assembler import (
    DEFAULT_BEHAVIORAL_INSTRUCTIONS,
    PromptConfig,
    AssembledPrompt,
    PromptAssembler,
)


class TestDefaultBehavioralInstructions(unittest.TestCase):
    """Tests for DEFAULT_BEHAVIORAL_INSTRUCTIONS."""

    def test_eight_instructions(self):
        self.assertEqual(len(DEFAULT_BEHAVIORAL_INSTRUCTIONS), 8)

    def test_security_instruction_present(self):
        self.assertTrue(any("security" in i.lower() for i in DEFAULT_BEHAVIORAL_INSTRUCTIONS))

    def test_code_minimalism_present(self):
        self.assertTrue(any("minimalism" in i.lower() for i in DEFAULT_BEHAVIORAL_INSTRUCTIONS))


class TestPromptConfig(unittest.TestCase):
    """Tests for PromptConfig."""

    def test_defaults(self):
        config = PromptConfig()
        self.assertEqual(config.agent_name, "EAA")
        self.assertEqual(config.agent_version, "4.0")
        self.assertEqual(config.model_name, "Qwen2.5-7B-Instruct")
        self.assertEqual(config.language, "en")

    def test_custom_values(self):
        config = PromptConfig(
            agent_name="Custom",
            session_id="abc123",
            language="zh"
        )
        self.assertEqual(config.agent_name, "Custom")
        self.assertEqual(config.session_id, "abc123")
        self.assertEqual(config.language, "zh")


class TestAssembledPrompt(unittest.TestCase):
    """Tests for AssembledPrompt."""

    def test_empty_prompt(self):
        ap = AssembledPrompt()
        self.assertEqual(ap.full_prompt, "")
        self.assertEqual(ap.total_chars, 0)
        self.assertEqual(ap.token_estimate, 0)

    def test_auto_calculated_size(self):
        ap = AssembledPrompt(full_prompt="x" * 100)
        self.assertEqual(ap.total_chars, 100)
        self.assertEqual(ap.token_estimate, 25)


class TestPromptAssembler(unittest.TestCase):
    """Tests for PromptAssembler."""

    def _make_assembler(self, **kwargs) -> PromptAssembler:
        config = PromptConfig(**kwargs)
        return PromptAssembler(config=config)

    def test_basic_assembly(self):
        asm = self._make_assembler()
        result = asm.assemble()
        self.assertIsInstance(result, AssembledPrompt)
        self.assertGreater(len(result.full_prompt), 0)

    def test_layer0_attribution(self):
        asm = self._make_assembler(agent_name="TestAgent", agent_version="1.0")
        result = asm.assemble()
        self.assertIn("TestAgent", result.layers["layer0_attribution"])
        self.assertIn("1.0", result.layers["layer0_attribution"])

    def test_layer1_has_static_sections(self):
        asm = self._make_assembler()
        result = asm.assemble()
        layer1 = result.layers["layer1_static"]
        self.assertIn("Introduction", layer1)
        self.assertIn("System Behavior", layer1)
        self.assertIn("Doing Tasks", layer1)
        self.assertIn("Actions", layer1)
        self.assertIn("Using Your Tools", layer1)
        self.assertIn("Tone & Style", layer1)
        self.assertIn("Output Efficiency", layer1)

    def test_layer1_includes_behavioral_instructions(self):
        asm = self._make_assembler()
        result = asm.assemble()
        layer1 = result.layers["layer1_static"]
        for instr in DEFAULT_BEHAVIORAL_INSTRUCTIONS:
            # Check at least a key phrase from each instruction
            words = instr.split()[:3]
            found = any(w in layer1 for w in words if len(w) > 4)
            self.assertTrue(found, f"Instruction not found: {instr[:50]}")

    def test_layer1_with_tools_includes_tool_section(self):
        reg = create_default_registry()
        config = PromptConfig()
        asm = PromptAssembler(config=config, tool_registry=reg)
        result = asm.assemble()
        layer1_tools = result.layers["layer1_static_with_tools"]
        self.assertIn("Tool Usage Guide", layer1_tools)

    def test_layer3_dynamic_has_session_id(self):
        asm = self._make_assembler(session_id="sess-42")
        result = asm.assemble()
        self.assertIn("sess-42", result.layers["layer3_dynamic"])

    def test_layer3_dynamic_has_environment(self):
        asm = self._make_assembler(working_dir="/test/dir")
        result = asm.assemble()
        self.assertIn("working_dir", result.layers["layer3_dynamic"])

    def test_layer3_language_preference(self):
        asm = self._make_assembler(language="zh")
        result = asm.assemble()
        self.assertIn("zh", result.layers["layer3_dynamic"])

    def test_layer3_no_language_when_en(self):
        asm = self._make_assembler(language="en")
        result = asm.assemble()
        # Should not include language_preference for English (default)
        self.assertNotIn("language_preference", result.layers["layer3_dynamic"])

    def test_layer4_has_current_date(self):
        asm = self._make_assembler()
        result = asm.assemble()
        layer4 = result.layers["layer4_context"]
        self.assertIn("current_date", layer4)
        # Should have current year
        self.assertIn("202", layer4)

    def test_layer5_custom_prompt_override(self):
        asm = self._make_assembler(
            override_prompt="Always respond in JSON",
            default_prompt="Be helpful"
        )
        result = asm.assemble()
        layer5 = result.layers["layer5_custom"]
        self.assertIn("JSON", layer5)
        # Default should NOT be present since override takes priority
        self.assertNotIn("Be helpful", layer5)

    def test_layer5_falls_through_to_default(self):
        asm = self._make_assembler(
            default_prompt="Be helpful"
        )
        result = asm.assemble()
        layer5 = result.layers["layer5_custom"]
        self.assertIn("Be helpful", layer5)

    def test_layer5_append_always_added(self):
        asm = self._make_assembler(
            override_prompt="Override",
            append_prompt="Also: be concise"
        )
        result = asm.assemble()
        layer5 = result.layers["layer5_custom"]
        self.assertIn("Override", layer5)
        self.assertIn("concise", layer5)

    def test_layer5_priority_order(self):
        """Test: coordinator > default when no override/agent."""
        asm = self._make_assembler(
            coordinator_prompt="Coord rule",
            default_prompt="Default rule"
        )
        result = asm.assemble()
        layer5 = result.layers["layer5_custom"]
        self.assertIn("Coord rule", layer5)
        self.assertNotIn("Default rule", layer5)

    def test_dynamic_section_registration(self):
        asm = self._make_assembler()
        asm.register_dynamic_section("git_status", lambda: "branch: main")
        result = asm.assemble()
        self.assertIn("git_status", result.layers["layer3_dynamic"])
        self.assertIn("branch: main", result.layers["layer3_dynamic"])

    def test_dynamic_section_error_doesnt_crash(self):
        asm = self._make_assembler()
        asm.register_dynamic_section("broken", lambda: (_ for _ in ()).throw(RuntimeError("test")))
        result = asm.assemble()
        # Should still assemble without crashing
        self.assertGreater(len(result.full_prompt), 0)

    def test_dynamic_section_empty_omitted(self):
        asm = self._make_assembler()
        asm.register_dynamic_section("empty", lambda: "")
        result = asm.assemble()
        self.assertNotIn("empty", result.layers["layer3_dynamic"])

    def test_full_prompt_has_boundary_marker(self):
        asm = self._make_assembler()
        result = asm.assemble()
        self.assertIn(CACHE_BOUNDARY_MARKER, result.full_prompt)

    def test_full_prompt_has_all_layers(self):
        asm = self._make_assembler(session_id="test-session")
        result = asm.assemble()
        # Should contain content from all layers
        self.assertIn("agent_info", result.full_prompt)  # L0
        self.assertIn("Introduction", result.full_prompt)  # L1
        self.assertIn("test-session", result.full_prompt)  # L3
        self.assertIn("current_date", result.full_prompt)  # L4

    def test_assemble_with_memory(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("# Rules\nUse Python 3.12+")

            asm = self._make_assembler(project_root=tmpdir)
            memory = load_all_memory(tmpdir)
            result = asm.assemble(memory_result=memory)
            self.assertIn("Use Python 3.12+", result.full_prompt)
            self.assertIn("system-reminder", result.full_prompt)
        finally:
            shutil.rmtree(tmpdir)

    def test_assemble_with_tool_filtering(self):
        reg = create_default_registry()
        config = PromptConfig()
        asm = PromptAssembler(config=config, tool_registry=reg)
        result = asm.assemble(tool_names=["Read"])
        self.assertIn("### Read", result.full_prompt)
        self.assertNotIn("### Bash", result.full_prompt)

    def test_token_estimate_reasonable(self):
        asm = self._make_assembler()
        result = asm.assemble()
        # Token estimate should be positive and less than char count
        self.assertGreater(result.token_estimate, 0)
        self.assertLessEqual(result.token_estimate, result.total_chars)

    def test_cache_blocks_populated(self):
        asm = self._make_assembler()
        result = asm.assemble()
        self.assertGreater(len(result.cache_blocks), 0)

    def test_layers_dict_has_all_layers(self):
        asm = self._make_assembler()
        result = asm.assemble()
        expected_keys = [
            "layer0_attribution",
            "layer1_static",
            "layer1_static_with_tools",
            "layer3_dynamic",
            "layer4_context",
            "layer5_custom",
        ]
        for key in expected_keys:
            self.assertIn(key, result.layers, f"Missing layer: {key}")

    def test_custom_model_name_in_attribution(self):
        asm = self._make_assembler(model_name="Llama-3-70B")
        result = asm.assemble()
        self.assertIn("Llama-3-70B", result.layers["layer0_attribution"])


# ============================================================
# Integration Tests
# ============================================================

class TestFullIntegration(unittest.TestCase):
    """End-to-end tests combining all Phase 4 modules."""

    def _make_assembler(self, **kwargs) -> PromptAssembler:
        config = PromptConfig(**kwargs)
        return PromptAssembler(config=config)

    def test_full_assembly_with_all_features(self):
        """Test full pipeline: registry + memory + assembler + cache."""
        # Create temp project with memory file
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("# Project\nUse tabs not spaces.")

            # Create an included file
            with open(os.path.join(tmpdir, "standards.md"), 'w') as f:
                f.write("Max line length: 120")

            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("@include standards.md\n\nUse tabs not spaces.")

            # Build registry
            registry = create_default_registry()
            registry.register(ToolInstruction(
                name="CustomTool",
                description="A custom tool for testing",
                usage="custom_tool --arg value",
                examples=["custom_tool --help"],
                warnings=["Test only"],
            ))

            # Build assembler
            config = PromptConfig(
                project_root=tmpdir,
                session_id="integ-test",
                append_prompt="Always add tests."
            )
            cache_store = PromptCacheStore()
            asm = PromptAssembler(config=config, tool_registry=registry, cache_store=cache_store)
            asm.register_dynamic_section("test_status", lambda: "All tests passing")

            # Assemble
            memory = load_all_memory(tmpdir)
            result = asm.assemble(memory_result=memory)

            # Verify
            self.assertIn("EAA", result.full_prompt)
            self.assertIn("Use tabs not spaces", result.full_prompt)
            self.assertIn("Max line length: 120", result.full_prompt)
            self.assertIn("Always add tests.", result.full_prompt)
            self.assertIn("All tests passing", result.full_prompt)
            self.assertIn("### CustomTool", result.full_prompt)
            self.assertIn("### Read", result.full_prompt)
            self.assertGreater(result.token_estimate, 0)

            # Verify caching
            for block in result.cache_blocks:
                key = create_cache_key(block, session_id="integ-test")
                if block.scope not in (CacheScope.NEVER, CacheScope.SESSION):
                    cache_store.put(key, block.content)
                    self.assertIsNotNone(cache_store.get(key))

            stats = cache_store.stats
            self.assertGreater(stats["size"], 0)

        finally:
            shutil.rmtree(tmpdir)

    def test_assembler_cache_integration(self):
        """Test that split blocks can be cached and retrieved."""
        asm = self._make_assembler(session_id="cache-test")
        result = asm.assemble()
        cache_store = PromptCacheStore()

        # Simulate caching all cacheable blocks
        cached_count = 0
        for block in result.cache_blocks:
            if block.scope not in (CacheScope.NEVER, CacheScope.SESSION):
                key = create_cache_key(block, session_id="cache-test")
                cache_store.put(key, block.content)
                cached_count += 1

        self.assertEqual(cached_count, cache_store.stats["size"])

        # Verify retrieval
        hits = 0
        for block in result.cache_blocks:
            key = create_cache_key(block, session_id="cache-test")
            if cache_store.get(key) is not None:
                hits += 1

        self.assertEqual(hits, cached_count)

    def test_memory_loader_with_includes_in_assembly(self):
        """Test that @include in memory files works end-to-end."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create included file
            with open(os.path.join(tmpdir, "rules.md"), 'w') as f:
                f.write("Follow PEP 8.")

            # Create main memory with include
            with open(os.path.join(tmpdir, "EAA.md"), 'w') as f:
                f.write("@include rules.md\n\nAlso use type hints.")

            asm = self._make_assembler(project_root=tmpdir)
            result = asm.assemble()

            self.assertIn("Follow PEP 8.", result.full_prompt)
            self.assertIn("Also use type hints", result.full_prompt)
        finally:
            shutil.rmtree(tmpdir)

    def test_preference_system_in_full_prompt(self):
        """Test that tool preferences appear in assembled prompt."""
        registry = create_default_registry()
        config = PromptConfig()
        asm = PromptAssembler(config=config, tool_registry=registry)
        result = asm.assemble()

        # Should contain preference rules
        self.assertIn("Tool Preference Rules", result.full_prompt)
        self.assertIn("instead of", result.full_prompt)


# ============================================================
# Run all tests
# ============================================================

if __name__ == "__main__":
    # Change to the test directory for relative imports
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Discover and run all tests
    loader = unittest.TestLoader()
    suite = loader.discover(".", pattern="test_phase4.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors
    print(f"Phase 4 Test Results: {passed}/{total} passed")
    if failures or errors:
        print(f"  Failures: {failures}")
        print(f"  Errors: {errors}")
    print("=" * 60)

    sys.exit(0 if (failures == 0 and errors == 0) else 1)
