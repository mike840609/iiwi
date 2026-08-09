"""Normalize Git remotes into credential-free canonical identities."""

from urllib.parse import urlsplit


def normalize_git_remote(remote: str) -> str:
    """Return host/path for common Git remote URL formats."""

    value = remote.strip()
    if not value:
        raise ValueError("git remote must not be empty")

    if "://" not in value and ":" in value:
        left, right = value.split(":", 1)
        if "/" not in left:
            value = f"ssh://{left}/{right}"

    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = parsed.hostname
    if not host:
        raise ValueError("git remote does not contain a host")
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path:
        raise ValueError("git remote does not contain a repository path")
    return f"{host.lower()}/{path}"


def repository_display_name(identity: str) -> str:
    """Humanize the final repository path component."""

    name = identity.rstrip("/").rsplit("/", 1)[-1]
    words = name.replace("_", "-").split("-")
    return " ".join(word.capitalize() for word in words if word)
