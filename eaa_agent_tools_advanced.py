"""
EAA Advanced Tools - Infrastructure, Networking, Research, IoT, Media
=====================================================================
24 new tools for advanced operations across 5 categories.

Categories:
  - infra: Docker management, GitHub integration
  - networking: WHOIS, DNS, ping, traceroute, port scanning
  - research: RSS feeds, HTML extraction, Wayback Machine
  - iot: MQTT publish/subscribe
  - media_advanced: FFmpeg video ops, PDF surgery

Requirements:
  pip install python-whois dnspython feedparser paho-mqtt
  Optional: pip install docker (for Docker tools)
"""

import subprocess
import os
import socket
import time
import json
import re
import struct
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════════
# COMPATIBLE ToolResult (duck-type compatible with eaa_agent_tools_v3.ToolResult)
# ═══════════════════════════════════════════════════════════════════════════════

class ToolResult:
    """Compatible ToolResult for advanced tools"""
    def __init__(self, success: bool, output: str = "", error: str = ""):
        self.success = success
        self.output = output
        self.error = error
        self.metadata = {}

    def __repr__(self):
        return f"ToolResult(success={self.success}, output_len={len(self.output)}, error={self.error})"


# ═══════════════════════════════════════════════════════════════════════════════
# OPTIONAL DEPENDENCY CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import lxml.html
    from lxml.cssselect import CSSSelector
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import dns.resolver
    import dns.reversename
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False

try:
    import whois
    HAS_WHOIS = True
except ImportError:
    HAS_WHOIS = False

try:
    import paho.mqtt.client as mqtt_lib
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

try:
    import docker as docker_lib
    HAS_DOCKER = True
except ImportError:
    HAS_DOCKER = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


# ═══════════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE & DEVOPS TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def tool_docker_list(action: str = "containers", all_items: bool = False) -> ToolResult:
    """List Docker containers or images"""
    if not HAS_DOCKER:
        return ToolResult(False, "", "Docker Python SDK not installed. Run: pip install docker")
    try:
        client = docker_lib.from_env()
        if action == "containers":
            items = client.containers.list(all=all_items)
            lines = [f"{'STATUS':<20} {'IMAGE':<30} {'CONTAINER ID':<15} {'NAMES'}"]
            lines.append("-" * 80)
            for c in items:
                status = c.status
                image = c.image.tags[0] if c.image.tags else c.image.id[:12]
                lines.append(f"{status:<20} {image:<30} {c.id[:12]:<15} {', '.join(c.names)}")
            return ToolResult(True, "\n".join(lines))
        elif action == "images":
            items = client.images.list(all=all_items)
            lines = [f"{'REPOSITORY':<40} {'TAG':<15} {'SIZE':<10} {'IMAGE ID'}"]
            lines.append("-" * 80)
            for img in items:
                tags = img.tags[0].split(":") if img.tags else ["<none>", "<none>"]
                repo, tag = tags[0], tags[1] if len(tags) > 1 else "latest"
                size = f"{img.attrs['Size'] / 1024 / 1024:.1f}MB"
                lines.append(f"{repo:<40} {tag:<15} {size:<10} {img.id[:12]}")
            return ToolResult(True, "\n".join(lines))
        else:
            return ToolResult(False, "", f"Unknown action '{action}'. Use 'containers' or 'images'")
    except Exception as e:
        return ToolResult(False, "", f"Docker error: {e}")


def tool_docker_build(path: str = ".", tag: str = "eaa-build:latest", dockerfile: str = "Dockerfile") -> ToolResult:
    """Build a Docker image from a Dockerfile"""
    if not HAS_DOCKER:
        return ToolResult(False, "", "Docker Python SDK not installed. Run: pip install docker")
    try:
        client = docker_lib.from_env()
        image, build_logs = client.images.build(path=path, tag=tag, dockerfile=dockerfile, rm=True)
        lines = [f"Built image: {tag}", f"Image ID: {image.id[:12]}"]
        for log in build_logs:
            if "stream" in log:
                lines.append(log["stream"].strip())
        return ToolResult(True, "\n".join(lines))
    except Exception as e:
        return ToolResult(False, "", f"Docker build error: {e}")


def tool_docker_start(container_id: str) -> ToolResult:
    """Start a Docker container"""
    if not HAS_DOCKER:
        return ToolResult(False, "", "Docker Python SDK not installed. Run: pip install docker")
    try:
        client = docker_lib.from_env()
        container = client.containers.get(container_id)
        container.start()
        container.reload()
        return ToolResult(True, f"Container {container_id} started. Status: {container.status}")
    except docker_lib.errors.NotFound:
        return ToolResult(False, "", f"Container '{container_id}' not found. Run docker_list to see available containers.")
    except Exception as e:
        return ToolResult(False, "", f"Docker start error: {e}")


def tool_docker_stop(container_id: str) -> ToolResult:
    """Stop a Docker container"""
    if not HAS_DOCKER:
        return ToolResult(False, "", "Docker Python SDK not installed. Run: pip install docker")
    try:
        client = docker_lib.from_env()
        container = client.containers.get(container_id)
        container.stop(timeout=10)
        container.reload()
        return ToolResult(True, f"Container {container_id} stopped. Status: {container.status}")
    except docker_lib.errors.NotFound:
        return ToolResult(False, "", f"Container '{container_id}' not found.")
    except Exception as e:
        return ToolResult(False, "", f"Docker stop error: {e}")


def tool_docker_logs(container_id: str, tail: int = 100) -> ToolResult:
    """Get logs from a Docker container"""
    if not HAS_DOCKER:
        return ToolResult(False, "", "Docker Python SDK not installed. Run: pip install docker")
    try:
        client = docker_lib.from_env()
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail).decode("utf-8", errors="replace")
        if len(logs) > 8000:
            logs = logs[:8000] + "\n\n... [truncated, showing last 100 lines]"
        return ToolResult(True, logs if logs else "(no logs)")
    except docker_lib.errors.NotFound:
        return ToolResult(False, "", f"Container '{container_id}' not found.")
    except Exception as e:
        return ToolResult(False, "", f"Docker logs error: {e}")


def tool_github_issue(action: str = "list", repo: str = "", issue_number: int = 0,
                      title: str = "", body: str = "", state: str = "open",
                      labels: str = "", token: str = "") -> ToolResult:
    """Interact with GitHub issues - list, create, get, or update"""
    import urllib.request
    import urllib.parse
    import base64

    if not repo:
        return ToolResult(False, "", "Repository required. Format: 'owner/repo' (e.g. 'python/cpython')")

    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "EAA-Agent"}
    if token:
        headers["Authorization"] = f"token {token}"

    base_url = f"https://api.github.com/repos/{repo}/issues"

    try:
        if action == "list":
            url = f"{base_url}?state={state}&per_page=20"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            if not data:
                return ToolResult(True, f"No {state} issues found in {repo}")
            lines = [f"Issues for {repo} (state={state}):\n"]
            for issue in data:
                labels_str = ", ".join(l["name"] for l in issue.get("labels", []))
                lines.append(f"  #{issue['number']} [{issue['state']}] {issue['title']}")
                if labels_str:
                    lines.append(f"    Labels: {labels_str}")
                lines.append(f"    Created: {issue['created_at']} | URL: {issue['html_url']}")
                lines.append("")
            return ToolResult(True, "\n".join(lines))

        elif action == "get":
            if not issue_number:
                return ToolResult(False, "", "issue_number required for 'get' action")
            url = f"{base_url}/{issue_number}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                issue = json.loads(resp.read())
            lines = [
                f"#{issue['number']} {issue['title']}",
                f"State: {issue['state']}",
                f"Author: {issue['user']['login']}",
                f"Created: {issue['created_at']}",
                f"Updated: {issue['updated_at']}",
                f"URL: {issue['html_url']}",
                f"\nBody:\n{issue['body'] or '(no body)'}"
            ]
            return ToolResult(True, "\n".join(lines))

        elif action == "create":
            if not title:
                return ToolResult(False, "", "title required for 'create' action")
            payload = {"title": title, "body": body, "state": state}
            if labels:
                payload["labels"] = [l.strip() for l in labels.split(",")]
            req = urllib.request.Request(base_url, data=json.dumps(payload).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                issue = json.loads(resp.read())
            return ToolResult(True, f"Created issue #{issue['number']}: {issue['title']}\nURL: {issue['html_url']}")

        elif action == "update":
            if not issue_number:
                return ToolResult(False, "", "issue_number required for 'update' action")
            payload = {}
            if title:
                payload["title"] = title
            if body:
                payload["body"] = body
            if state:
                payload["state"] = state
            if not payload:
                return ToolResult(False, "", "Nothing to update. Provide title, body, or state.")
            url = f"{base_url}/{issue_number}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="PATCH")
            with urllib.request.urlopen(req, timeout=15) as resp:
                issue = json.loads(resp.read())
            return ToolResult(True, f"Updated issue #{issue['number']}: {issue['title']}")

        else:
            return ToolResult(False, "", f"Unknown action '{action}'. Use: list, get, create, update")

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return ToolResult(False, "", f"GitHub API error {e.code}: {err_body}")
    except Exception as e:
        return ToolResult(False, "", f"GitHub error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORKING & OSINT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def tool_whois_lookup(domain: str) -> ToolResult:
    """WHOIS domain lookup - get registration and ownership info"""
    if not HAS_WHOIS:
        return ToolResult(False, "", "python-whois not installed. Run: pip install python-whois")
    try:
        domain = domain.strip().lower()
        if not domain.endswith((".com", ".net", ".org", ".io", ".dev", ".info", ".biz", ".me", ".co", ".xyz")):
            pass  # Try anyway, WHOIS works on most TLDs
        w = whois.whois(domain)
        result = {}
        for key, val in w.items():
            if val and str(val).strip() and str(val) != "None":
                if isinstance(val, list):
                    val = val[0] if len(val) == 1 else ", ".join(str(v) for v in val if v)
                result[key] = str(val)
        if not result:
            return ToolResult(False, "", f"No WHOIS data found for '{domain}'")
        lines = [f"WHOIS: {domain}", "=" * 50]
        for key, val in result.items():
            lines.append(f"  {key}: {val}")
        return ToolResult(True, "\n".join(lines))
    except Exception as e:
        return ToolResult(False, "", f"WHOIS lookup error: {e}")


def tool_dns_resolve(domain: str, record_type: str = "A", server: str = "") -> ToolResult:
    """DNS resolution - query DNS records for a domain"""
    if not HAS_DNSPYTHON:
        # Fallback to socket-based resolution
        try:
            domain = domain.strip()
            if record_type.upper() in ("A", "AAAA", "MX"):
                if record_type.upper() == "MX":
                    answers = socket.getaddrinfo(domain, None, socket.AF_INET)
                    ips = list(set(a[4][0] for a in answers))
                    return ToolResult(True, f"DNS {record_type} for {domain}:\n" + "\n".join(f"  {ip}" for ip in ips[:20]))
                else:
                    ip = socket.gethostbyname(domain)
                    return ToolResult(True, f"DNS {record_type} for {domain}: {ip}")
            else:
                return ToolResult(False, "", f"dnspython needed for {record_type} records. Run: pip install dnspython")
        except socket.gaierror as e:
            return ToolResult(False, "", f"DNS resolution failed: {e}")

    try:
        domain = domain.strip()
        record_type = record_type.upper()
        resolver = dns.resolver.Resolver()
        if server:
            resolver.nameservers = [server]
        answers = resolver.resolve(domain, record_type)
        lines = [f"DNS {record_type} records for {domain}:"]
        for rdata in answers:
            lines.append(f"  {rdata}")
            # Try to get additional info for common types
            if hasattr(rdata, 'exchange'):
                lines[-1] += f" (priority: {rdata.preference})"
            if hasattr(rdata, 'target'):
                lines[-1] += f" -> {rdata.target}"
        return ToolResult(True, "\n".join(lines))
    except dns.resolver.NXDOMAIN:
        return ToolResult(False, "", f"Domain '{domain}' does not exist (NXDOMAIN)")
    except dns.resolver.NoAnswer:
        return ToolResult(False, "", f"No {record_type} records found for '{domain}'")
    except dns.resolver.NoNameservers:
        return ToolResult(False, "", f"No nameservers available for '{domain}'")
    except Exception as e:
        return ToolResult(False, "", f"DNS error: {e}")


def tool_subdomain_enum(domain: str, wordlist_source: str = "common") -> ToolResult:
    """Enumerate subdomains for a domain using common prefix lists"""
    COMMON_SUBDOMAINS = [
        "www", "mail", "ftp", "localhost", "webmail", "smtp", "pop", "ns1", "ns2",
        "dns", "dns1", "dns2", "mx", "mx1", "mx2", "api", "dev", "staging",
        "test", "admin", "portal", "vpn", "remote", "blog", "forum", "shop",
        "store", "app", "cdn", "static", "media", "img", "images", "assets",
        "docs", "doc", "wiki", "help", "support", "status", "monitor", "grafana",
        "git", "github", "gitlab", "ci", "jenkins", "build", "deploy", "db",
        "database", "mysql", "postgres", "redis", "elastic", "search", "auth",
        "sso", "login", "oauth", "openid", "id", "identity", "accounts",
        "billing", "pay", "payment", "checkout", "cart", "order", "tracking",
        "analytics", "metric", "log", "logs", "splunk", "kibana", "dashboard",
        "internal", "intranet", "private", "secure", "ssh", "telnet", "backup",
        "proxy", "edge", "relay", "gw", "gateway", "firewall", "utm",
        "cloud", "aws", "azure", "gcp", "heroku", "vercel", "netlify",
        "web", "web1", "web2", "srv", "server", "node", "master", "slave",
    ]

    if wordlist_source == "common":
        subdomains = COMMON_SUBDOMAINS
    else:
        return ToolResult(False, "", f"Unknown wordlist source '{wordlist_source}'. Use 'common'")

    found = []
    total = len(subdomains)
    for i, sub in enumerate(subdomains):
        full_domain = f"{sub}.{domain.strip()}"
        try:
            socket.setdefaulttimeout(1.5)
            ip = socket.gethostbyname(full_domain)
            found.append((full_domain, ip))
        except socket.gaierror:
            pass
        except Exception:
            pass

    if found:
        lines = [f"Found {len(found)} subdomains for {domain} (checked {total} prefixes):\n"]
        lines.append(f"{'SUBDOMAIN':<40} {'IP ADDRESS'}")
        lines.append("-" * 60)
        for sub, ip in sorted(found):
            lines.append(f"{sub:<40} {ip}")
        return ToolResult(True, "\n".join(lines))
    else:
        return ToolResult(True, f"No subdomains found for {domain} (checked {total} common prefixes)")


def tool_ping_host(host: str, count: int = 4) -> ToolResult:
    """Ping a host to check connectivity and measure latency"""
    try:
        count = max(1, min(count, 20))
        # Windows uses -n, Linux/Mac use -c
        if os.name == "nt":
            cmd = ["ping", "-n", str(count), "-w", "3000", host]
        else:
            cmd = ["ping", "-c", str(count), "-W", "3", host]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=count * 5 + 5)
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if result.returncode == 0:
            # Extract stats from output
            if "packet loss" in output.lower() or "loss" in output.lower():
                return ToolResult(True, output.strip())
            return ToolResult(True, output.strip())
        else:
            return ToolResult(False, "", f"Ping failed (code {result.returncode}): {output.strip()[:500]}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"Ping timed out after {count * 5}s")
    except FileNotFoundError:
        return ToolResult(False, "", "ping command not found")
    except Exception as e:
        return ToolResult(False, "", f"Ping error: {e}")


def tool_traceroute(host: str, max_hops: int = 20, timeout_ms: int = 2000) -> ToolResult:
    """Traceroute to a host - trace the network path"""
    try:
        max_hops = max(1, min(max_hops, 50))
        if os.name == "nt":
            cmd = ["tracert", "-h", str(max_hops), "-w", str(timeout_ms), host]
        else:
            cmd = ["traceroute", "-m", str(max_hops), "-w", str(timeout_ms / 1000), host]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * 3 + 10)
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if result.returncode == 0 or "* * *" in output:
            return ToolResult(True, output.strip())
        else:
            return ToolResult(False, "", f"Traceroute failed: {output.strip()[:500]}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", f"Traceroute timed out")
    except FileNotFoundError:
        return ToolResult(False, "", "tracert/traceroute command not found")
    except Exception as e:
        return ToolResult(False, "", f"Traceroute error: {e}")


def tool_port_scan(host: str, ports: str = "1-1024", timeout: float = 1.0) -> ToolResult:
    """Scan ports on a host to find open services"""
    try:
        # Parse port range
        port_list = []
        for part in ports.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                port_list.extend(range(int(start.strip()), int(end.strip()) + 1))
            else:
                port_list.append(int(part))

        port_list = list(set(port_list))  # deduplicate
        total = len(port_list)

        if total > 5000:
            return ToolResult(False, "", f"Too many ports ({total}). Maximum 5000 per scan.")

        open_ports = []
        for port in port_list:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                if result == 0:
                    try:
                        service = socket.getservbyport(port)
                    except OSError:
                        service = "unknown"
                    open_ports.append((port, service))
                sock.close()
            except Exception:
                pass

        if open_ports:
            lines = [f"Port scan of {host} ({total} ports scanned, {len(open_ports)} open):\n"]
            lines.append(f"{'PORT':<10} {'SERVICE':<15} {'STATUS'}")
            lines.append("-" * 40)
            for port, service in sorted(open_ports):
                lines.append(f"{port:<10} {service:<15} OPEN")
            return ToolResult(True, "\n".join(lines))
        else:
            return ToolResult(True, f"Port scan of {host}: No open ports found (scanned {total} ports)")
    except Exception as e:
        return ToolResult(False, "", f"Port scan error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED RESEARCH & PARSING TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def tool_rss_read(url: str, max_items: int = 10) -> ToolResult:
    """Read and parse RSS/Atom feeds - get latest articles from blogs, news, CVEs"""
    if not HAS_FEEDPARSER:
        return ToolResult(False, "", "feedparser not installed. Run: pip install feedparser")
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return ToolResult(False, "", f"Failed to parse feed: {feed.bozo_exception}")

        feed_title = feed.feed.get("title", "Unknown Feed")
        feed_desc = feed.feed.get("description", "")
        feed_link = feed.feed.get("link", "")
        total = len(feed.entries)

        lines = [f"Feed: {feed_title}"]
        if feed_link:
            lines.append(f"URL: {feed_link}")
        if feed_desc:
            lines.append(f"Description: {feed_desc}")
        lines.append(f"Total entries: {total} (showing latest {min(max_items, total)})\n")

        for i, entry in enumerate(feed.entries[:max_items]):
            title = entry.get("title", "(no title)")
            link = entry.get("link", "(no link)")
            published = entry.get("published", entry.get("updated", "(no date)"))
            author = entry.get("author", "")
            summary = entry.get("summary", "")[:200]

            lines.append(f"[{i+1}] {title}")
            lines.append(f"    Published: {published}")
            if author:
                lines.append(f"    Author: {author}")
            lines.append(f"    Link: {link}")
            if summary:
                # Strip HTML tags
                clean = re.sub(r"<[^>]+>", "", summary)
                lines.append(f"    Summary: {clean}")
            lines.append("")

        return ToolResult(True, "\n".join(lines))
    except Exception as e:
        return ToolResult(False, "", f"RSS read error: {e}")


def tool_html_extract(url_or_html: str, selector_type: str = "css", selector: str = "body",
                      attribute: str = "text", source: str = "url") -> ToolResult:
    """Extract data from HTML using CSS selectors or XPath expressions"""
    if not HAS_LXML:
        return ToolResult(False, "", "lxml not installed. Run: pip install lxml")

    try:
        if source == "url":
            import urllib.request
            req = urllib.request.Request(url_or_html, headers={"User-Agent": "EAA-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        else:
            html = url_or_html

        tree = lxml.html.fromstring(html)
        results = []

        if selector_type == "css":
            elements = tree.cssselect(selector)
        elif selector_type == "xpath":
            elements = tree.xpath(selector)
        else:
            return ToolResult(False, "", f"Unknown selector_type '{selector_type}'. Use 'css' or 'xpath'")

        for el in elements:
            if attribute == "text":
                text = el.text_content().strip()
                if text:
                    results.append(text)
            elif attribute == "href":
                href = el.get("href", "")
                if href:
                    results.append(href)
            elif attribute == "src":
                src = el.get("src", "")
                if src:
                    results.append(src)
            elif attribute == "html":
                results.append(lxml.html.tostring(el, encoding="unicode"))
            elif attribute.startswith("attr:"):
                attr_name = attribute[5:]
                val = el.get(attr_name, "")
                if val:
                    results.append(val)
            else:
                results.append(el.get(attribute, ""))

        if results:
            output = f"Found {len(results)} matches for {selector_type}='{selector}', attribute='{attribute}':\n\n"
            output += "\n".join(results[:100])
            if len(results) > 100:
                output += f"\n\n... ({len(results) - 100} more results truncated)"
            return ToolResult(True, output)
        else:
            return ToolResult(True, f"No matches found for {selector_type}='{selector}', attribute='{attribute}'")
    except urllib.error.URLError as e:
        return ToolResult(False, "", f"Failed to fetch URL: {e}")
    except Exception as e:
        return ToolResult(False, "", f"HTML extract error: {e}")


def tool_wayback_fetch(url: str, timestamp: str = "") -> ToolResult:
    """Fetch historical snapshots from the Wayback Machine API"""
    import urllib.request
    import urllib.parse

    try:
        encoded_url = urllib.parse.quote(url)
        if timestamp:
            api_url = f"http://archive.org/wayback/available?url={encoded_url}&timestamp={timestamp}"
        else:
            api_url = f"http://archive.org/wayback/available?url={encoded_url}"

        req = urllib.request.Request(api_url, headers={"User-Agent": "EAA-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        if "archived_snapshots" in data and data["archived_snapshots"].get("closest"):
            snap = data["archived_snapshots"]["closest"]
            snap_url = snap["url"]
            snap_ts = snap["timestamp"]
            snap_avail = snap["available"]
            snap_status = snap.get("status", "")

            # Try to fetch the actual archived content
            content_lines = [f"Wayback Machine snapshot found!"]
            content_lines.append(f"  Original URL: {url}")
            content_lines.append(f"  Snapshot URL: {snap_url}")
            content_lines.append(f"  Archived: {snap_ts} (available={snap_avail}, status={snap_status})")

            if snap_avail:
                try:
                    req2 = urllib.request.Request(snap_url, headers={"User-Agent": "EAA-Agent/1.0"})
                    with urllib.request.urlopen(req2, timeout=15) as resp2:
                        content = resp2.read().decode("utf-8", errors="replace")
                    # Strip HTML for readability
                    clean = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
                    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
                    clean = re.sub(r"<[^>]+>", " ", clean)
                    clean = re.sub(r"\s+", " ", clean).strip()
                    if len(clean) > 5000:
                        clean = clean[:5000] + "\n\n... [truncated]"
                    content_lines.append(f"\nContent preview:\n{clean}")
                except Exception as e:
                    content_lines.append(f"\nCould not fetch snapshot content: {e}")

            return ToolResult(True, "\n".join(content_lines))
        else:
            return ToolResult(False, "", f"No Wayback Machine snapshot found for: {url}")
    except Exception as e:
        return ToolResult(False, "", f"Wayback Machine error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM & IoT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def tool_hardware_stats(component: str = "all") -> ToolResult:
    """Get real-time hardware statistics - CPU, GPU, RAM, disk, temps"""
    if not HAS_PSUTIL:
        return ToolResult(False, "", "psutil not installed. Run: pip install psutil")
    try:
        lines = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Hardware Stats @ {now}")
        lines.append("=" * 55)

        if component in ("all", "cpu"):
            cpu_percent = psutil.cpu_percent(interval=1, percpu=False)
            cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
            cpu_count_logical = psutil.cpu_count(logical=True)
            cpu_count_phys = psutil.cpu_count(logical=False)
            cpu_freq = psutil.cpu_freq()
            lines.append(f"\nCPU:")
            lines.append(f"  Usage: {cpu_percent}%")
            lines.append(f"  Cores: {cpu_count_phys} physical / {cpu_count_logical} logical")
            if cpu_freq:
                lines.append(f"  Frequency: {cpu_freq.current:.0f} MHz (min: {cpu_freq.min:.0f}, max: {cpu_freq.max:.0f})")
            lines.append(f"  Per-core: {[f'{c}%' for c in cpu_per_core]}")

        if component in ("all", "memory", "ram"):
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            lines.append(f"\nMemory (RAM):")
            lines.append(f"  Total: {mem.total / (1024**3):.1f} GB")
            lines.append(f"  Used: {mem.used / (1024**3):.1f} GB ({mem.percent}%)")
            lines.append(f"  Available: {mem.available / (1024**3):.1f} GB")
            lines.append(f"  Swap: {swap.used / (1024**3):.1f} GB / {swap.total / (1024**3):.1f} GB ({swap.percent}%)")

        if component in ("all", "gpu"):
            # Try to get GPU info (Windows: wmic, Linux: nvidia-smi)
            lines.append(f"\nGPU:")
            try:
                if os.name == "nt":
                    result = subprocess.run(
                        ["wmic", "path", "win32_videocontroller", "get", "name,adapterram,driverversion,status",
                         "/format:list"],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        gpu_info = result.stdout.strip()
                        # Parse wmic output
                        for line in gpu_info.split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            if "=" in line:
                                key, val = line.split("=", 1)
                                key = key.strip()
                                val = val.strip()
                                if key == "AdapterRAM" and val and val != "NULL":
                                    try:
                                        val = f"{int(val) / (1024**3):.1f} GB"
                                    except ValueError:
                                        pass
                                lines.append(f"  {key}: {val}")
                    else:
                        lines.append("  (wmic not available)")
                else:
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n"):
                            parts = [p.strip() for p in line.split(",")]
                            if len(parts) >= 5:
                                lines.append(f"  {parts[0]}")
                                lines.append(f"    Memory: {parts[2]} MB / {parts[1]} MB (free: {parts[3]} MB)")
                                lines.append(f"    Temperature: {parts[4]} C")
                    else:
                        lines.append("  (nvidia-smi not available)")
            except Exception as e:
                lines.append(f"  (GPU info unavailable: {e})")

        if component in ("all", "disk"):
            lines.append(f"\nDisk:")
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    lines.append(f"  {part.device} ({part.mountpoint}):")
                    lines.append(f"    Total: {usage.total / (1024**3):.1f} GB")
                    lines.append(f"    Used: {usage.used / (1024**3):.1f} GB ({usage.percent}%)")
                    lines.append(f"    Free: {usage.free / (1024**3):.1f} GB")
                    lines.append(f"    Type: {part.fstype}")
                except PermissionError:
                    lines.append(f"  {part.device}: (access denied)")
                except Exception:
                    pass

        if component in ("all", "network"):
            lines.append(f"\nNetwork:")
            try:
                addrs = psutil.net_if_addrs()
                for iface, addr_list in addrs.items():
                    for addr in addr_list:
                        if addr.family == socket.AF_INET:
                            lines.append(f"  {iface}: {addr.address} (netmask: {addr.netmask or 'N/A'})")
                io = psutil.net_io_counters()
                lines.append(f"  Bytes sent: {io.bytes_sent / (1024**2):.1f} MB")
                lines.append(f"  Bytes received: {io.bytes_recv / (1024**2):.1f} MB")
            except Exception as e:
                lines.append(f"  (Network info unavailable: {e})")

        if component in ("all", "process"):
            lines.append(f"\nTop processes by memory:")
            procs = sorted(psutil.process_iter(['pid', 'name', 'memory_percent', 'cpu_percent']),
                           key=lambda p: p.info.get('memory_percent', 0) or 0, reverse=True)
            for p in procs[:10]:
                lines.append(f"  PID {p.info['pid']:<8} {p.info['name'][:30]:<30} "
                             f"MEM: {p.info.get('memory_percent', 0):.1f}% "
                             f"CPU: {p.info.get('cpu_percent', 0):.1f}%")

        return ToolResult(True, "\n".join(lines))
    except Exception as e:
        return ToolResult(False, "", f"Hardware stats error: {e}")


def tool_mqtt_publish(host: str = "localhost", port: int = 1883, topic: str = "",
                      message: str = "", username: str = "", password: str = "",
                      qos: int = 0, retain: bool = False) -> ToolResult:
    """Publish a message to an MQTT broker/topic"""
    if not HAS_MQTT:
        return ToolResult(False, "", "paho-mqtt not installed. Run: pip install paho-mqtt")
    if not topic:
        return ToolResult(False, "", "topic is required")
    if not message:
        return ToolResult(False, "", "message is required")

    result_data = {"published": False}

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.publish(topic, message, qos=qos, retain=retain)
        else:
            result_data["error"] = f"Connection failed with code {rc}"

    def on_publish(client, userdata, mid, properties=None):
        result_data["published"] = True
        result_data["mid"] = mid
        client.disconnect()

    try:
        client = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2)
        if username and password:
            client.username_pw_set(username, password)
        client.on_connect = on_connect
        client.on_publish = on_publish
        client.connect(host, port, keepalive=10)
        client.loop_start()
        # Wait for publish (max 5s)
        for _ in range(50):
            time.sleep(0.1)
            if result_data.get("published") or result_data.get("error"):
                break
        client.loop_stop()
        client.disconnect()

        if result_data.get("published"):
            return ToolResult(True, f"Published to '{topic}' on {host}:{port}\nMessage: {message}\nQoS: {qos}, Retain: {retain}")
        elif result_data.get("error"):
            return ToolResult(False, "", result_data["error"])
        else:
            return ToolResult(False, "", "Publish timed out (5s)")
    except Exception as e:
        return ToolResult(False, "", f"MQTT publish error: {e}")


def tool_mqtt_subscribe(host: str = "localhost", port: int = 1883, topic: str = "",
                        timeout_secs: int = 10, username: str = "", password: str = "",
                        qos: int = 0) -> ToolResult:
    """Subscribe to an MQTT topic and capture messages for a duration"""
    if not HAS_MQTT:
        return ToolResult(False, "", "paho-mqtt not installed. Run: pip install paho-mqtt")
    if not topic:
        return ToolResult(False, "", "topic is required")

    messages = []

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe(topic, qos=qos)
        else:
            messages.append(f"[ERROR] Connection failed with code {rc}")

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            payload = msg.payload.hex()
        messages.append(f"[{datetime.now().strftime('%H:%M:%S.%f')}] {msg.topic}: {payload}")

    def on_subscribe(client, userdata, mid, granted_qos, properties=None):
        messages.append(f"[SUBSCRIBED] to '{topic}' (QoS: {granted_qos})")

    try:
        client = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2)
        if username and password:
            client.username_pw_set(username, password)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_subscribe = on_subscribe
        client.connect(host, port, keepalive=10)
        client.loop_start()
        time.sleep(timeout_secs)
        client.loop_stop()
        client.disconnect()

        if messages:
            return ToolResult(True, f"MQTT subscribe to '{topic}' on {host}:{port} ({timeout_secs}s):\n\n" + "\n".join(messages))
        else:
            return ToolResult(True, f"No messages received on '{topic}' in {timeout_secs}s")
    except Exception as e:
        return ToolResult(False, "", f"MQTT subscribe error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MEDIA MANIPULATION TOOLS (FFmpeg)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_ffmpeg() -> Optional[str]:
    """Check if ffmpeg is available, return path or None"""
    for cmd in ["ffmpeg", "ffmpeg.exe"]:
        try:
            result = subprocess.run([cmd, "-version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def tool_video_trim(input_path: str, output_path: str = "", start_time: str = "0:00",
                    duration: str = "10") -> ToolResult:
    """Trim a video file using FFmpeg - extract a clip by start time and duration"""
    ffmpeg = _check_ffmpeg()
    if not ffmpeg:
        return ToolResult(False, "", "FFmpeg not found. Install FFmpeg and add to PATH.")
    if not input_path or not os.path.exists(input_path):
        return ToolResult(False, "", f"Input file not found: {input_path}")

    if not output_path:
        base, _ = os.path.splitext(input_path)
        output_path = f"{base}_trimmed{_}"

    try:
        cmd = [
            ffmpeg, "-y", "-ss", start_time, "-i", input_path,
            "-t", duration, "-c", "copy",
            "-avoid_negative_ts", "make_zero", output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return ToolResult(True, f"Video trimmed successfully!\nOutput: {output_path}\nSize: {size_mb:.1f} MB\nStart: {start_time}, Duration: {duration}")
        else:
            err = result.stderr[-1000:] if result.stderr else "Unknown error"
            return ToolResult(False, "", f"FFmpeg trim failed: {err}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", "FFmpeg trim timed out (5 min)")
    except Exception as e:
        return ToolResult(False, "", f"Video trim error: {e}")


def tool_video_extract_audio(input_path: str, output_path: str = "",
                              audio_format: str = "mp3", bitrate: str = "192k") -> ToolResult:
    """Extract audio track from a video file using FFmpeg"""
    ffmpeg = _check_ffmpeg()
    if not ffmpeg:
        return ToolResult(False, "", "FFmpeg not found. Install FFmpeg and add to PATH.")
    if not input_path or not os.path.exists(input_path):
        return ToolResult(False, "", f"Input file not found: {input_path}")

    if not output_path:
        base, _ = os.path.splitext(input_path)
        output_path = f"{base}_audio.{audio_format}"

    try:
        cmd = [
            ffmpeg, "-y", "-i", input_path,
            "-vn",  # no video
            "-acodec", "libmp3lame" if audio_format == "mp3" else "copy",
            "-b:a", bitrate,
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return ToolResult(True, f"Audio extracted successfully!\nOutput: {output_path}\nFormat: {audio_format}, Bitrate: {bitrate}\nSize: {size_mb:.1f} MB")
        else:
            err = result.stderr[-1000:] if result.stderr else "Unknown error"
            return ToolResult(False, "", f"FFmpeg extract failed: {err}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", "FFmpeg extract timed out (5 min)")
    except Exception as e:
        return ToolResult(False, "", f"Audio extract error: {e}")


def tool_video_compress(input_path: str, output_path: str = "", crf: int = 23,
                        scale: str = "") -> ToolResult:
    """Compress/reduce video file size using FFmpeg with configurable quality"""
    ffmpeg = _check_ffmpeg()
    if not ffmpeg:
        return ToolResult(False, "", "FFmpeg not found. Install FFmpeg and add to PATH.")
    if not input_path or not os.path.exists(input_path):
        return ToolResult(False, "", f"Input file not found: {input_path}")

    crf = max(0, min(51, crf))  # Clamp 0-51

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_compressed{ext}"

    try:
        # Get original file size
        orig_size = os.path.getsize(input_path) / (1024 * 1024)

        cmd = [ffmpeg, "-y", "-i", input_path, "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-c:a", "aac", "-b:a", "128k"]
        if scale:
            cmd.extend(["-vf", f"scale={scale}"])
        cmd.append(output_path)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and os.path.exists(output_path):
            new_size = os.path.getsize(output_path) / (1024 * 1024)
            reduction = (1 - new_size / orig_size) * 100 if orig_size > 0 else 0
            return ToolResult(True, (
                f"Video compressed successfully!\n"
                f"Output: {output_path}\n"
                f"Original: {orig_size:.1f} MB -> Compressed: {new_size:.1f} MB\n"
                f"Reduction: {reduction:.1f}%\n"
                f"CRF: {crf}, Scale: {scale or 'original'}"
            ))
        else:
            err = result.stderr[-1000:] if result.stderr else "Unknown error"
            return ToolResult(False, "", f"FFmpeg compress failed: {err}")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "", "FFmpeg compress timed out (10 min)")
    except Exception as e:
        return ToolResult(False, "", f"Video compress error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PDF SURGERY TOOLS (Split, Merge, Watermark)
# ═══════════════════════════════════════════════════════════════════════════════

def tool_pdf_split(input_path: str, output_dir: str = "", page_ranges: str = "") -> ToolResult:
    """Split a PDF into separate files - by page ranges or individual pages"""
    if not HAS_PYMUPDF:
        return ToolResult(False, "", "PyMuPDF not installed. Run: pip install PyMuPDF")
    if not input_path or not os.path.exists(input_path):
        return ToolResult(False, "", f"Input file not found: {input_path}")

    if not output_dir:
        output_dir = os.path.dirname(input_path) or "."

    try:
        doc = fitz.open(input_path)
        total_pages = len(doc)
        output_files = []

        if page_ranges:
            # Parse page ranges like "1-3,5,7-10"
            ranges = []
            for part in page_ranges.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    ranges.append((int(start) - 1, int(end) - 1))
                else:
                    page = int(part) - 1
                    ranges.append((page, page))
        else:
            # Split every page
            ranges = [(i, i) for i in range(total_pages)]

        for idx, (start, end) in enumerate(ranges):
            if start < 0:
                start = 0
            if end >= total_pages:
                end = total_pages - 1
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start, to_page=end)
            out_file = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(input_path))[0]}_pages_{start+1}-{end+1}.pdf")
            new_doc.save(out_file)
            new_doc.close()
            output_files.append(out_file)

        doc.close()
        lines = [f"Split '{input_path}' into {len(output_files)} file(s) (total {total_pages} pages):"]
        for f in output_files:
            size_kb = os.path.getsize(f) / 1024
            lines.append(f"  {f} ({size_kb:.0f} KB)")
        return ToolResult(True, "\n".join(lines))
    except Exception as e:
        return ToolResult(False, "", f"PDF split error: {e}")


def tool_pdf_merge(input_paths: str, output_path: str = "") -> ToolResult:
    """Merge multiple PDF files into one"""
    if not HAS_PYMUPDF:
        return ToolResult(False, "", "PyMuPDF not installed. Run: pip install PyMuPDF")

    paths = [p.strip() for p in input_paths.split(",")]
    if len(paths) < 2:
        return ToolResult(False, "", "Need at least 2 PDF files to merge. Separate paths with commas.")

    for p in paths:
        if not os.path.exists(p):
            return ToolResult(False, "", f"File not found: {p}")

    if not output_path:
        output_dir = os.path.dirname(paths[0]) or "."
        output_path = os.path.join(output_dir, "merged_output.pdf")

    try:
        merged = fitz.open()
        total_pages = 0
        for p in paths:
            doc = fitz.open(p)
            merged.insert_pdf(doc)
            total_pages += len(doc)
            doc.close()

        merged.save(output_path)
        merged.close()
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return ToolResult(True, (
            f"Merged {len(paths)} PDFs into '{output_path}'\n"
            f"Total pages: {total_pages}\n"
            f"Output size: {size_mb:.2f} MB\n"
            f"Files merged:\n" + "\n".join(f"  - {p}" for p in paths)
        ))
    except Exception as e:
        return ToolResult(False, "", f"PDF merge error: {e}")


def tool_pdf_watermark(input_path: str, output_path: str = "", watermark_text: str = "WATERMARK",
                       opacity: float = 0.3, font_size: int = 50) -> ToolResult:
    """Add a text watermark to a PDF file"""
    if not HAS_PYMUPDF:
        return ToolResult(False, "", "PyMuPDF not installed. Run: pip install PyMuPDF")
    if not input_path or not os.path.exists(input_path):
        return ToolResult(False, "", f"Input file not found: {input_path}")

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_watermarked{ext}"

    opacity = max(0.05, min(1.0, opacity))
    font_size = max(10, min(200, font_size))

    try:
        doc = fitz.open(input_path)
        total_pages = len(doc)

        for page in doc:
            rect = page.rect
            # Create text point at center of page
            text_point = fitz.Point(rect.width / 2, rect.height / 2)

            # Add watermark with rotation
            page.insert_text(
                text_point,
                watermark_text,
                fontsize=font_size,
                fontname="helv",
                color=(0.5, 0.5, 0.5),
                rotate=45,
                opacity=opacity
            )

        doc.save(output_path)
        doc.close()
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return ToolResult(True, (
            f"Watermark added to '{output_path}'\n"
            f"Text: '{watermark_text}' | Opacity: {opacity} | Font size: {font_size}px\n"
            f"Pages watermarked: {total_pages}\n"
            f"Output size: {size_mb:.2f} MB"
        ))
    except Exception as e:
        return ToolResult(False, "", f"PDF watermark error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION FUNCTION - Called from create_tool_registry()
# ═══════════════════════════════════════════════════════════════════════════════

def register_advanced_tools(registry) -> None:
    """Register all 24 advanced tools with the main ToolRegistry"""

    # ── INFRASTRUCTURE & DEVOPS ──
    registry.register(
        "docker_list", tool_docker_list,
        "List Docker containers or images. Args: action (containers/images), all_items",
    )
    registry.register(
        "docker_build", tool_docker_build,
        "Build a Docker image from Dockerfile. Args: path, tag, dockerfile",
    )
    registry.register(
        "docker_start", tool_docker_start,
        "Start a Docker container. Args: container_id",
    )
    registry.register(
        "docker_stop", tool_docker_stop,
        "Stop a Docker container. Args: container_id",
    )
    registry.register(
        "docker_logs", tool_docker_logs,
        "Get Docker container logs. Args: container_id, tail",
    )
    registry.register(
        "github_issue", tool_github_issue,
        "GitHub issue management - list/create/get/update. Args: action, repo, issue_number, title, body, state, labels, token",
    )

    # ── NETWORKING & OSINT ──
    registry.register(
        "whois_lookup", tool_whois_lookup,
        "WHOIS domain lookup - registration info. Args: domain",
    )
    registry.register(
        "dns_resolve", tool_dns_resolve,
        "DNS record lookup. Args: domain, record_type (A/AAAA/MX/TXT/CNAME/NS), server",
    )
    registry.register(
        "subdomain_enum", tool_subdomain_enum,
        "Enumerate subdomains using common prefixes. Args: domain, wordlist_source",
    )
    registry.register(
        "ping_host", tool_ping_host,
        "Ping a host for connectivity and latency. Args: host, count",
    )
    registry.register(
        "traceroute", tool_traceroute,
        "Trace network path to host. Args: host, max_hops, timeout_ms",
    )
    registry.register(
        "port_scan", tool_port_scan,
        "Scan ports on a host. Args: host, ports (e.g. '80,443' or '1-1024'), timeout",
    )

    # ── ADVANCED RESEARCH & PARSING ──
    registry.register(
        "rss_read", tool_rss_read,
        "Read RSS/Atom feeds - news, blogs, CVE alerts. Args: url, max_items",
    )
    registry.register(
        "html_extract", tool_html_extract,
        "Extract data from HTML using CSS selectors or XPath. Args: url_or_html, selector_type (css/xpath), selector, attribute, source (url/html)",
    )
    registry.register(
        "wayback_fetch", tool_wayback_fetch,
        "Fetch historical snapshots from Wayback Machine. Args: url, timestamp",
    )

    # ── SYSTEM & IoT ──
    registry.register(
        "hardware_stats", tool_hardware_stats,
        "Real-time hardware stats - CPU/GPU/RAM/disk/network/processes. Args: component (all/cpu/memory/gpu/disk/network/process)",
    )
    registry.register(
        "mqtt_publish", tool_mqtt_publish,
        "Publish message to MQTT broker. Args: host, port, topic, message, username, password, qos, retain",
    )
    registry.register(
        "mqtt_subscribe", tool_mqtt_subscribe,
        "Subscribe to MQTT topic and capture messages. Args: host, port, topic, timeout_secs, username, password, qos",
    )

    # ── MEDIA MANIPULATION (FFmpeg) ──
    registry.register(
        "video_trim", tool_video_trim,
        "Trim video clip by start time and duration. Args: input_path, output_path, start_time, duration",
    )
    registry.register(
        "video_extract_audio", tool_video_extract_audio,
        "Extract audio track from video file. Args: input_path, output_path, audio_format, bitrate",
    )
    registry.register(
        "video_compress", tool_video_compress,
        "Compress/reduce video file size. Args: input_path, output_path, crf (0-51, lower=better), scale",
    )

    # ── PDF SURGERY ──
    registry.register(
        "pdf_split", tool_pdf_split,
        "Split PDF into separate files by page ranges. Args: input_path, output_dir, page_ranges (e.g. '1-3,5,7-10')",
    )
    registry.register(
        "pdf_merge", tool_pdf_merge,
        "Merge multiple PDFs into one. Args: input_paths (comma-separated), output_path",
    )
    registry.register(
        "pdf_watermark", tool_pdf_watermark,
        "Add text watermark to PDF. Args: input_path, output_path, watermark_text, opacity, font_size",
    )


# List of all advanced tool names (for LIGHT_TOOLS and category updates)
ADVANCED_TOOL_NAMES = [
    "docker_list", "docker_build", "docker_start", "docker_stop", "docker_logs", "github_issue",
    "whois_lookup", "dns_resolve", "subdomain_enum", "ping_host", "traceroute", "port_scan",
    "rss_read", "html_extract", "wayback_fetch",
    "hardware_stats", "mqtt_publish", "mqtt_subscribe",
    "video_trim", "video_extract_audio", "video_compress",
    "pdf_split", "pdf_merge", "pdf_watermark",
]

ADVANCED_LIGHT_TOOLS = {"ping_host", "dns_resolve", "hardware_stats", "whois_lookup", "port_scan"}

__all__ = [
    "ToolResult", "register_advanced_tools",
    "ADVANCED_TOOL_NAMES", "ADVANCED_LIGHT_TOOLS",
]
