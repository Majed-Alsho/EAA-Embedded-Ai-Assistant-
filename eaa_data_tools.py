"""
EAA Data Tools - Phase 8
JSON parsing, CSV read/write, database queries, API calls, hashing.
All tools use the existing ToolResult pattern from eaa_agent_tools.py.
"""

import os
import json
import csv
import hashlib
import hmac
import re
import io
import traceback
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


# ─── JSON PARSE ───────────────────────────────────────────────────────────────
def tool_json_parse(data: str, query: str = None, pretty: bool = True) -> ToolResult:
    """
    Parse and query JSON data.
    data: JSON string or file path (if starts with @ or ends with .json)
    query: Dot-notation path to extract, e.g. "users[0].name" or "config.settings.theme"
    """
    try:
        # Check if it's a file path
        if data.startswith("@") or (data.endswith(".json") and os.path.exists(data)):
            file_path = data.lstrip("@") if data.startswith("@") else data
            file_path = os.path.expanduser(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
        else:
            parsed = json.loads(data)

        if query:
            # Simple dot-notation query
            result = parsed
            for part in query.split("."):
                # Handle array index
                match = re.match(r"(\w+)\[(\d+)\]", part)
                if match:
                    key = match.group(1)
                    index = int(match.group(2))
                    result = result[key][index]
                elif part.isdigit():
                    result = result[int(part)]
                else:
                    result = result[part]

            indent = 2 if pretty else None
            return ToolResult(True, json.dumps(result, indent=indent, ensure_ascii=False, default=str))

        indent = 2 if pretty else None
        output = json.dumps(parsed, indent=indent, ensure_ascii=False, default=str)
        if len(output) > 10000:
            output = output[:10000] + "\n...[truncated]"
        return ToolResult(True, output)

    except json.JSONDecodeError as e:
        return ToolResult(False, "", f"Invalid JSON: {e}")
    except (KeyError, IndexError, TypeError) as e:
        return ToolResult(False, "", f"Query path not found: {query} - {e}")
    except Exception as e:
        return ToolResult(False, "", f"JSON parse failed: {str(e)}")


# ─── CSV READ ─────────────────────────────────────────────────────────────────
def tool_csv_read(file_path: str, delimiter: str = ",", has_header: bool = True, max_rows: int = 100) -> ToolResult:
    """Read a CSV file and return as formatted table."""
    try:
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            return ToolResult(False, "", f"CSV not found: {file_path}")

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)

        if not rows:
            return ToolResult(True, "[CSV is empty]")

        # Format as aligned table
        if has_header and rows:
            headers = rows[0]
            data_rows = rows[1:]
        else:
            headers = [f"Col{i}" for i in range(len(rows[0]))] if rows else []
            data_rows = rows

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in data_rows[:max_rows]:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(cell))

        # Build table
        def format_row(cells):
            return " | ".join(str(c).ljust(col_widths[i]) if i < len(col_widths) else str(c) for i, c in enumerate(cells))

        table_parts = []
        table_parts.append(format_row(headers))
        table_parts.append("-+-".join("-" * w for w in col_widths))

        for row in data_rows[:max_rows]:
            table_parts.append(format_row(row[:len(headers)]))

        total_rows = len(data_rows)
        if total_rows > max_rows:
            table_parts.append(f"... ({max_rows} of {total_rows} rows shown)")

        return ToolResult(True, f"CSV: {file_path} ({total_rows} rows, {len(headers)} columns)\n\n" + "\n".join(table_parts))

    except Exception as e:
        return ToolResult(False, "", f"CSV read failed: {str(e)}")


# ─── CSV WRITE ────────────────────────────────────────────────────────────────
def tool_csv_write(file_path: str, headers: str, rows: str, delimiter: str = ",") -> ToolResult:
    """
    Write data to a CSV file.
    headers: JSON array of column names
    rows: JSON array of arrays
    """
    try:
        file_path = os.path.expanduser(file_path)
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else ".", exist_ok=True)

        header_list = json.loads(headers) if isinstance(headers, str) else headers
        row_list = json.loads(rows) if isinstance(rows, str) else rows

        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(header_list)
            writer.writerows(row_list)

        return ToolResult(True, f"CSV written: {file_path} ({len(row_list)} rows, {len(header_list)} cols)")

    except Exception as e:
        return ToolResult(False, "", f"CSV write failed: {str(e)}")


# ─── DATABASE QUERY ───────────────────────────────────────────────────────────
def tool_database_query(db_path: str, query: str, fetch: str = "all") -> ToolResult:
    """
    Execute a SQL query on a SQLite database.
    fetch: 'all', 'one', or 'execute' (for INSERT/UPDATE/DELETE)
    """
    try:
        import sqlite3

        db_path = os.path.expanduser(db_path)

        # Check for dangerous operations
        dangerous = ["DROP DATABASE", "DROP TABLE", "ALTER TABLE"]
        for d in dangerous:
            if d in query.upper():
                return ToolResult(False, "", f"Blocked dangerous operation: {d}")

        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query)

        if query.strip().upper().startswith(("SELECT", "PRAGMA")):
            if fetch == "one":
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    return ToolResult(True, json.dumps(result, indent=2, default=str))
                return ToolResult(True, "[No results]")
            else:
                rows = cursor.fetchall()
                if rows:
                    result = [dict(r) for r in rows[:200]]
                    output = json.dumps(result, indent=2, default=str)
                    if len(rows) > 200:
                        output += f"\n... ({len(rows)} total rows, showing 200)"
                    return ToolResult(True, f"Query returned {len(rows)} rows:\n{output}")
                return ToolResult(True, "[No results]")
        else:
            conn.commit()
            affected = cursor.rowcount
            return ToolResult(True, f"Query executed. Rows affected: {affected}")

    except sqlite3.Error as e:
        return ToolResult(False, "", f"SQLite error: {str(e)}")
    except Exception as e:
        return ToolResult(False, "", f"Database query failed: {str(e)}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─── API CALL ─────────────────────────────────────────────────────────────────
def tool_api_call(
    url: str,
    method: str = "GET",
    headers: str = None,
    body: str = None,
    timeout: int = 30,
    params: str = None
) -> ToolResult:
    """
    Make an HTTP API call.
    headers: JSON string of headers
    body: Request body (JSON string)
    params: JSON string of query parameters
    """
    try:
        import urllib.request
        import urllib.parse

        if params:
            params_dict = json.loads(params) if isinstance(params, str) else params
            query_string = urllib.parse.urlencode(params_dict)
            url = f"{url}?{query_string}"

        req_headers = {"User-Agent": "EAA/1.0", "Content-Type": "application/json"}
        if headers:
            custom = json.loads(headers) if isinstance(headers, str) else headers
            req_headers.update(custom)

        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            resp_headers = dict(resp.headers)

            # Try to pretty-print JSON
            try:
                parsed = json.loads(resp_body)
                resp_body = json.dumps(parsed, indent=2, ensure_ascii=False)
            except Exception:
                if len(resp_body) > 5000:
                    resp_body = resp_body[:5000] + "...[truncated]"

            result = {
                "status": resp.status,
                "url": resp.url,
                "headers": {k: v for k, v in list(resp_headers.items())[:10]},
                "body": resp_body
            }

            return ToolResult(True, json.dumps(result, indent=2, default=str))

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return ToolResult(False, f"HTTP {e.code}: {e.reason}\n{body[:2000]}", f"HTTP Error {e.code}")
    except urllib.error.URLError as e:
        return ToolResult(False, "", f"URL Error: {str(e)}")
    except Exception as e:
        return ToolResult(False, "", f"API call failed: {str(e)}")


# ─── HASH TEXT ────────────────────────────────────────────────────────────────
def tool_hash_text(text: str, algorithm: str = "sha256") -> ToolResult:
    """
    Hash text using various algorithms.
    algorithm: md5, sha1, sha256, sha384, sha512
    """
    try:
        algo_map = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
            "sha384": hashlib.sha384,
            "sha512": hashlib.sha512,
        }

        if algorithm.lower() not in algo_map:
            return ToolResult(False, "", f"Unsupported algorithm: {algorithm}. Use: {', '.join(algo_map.keys())}")

        hash_func = algo_map[algorithm.lower()]
        result = hash_func(text.encode("utf-8")).hexdigest()

        return ToolResult(True, f"{algorithm.upper()}: {result}\nInput length: {len(text)} chars")

    except Exception as e:
        return ToolResult(False, "", f"Hash failed: {str(e)}")


# ─── HASH FILE ────────────────────────────────────────────────────────────────
def tool_hash_file(file_path: str, algorithm: str = "sha256") -> ToolResult:
    """Hash a file."""
    try:
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            return ToolResult(False, "", f"File not found: {file_path}")

        algo_map = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
        }

        hash_func = algo_map.get(algorithm.lower(), hashlib.sha256)

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                hash_func.update(chunk)

        result = hash_func.hexdigest()
        size = os.path.getsize(file_path)

        return ToolResult(True, f"{algorithm.upper()}: {result}\nFile: {file_path}\nSize: {size:,} bytes")

    except Exception as e:
        return ToolResult(False, "", f"File hash failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def register_data_tools(registry) -> None:
    """Register all data tools with the existing ToolRegistry."""
    registry.register("json_parse", tool_json_parse, "Parse/query JSON. Args: data (JSON string or @file.json), query (optional dot path)")
    registry.register("csv_read", tool_csv_read, "Read CSV file. Args: file_path, delimiter, has_header, max_rows")
    registry.register("csv_write", tool_csv_write, "Write CSV file. Args: file_path, headers (JSON array), rows (JSON array)")
    registry.register("database_query", tool_database_query, "Query SQLite DB. Args: db_path, query, fetch (all/one/execute)")
    registry.register("api_call", tool_api_call, "HTTP API call. Args: url, method, headers, body, params")
    registry.register("hash_text", tool_hash_text, "Hash text. Args: text, algorithm (md5/sha1/sha256/sha512)")
    registry.register("hash_file", tool_hash_file, "Hash file. Args: file_path, algorithm")

__all__ = [
    "register_data_tools",
    "tool_json_parse", "tool_csv_read", "tool_csv_write",
    "tool_database_query", "tool_api_call", "tool_hash_text", "tool_hash_file",
]
