"""
EAA Code Tools - Phase 3
Code execution, linting, formatting, testing, and git operations.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import sys
import json
import subprocess
import traceback
import tempfile
import shutil
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

try:
    from eaa_agent_tools import ToolResult
except ImportError:
    @dataclass
    class ToolResult:
        success: bool
        output: str
        error: Optional[str] = None
        def to_dict(self):
            return {"success": self.success, "output": self.output, "error": self.error}


# ─── CODE RUN ─────────────────────────────────────────────────────────────────
def tool_code_run(code: str, language: str = "python", timeout: int = 30, save_output: str = None) -> ToolResult:
    """
    Execute code safely in a temporary file.
    language: python, javascript, batch, powershell
    """
    try:
        ext_map = {
            "python": ".py",
            "javascript": ".js",
            "js": ".js",
            "batch": ".bat",
            "powershell": ".ps1",
        }
        ext = ext_map.get(language.lower(), ".py")

        # Create temp file
        tmp_dir = tempfile.mkdtemp(prefix="eaa_code_")
        tmp_file = os.path.join(tmp_dir, f"code{ext}")

        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            if language.lower() in ("python",):
                cmd = [sys.executable, tmp_file]
            elif language.lower() in ("javascript", "js"):
                cmd = ["node", tmp_file]
            elif language.lower() == "powershell":
                cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", tmp_file]
            elif language.lower() == "batch":
                cmd = ["cmd", "/c", tmp_file]
            else:
                cmd = [sys.executable, tmp_file]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp_dir
            )

            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            if len(output) > 5000:
                output = output[:5000] + "\n...[truncated]"

            if save_output:
                save_path = os.path.expanduser(save_output)
                os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
                with open(save_path, "w") as f:
                    f.write(output)
                output += f"\n\nOutput saved to: {save_path}"

            if result.returncode != 0:
                return ToolResult(False, output, f"Exit code: {result.returncode}")

            return ToolResult(True, output)

        finally:
            # Cleanup temp files
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"Code timed out after {timeout} seconds")
    except FileNotFoundError:
        return ToolResult(False, "", f"Runtime not found for language: {language}. Install Node.js for JavaScript.")
    except Exception as e:
        return ToolResult(False, "", f"Code execution failed: {str(e)}")


# ─── CODE LINT ────────────────────────────────────────────────────────────────
def tool_code_lint(file_path: str, language: str = "auto") -> ToolResult:
    """
    Check code quality/linting issues.
    language: auto, python, javascript
    """
    try:
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            return ToolResult(False, "", f"File not found: {file_path}")

        if language == "auto":
            ext = os.path.splitext(file_path)[1].lower()
            language = {"py": "python", "js": "javascript", "ts": "javascript"}.get(ext.lstrip("."), "python")

        if language == "python":
            # Use py_compile for syntax check
            try:
                compile(open(file_path).read(), file_path, 'exec')
                syntax_ok = "✓ No syntax errors"
            except SyntaxError as se:
                syntax_ok = f"✗ Syntax Error at line {se.lineno}: {se.msg}"

            # Try flake8 if available
            try:
                result = subprocess.run(
                    ["flake8", "--max-line-length=120", "--statistics", file_path],
                    capture_output=True, text=True, timeout=15
                )
                lint_output = result.stdout.strip()
                if lint_output:
                    return ToolResult(True, f"{syntax_ok}\n\nFlake8 Issues:\n{lint_output}")
                return ToolResult(True, f"{syntax_ok}\n\n✓ No linting issues found (flake8)")
            except FileNotFoundError:
                return ToolResult(True, f"{syntax_ok}\n\n(Install flake8 for detailed linting: pip install flake8)")
            except Exception as e:
                return ToolResult(True, f"{syntax_ok}\n\nLint check error: {e}")

        elif language in ("javascript", "js"):
            try:
                result = subprocess.run(
                    ["npx", "eslint", file_path],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    return ToolResult(True, "✓ No ESLint issues found")
                return ToolResult(True, f"ESLint Issues:\n{result.stdout}")
            except FileNotFoundError:
                return ToolResult(True, "ESLint not available. Install: npm install -g eslint")
            except Exception as e:
                return ToolResult(False, "", f"JS lint failed: {e}")
        else:
            return ToolResult(False, "", f"Unsupported language for linting: {language}")

    except Exception as e:
        return ToolResult(False, "", f"Code lint failed: {str(e)}")


# ─── CODE FORMAT ──────────────────────────────────────────────────────────────
def tool_code_format(file_path: str, language: str = "auto") -> ToolResult:
    """
    Format code using formatters (black for Python, prettier for JS).
    Creates a backup before formatting.
    """
    try:
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            return ToolResult(False, "", f"File not found: {file_path}")

        if language == "auto":
            ext = os.path.splitext(file_path)[1].lower()
            language = {"py": "python", "js": "javascript", "ts": "javascript", "json": "javascript"}.get(ext.lstrip("."), "python")

        # Backup
        backup_path = file_path + ".backup"
        shutil.copy2(file_path, backup_path)

        if language == "python":
            try:
                result = subprocess.run(
                    ["black", "--line-length=100", file_path],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    return ToolResult(True, f"Formatted with Black.\nBackup: {backup_path}\n{result.stdout}")
                else:
                    # Restore backup on failure
                    shutil.move(backup_path, file_path)
                    return ToolResult(False, "", f"Black formatting failed:\n{result.stderr}")
            except FileNotFoundError:
                return ToolResult(False, "", "Black not installed. Install: pip install black")
            except Exception as e:
                shutil.move(backup_path, file_path)
                return ToolResult(False, "", f"Format failed: {e}")

        elif language in ("javascript", "js"):
            try:
                result = subprocess.run(
                    ["npx", "prettier", "--write", file_path],
                    capture_output=True, text=True, timeout=15
                )
                return ToolResult(True, f"Formatted with Prettier.\nBackup: {backup_path}\n{result.stdout}")
            except FileNotFoundError:
                return ToolResult(False, "", "Prettier not available. Install: npm install -g prettier")
            except Exception as e:
                return ToolResult(False, "", f"JS format failed: {e}")
        else:
            return ToolResult(False, "", f"Unsupported language: {language}")

    except Exception as e:
        return ToolResult(False, "", f"Code format failed: {str(e)}")


# ─── CODE TEST ────────────────────────────────────────────────────────────────
def tool_code_test(path: str = ".", test_type: str = "pytest", verbose: bool = True) -> ToolResult:
    """
    Run unit tests.
    path: Directory or specific test file
    test_type: pytest, unittest
    """
    try:
        path = os.path.expanduser(path)

        if test_type == "pytest":
            cmd = ["python", "-m", "pytest", path, "-v" if verbose else "-q", "--tb=short"]
        elif test_type == "unittest":
            cmd = ["python", "-m", "unittest", "discover", "-v" if verbose else "", "-s", path]
        else:
            return ToolResult(False, "", f"Unknown test type: {test_type}. Use 'pytest' or 'unittest'")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=os.path.dirname(path) or ".")

        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"

        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"

        success = result.returncode == 0
        return ToolResult(success, output, None if success else f"Tests failed (exit code: {result.returncode})")

    except subprocess.TimeoutExpired:
        return ToolResult(False, "", "Tests timed out after 60 seconds")
    except Exception as e:
        return ToolResult(False, "", f"Test execution failed: {str(e)}")


# ─── GIT STATUS ───────────────────────────────────────────────────────────────
def tool_git_status(repo_path: str = ".") -> ToolResult:
    """Check git repository status."""
    try:
        repo_path = os.path.expanduser(repo_path)
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-b"],
            capture_output=True, text=True, timeout=10, cwd=repo_path
        )
        if result.returncode != 0:
            return ToolResult(False, "", f"Not a git repository: {repo_path}\n{result.stderr}")

        lines = result.stdout.strip().split("\n")
        output_parts = []

        # Branch info
        for line in lines:
            if line.startswith("##"):
                output_parts.append(f"Branch: {line[2:]}")
                break

        # Files
        staged, modified, untracked = [], [], []
        for line in lines:
            if line.startswith("##"):
                continue
            if not line:
                continue
            status = line[:2]
            filepath = line[3:]
            if status[0] != " " and status[0] != "?":
                staged.append(f"  STAGED   {filepath}")
            elif status[1] != " " and status[1] != "?":
                modified.append(f"  MODIFIED  {filepath}")
            elif "?" in status:
                untracked.append(f"  UNTRACKED {filepath}")

        if staged: output_parts.append(f"Staged ({len(staged)}):\n" + "\n".join(staged))
        if modified: output_parts.append(f"Modified ({len(modified)}):\n" + "\n".join(modified))
        if untracked: output_parts.append(f"Untracked ({len(untracked)}):\n" + "\n".join(untracked))
        if not staged and not modified and not untracked:
            output_parts.append("✓ Working tree clean")

        return ToolResult(True, "\n".join(output_parts))

    except FileNotFoundError:
        return ToolResult(False, "", "Git not installed")
    except Exception as e:
        return ToolResult(False, "", f"Git status failed: {str(e)}")


# ─── GIT COMMIT ───────────────────────────────────────────────────────────────
def tool_git_commit(repo_path: str = ".", message: str = "Update", add_all: bool = True) -> ToolResult:
    """Commit changes in a git repository."""
    try:
        repo_path = os.path.expanduser(repo_path)

        if add_all:
            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10, cwd=repo_path)

        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=10, cwd=repo_path
        )

        if result.returncode == 0:
            return ToolResult(True, f"Committed: {message}\n{result.stdout}")
        else:
            return ToolResult(False, result.stderr, f"Commit failed (exit code: {result.returncode})")

    except FileNotFoundError:
        return ToolResult(False, "", "Git not installed")
    except Exception as e:
        return ToolResult(False, "", f"Git commit failed: {str(e)}")


# ─── GIT DIFF ─────────────────────────────────────────────────────────────────
def tool_git_diff(repo_path: str = ".", file_path: str = None, staged: bool = False) -> ToolResult:
    """Show git differences."""
    try:
        repo_path = os.path.expanduser(repo_path)
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        if file_path:
            cmd.append(os.path.expanduser(file_path))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=repo_path)

        if not result.stdout.strip():
            return ToolResult(True, "No differences found")

        output = result.stdout[:5000]
        if len(result.stdout) > 5000:
            output += "\n...[truncated]"

        return ToolResult(True, output)

    except Exception as e:
        return ToolResult(False, "", f"Git diff failed: {str(e)}")


# ─── GIT LOG ──────────────────────────────────────────────────────────────────
def tool_git_log(repo_path: str = ".", count: int = 10, oneline: bool = True) -> ToolResult:
    """Show git commit history."""
    try:
        repo_path = os.path.expanduser(repo_path)
        cmd = ["git", "log"]
        if oneline:
            cmd.extend(["--oneline", f"-{count}"])
        else:
            cmd.extend([f"-{count}", "--stat"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=repo_path)
        return ToolResult(True, result.stdout.strip() or "No commits found")

    except Exception as e:
        return ToolResult(False, "", f"Git log failed: {str(e)}")


# ─── GIT BRANCH ───────────────────────────────────────────────────────────────
def tool_git_branch(repo_path: str = ".", create: str = None) -> ToolResult:
    """List or create git branches."""
    try:
        repo_path = os.path.expanduser(repo_path)

        if create:
            result = subprocess.run(
                ["git", "checkout", "-b", create],
                capture_output=True, text=True, timeout=10, cwd=repo_path
            )
            if result.returncode == 0:
                return ToolResult(True, f"Created and switched to branch: {create}")
            return ToolResult(False, "", f"Branch creation failed: {result.stderr}")

        result = subprocess.run(
            ["git", "branch", "-a"],
            capture_output=True, text=True, timeout=10, cwd=repo_path
        )
        return ToolResult(True, result.stdout.strip())

    except Exception as e:
        return ToolResult(False, "", f"Git branch failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_code_tools(registry) -> None:
    """Register all code tools with the existing ToolRegistry."""
    registry.register("code_run", tool_code_run, "Execute code safely. Args: code, language (python/js/batch/powershell), timeout")
    registry.register("code_lint", tool_code_lint, "Check code quality. Args: file_path, language (auto/python/js)")
    registry.register("code_format", tool_code_format, "Format code. Args: file_path, language (auto/python/js)")
    registry.register("code_test", tool_code_test, "Run tests. Args: path, test_type (pytest/unittest), verbose")
    registry.register("git_status", tool_git_status, "Git status. Args: repo_path")
    registry.register("git_commit", tool_git_commit, "Git commit. Args: repo_path, message, add_all (default True)")
    registry.register("git_diff", tool_git_diff, "Git diff. Args: repo_path, file_path (optional), staged")
    registry.register("git_log", tool_git_log, "Git log. Args: repo_path, count (default 10), oneline")
    registry.register("git_branch", tool_git_branch, "Git branches. Args: repo_path, create (optional new branch name)")

__all__ = [
    "register_code_tools",
    "tool_code_run", "tool_code_lint", "tool_code_format", "tool_code_test",
    "tool_git_status", "tool_git_commit", "tool_git_diff", "tool_git_log", "tool_git_branch",
]
