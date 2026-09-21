"""
actions/github_manager.py — Headless GitHub & Developer Command Center for JARVIS
Provides hands-free GitHub API operations:
1. Unread notifications triage
2. Pull requests listing & automated AI code review
3. Issues creation and listing
4. GitHub Actions CI/CD workflow status monitoring
5. Trending & repository search
6. One-shot voice Git commit & push
"""

from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CONFIG_DIR = BASE_DIR / "config"
API_KEYS_FILE = CONFIG_DIR / "api_keys.json"


def _get_github_token() -> str:
    """Retrieve GitHub Personal Access Token from env or config/api_keys.json."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    if API_KEYS_FILE.exists():
        try:
            data = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
            return data.get("github_token") or data.get("github") or ""
        except Exception:
            pass
    return ""


def _github_api_request(endpoint: str, method: str = "GET", payload: dict | None = None, accept: str = "application/vnd.github.v3+json") -> tuple[int, any]:
    """Execute authenticated GitHub REST API request."""
    token = _get_github_token()
    url = endpoint if endpoint.startswith("http") else f"https://api.github.com/{endpoint.lstrip('/')}"
    headers = {
        "Accept": accept,
        "User-Agent": "JARVIS-Developer-Assistant",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in content_type:
                return status, json.loads(raw.decode("utf-8", errors="replace"))
            return status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
            return e.code, err_json
        except Exception:
            return e.code, err_body
    except Exception as e:
        return 500, str(e)


def get_default_repo() -> str:
    """Extract default owner/repo from local git remote."""
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True, stderr=subprocess.DEVNULL).strip()
        # Handle https://github.com/owner/repo.git or git@github.com:owner/repo.git
        if "github.com" in out:
            cleaned = out.split("github.com")[-1].lstrip("/:").removesuffix(".git")
            return cleaned
    except Exception:
        pass
    return "Scientist-Py/MARK-54"


def list_notifications(max_results: int = 5) -> str:
    """Fetch unread GitHub notifications."""
    status, data = _github_api_request("notifications")
    if status == 401:
        return "Sir, GitHub token is missing or unauthorized. Please configure your GITHUB_TOKEN."
    if status != 200 or not isinstance(data, list):
        return f"Sir, could not retrieve notifications: {data}"
    if not data:
        return "Sir, you have no unread GitHub notifications."

    lines = [f"Sir, you have {len(data)} unread GitHub notification(s):"]
    for item in data[:max_results]:
        subject = item.get("subject", {}).get("title", "Untitled")
        repo = item.get("repository", {}).get("full_name", "")
        reason = item.get("reason", "")
        lines.append(f"• [{repo}] {subject} ({reason})")
    return "\n".join(lines)


def list_pull_requests(repo: str = "", state: str = "open") -> str:
    """List pull requests for a repository."""
    target_repo = repo.strip() or get_default_repo()
    status, data = _github_api_request(f"repos/{target_repo}/pulls?state={state}")
    if status != 200 or not isinstance(data, list):
        return f"Sir, could not retrieve pull requests for {target_repo}: {data}"
    if not data:
        return f"Sir, there are no {state} pull requests in {target_repo}."

    lines = [f"Sir, found {len(data)} {state} pull request(s) in {target_repo}:"]
    for pr in data[:5]:
        num = pr.get("number")
        title = pr.get("title", "")
        user = pr.get("user", {}).get("login", "unknown")
        lines.append(f"• PR #{num}: {title} (by @{user})")
    return "\n".join(lines)


def review_pull_request(repo: str = "", pr_number: int | None = None, player=None) -> str:
    """Fetch PR diff and generate an AI code review summary."""
    target_repo = repo.strip() or get_default_repo()
    if not pr_number:
        # Get latest open PR
        status, data = _github_api_request(f"repos/{target_repo}/pulls?state=open")
        if status == 200 and isinstance(data, list) and data:
            pr_number = data[0].get("number")
        else:
            return f"Sir, no open pull requests found to review in {target_repo}."

    # Fetch PR metadata
    status, pr_meta = _github_api_request(f"repos/{target_repo}/pulls/{pr_number}")
    if status != 200 or not isinstance(pr_meta, dict):
        return f"Sir, could not fetch PR #{pr_number} metadata."

    pr_title = pr_meta.get("title", "")
    author = pr_meta.get("user", {}).get("login", "")

    # Fetch PR diff
    status_diff, diff_text = _github_api_request(
        f"repos/{target_repo}/pulls/{pr_number}",
        accept="application/vnd.github.v3.diff"
    )

    if status_diff != 200 or not isinstance(diff_text, str):
        return f"Sir, could not fetch diff for PR #{pr_number}."

    # Call Gemini for AI Code Review if available
    review_summary = ""
    try:
        import core.gemini as gemini
        prompt = (
            f"You are JARVIS, an expert senior software architect. Review this GitHub PR diff for {target_repo} PR #{pr_number} ('{pr_title}').\n"
            f"Provide:\n"
            f"1. Brief executive summary of what was changed.\n"
            f"2. Security, bugs, or performance issues (if any).\n"
            f"3. Verdict (LGTM / Changes Requested).\n\n"
            f"Diff:\n{diff_text[:6000]}"
        )
        review_summary = gemini.call(prompt, tier=gemini.FAST, timeout_ms=30000)
    except Exception as e:
        review_summary = f"Summary: PR #{pr_number} by @{author} modifies {pr_meta.get('changed_files', 0)} files with +{pr_meta.get('additions', 0)}/-{pr_meta.get('deletions', 0)} lines."

    if player and hasattr(player, "show_content"):
        player.show_content(f"PR #{pr_number} REVIEW: {target_repo}", f"Title: {pr_title}\nAuthor: @{author}\n\n{review_summary}")

    return f"Sir, I have reviewed PR #{pr_number} ('{pr_title}') by @{author}. {review_summary[:300]}"


def create_issue(title: str, body: str = "", labels: list[str] | None = None, repo: str = "") -> str:
    """Create a new GitHub issue."""
    target_repo = repo.strip() or get_default_repo()
    if not title:
        return "Sir, please provide a title for the issue."

    payload = {"title": title, "body": body or "Created via JARVIS voice assistant."}
    if labels:
        payload["labels"] = labels

    status, data = _github_api_request(f"repos/{target_repo}/issues", method="POST", payload=payload)
    if status == 201 and isinstance(data, dict):
        issue_num = data.get("number")
        html_url = data.get("html_url", "")
        return f"Sir, successfully created Issue #{issue_num} ('{title}') in {target_repo}. Link: {html_url}"
    return f"Sir, failed to create issue: {data}"


def check_workflow_status(repo: str = "") -> str:
    """Check recent CI/CD GitHub Actions workflow runs."""
    target_repo = repo.strip() or get_default_repo()
    status, data = _github_api_request(f"repos/{target_repo}/actions/runs?per_page=3")
    if status != 200 or not isinstance(data, dict):
        return f"Sir, could not fetch GitHub Actions status for {target_repo}."

    runs = data.get("workflow_runs", [])
    if not runs:
        return f"Sir, no GitHub Actions workflows found for {target_repo}."

    latest = runs[0]
    wf_name = latest.get("name", "Build")
    status_str = latest.get("status", "unknown")
    conclusion = latest.get("conclusion") or status_str
    commit_msg = latest.get("head_commit", {}).get("message", "").split("\n")[0]

    return f"Sir, the latest workflow '{wf_name}' for commit '{commit_msg}' concluded with: {conclusion.upper()}."


def search_repos(query: str, max_results: int = 5) -> str:
    """Search GitHub repositories."""
    if not query:
        return "Sir, what topic or repository would you like to search for?"
    
    encoded = urllib.parse.quote(query) if hasattr(urllib, "parse") else query
    import urllib.parse
    encoded = urllib.parse.quote(query)
    status, data = _github_api_request(f"search/repositories?q={encoded}&sort=stars&order=desc&per_page={max_results}")
    if status != 200 or not isinstance(data, dict):
        return f"Sir, failed to search GitHub repositories: {data}"

    items = data.get("items", [])
    if not items:
        return f"Sir, no repositories found matching '{query}'."

    lines = [f"Sir, here are the top repositories for '{query}':"]
    for repo in items[:max_results]:
        full_name = repo.get("full_name", "")
        stars = repo.get("stargazers_count", 0)
        desc = repo.get("description") or "No description."
        lines.append(f"• {full_name} (⭐ {stars:,}): {desc[:80]}")
    return "\n".join(lines)


def git_commit_and_push(commit_msg: str = "", branch: str = "") -> str:
    """Stage local changes, commit with message, and push to GitHub."""
    try:
        # 1. Check if git status has changes
        status_out = subprocess.check_output(["git", "status", "--porcelain"], text=True, stderr=subprocess.STDOUT)
        if not status_out.strip():
            return "Sir, working directory is clean. No changes to commit."

        # 2. Stage changes
        subprocess.check_call(["git", "add", "-A"])

        # 3. Commit
        msg = commit_msg.strip() or "feat: update codebase via JARVIS Developer Assistant"
        subprocess.check_call(["git", "commit", "-m", msg])

        # 4. Push
        target_branch = branch.strip()
        if not target_branch:
            try:
                target_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
            except Exception:
                target_branch = "main"

        subprocess.check_call(["git", "push", "origin", target_branch])
        return f"Sir, changes committed with message '{msg}' and pushed successfully to origin/{target_branch}."
    except subprocess.CalledProcessError as e:
        return f"Sir, git operation encountered an error: {e}"
    except Exception as e:
        return f"Sir, git commit and push failed: {e}"


def github_manager_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    """
    Main entrypoint for github_manager action.
    """
    action = (parameters.get("action") or "notifications").lower().strip()
    repo = (parameters.get("repo") or "").strip()
    query = (parameters.get("query") or "").strip()
    title = (parameters.get("title") or "").strip()
    body = (parameters.get("body") or "").strip()
    pr_number = parameters.get("pr_number")
    commit_msg = (parameters.get("commit_msg") or parameters.get("message") or "").strip()
    branch = (parameters.get("branch") or "").strip()

    if action in ("notifications", "unread", "check_notifications"):
        return list_notifications()

    elif action in ("list_prs", "prs", "pull_requests"):
        return list_pull_requests(repo=repo)

    elif action in ("review_pr", "review", "code_review"):
        return review_pull_request(repo=repo, pr_number=pr_number, player=player)

    elif action in ("create_issue", "new_issue", "report_bug"):
        labels = parameters.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",") if l.strip()]
        return create_issue(title=title, body=body, labels=labels, repo=repo)

    elif action in ("workflow", "ci", "cicd", "build_status", "actions"):
        return check_workflow_status(repo=repo)

    elif action in ("search", "trending", "find_repo"):
        return search_repos(query=query or repo)

    elif action in ("commit_and_push", "push", "commit"):
        return git_commit_and_push(commit_msg=commit_msg, branch=branch)

    return f"Sir, unknown GitHub action '{action}'. Supported actions: notifications, list_prs, review_pr, create_issue, workflow, search, commit_and_push."


TOOL = {
    "name": "github_manager",
    "description": (
        "THE tool for managing GitHub operations and developer workflows. "
        "Supports: checking unread notifications, listing and reviewing pull requests (with AI code review), "
        "creating GitHub issues, checking GitHub Actions CI/CD workflow status, searching trending repositories, "
        "and performing voice-controlled git commit and push."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["notifications", "list_prs", "review_pr", "create_issue", "workflow", "search", "commit_and_push"],
                "description": "The GitHub action to perform."
            },
            "repo": {
                "type": "STRING",
                "description": "Target repository in 'owner/repo' format (e.g. 'Scientist-Py/MARK-54', 'facebook/react'). If omitted, defaults to current repository."
            },
            "pr_number": {
                "type": "INTEGER",
                "description": "Pull request number to inspect or review."
            },
            "title": {
                "type": "STRING",
                "description": "Title of the issue or pull request."
            },
            "body": {
                "type": "STRING",
                "description": "Body/description content for issues."
            },
            "labels": {
                "type": "ARRAY",
                "description": "List of label strings for issues (e.g. ['bug', 'enhancement'])."
            },
            "query": {
                "type": "STRING",
                "description": "Search query for repositories or trending topics."
            },
            "commit_msg": {
                "type": "STRING",
                "description": "Git commit message for commit_and_push action."
            },
            "branch": {
                "type": "STRING",
                "description": "Target branch to push to (defaults to current active branch)."
            }
        },
        "required": ["action"]
    },
    "handler": github_manager_action,
}
