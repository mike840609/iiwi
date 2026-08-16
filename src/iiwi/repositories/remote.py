"""Normalize Git remotes into credential-free canonical identities."""

from urllib.parse import urlsplit

# Default ports per scheme, mirroring git's own. A port equal to the scheme
# default is not part of the identity, so the explicit and implicit forms of
# the same remote normalize identically (ssh://host:22/repo == ssh://host/repo).
_DEFAULT_PORTS = {
    "ssh": 22,
    "git": 9418,
    "http": 80,
    "https": 443,
    "ftp": 21,
    "ftps": 990,
}


def _is_scp_like(value: str) -> bool:
    """Whether `value` is an scp-style `[user@]host:path` SSH remote.

    Git only treats a colon as the scp separator when it appears before any
    slash; a colon after a slash is part of a local filename. Everything else
    without a scheme is a local filesystem path, not a network URL.
    """

    first_colon = value.find(":")
    if first_colon == -1:
        return False
    first_slash = value.find("/")
    return first_slash == -1 or first_colon < first_slash


def normalize_git_remote(remote: str) -> str:
    """Return host[/port]/path for common Git remote URL formats.

    Accepts explicit URLs (`https://host/org/repo.git`, `ssh://host:2222/...`,
    `git://host/...`) and scp-style SSH remotes (`git@host:org/repo.git`). A
    scheme-less value that is not scp-style is a local filesystem path —
    relative, absolute, or `~`-based — and raises ValueError so callers fall
    back to a path-based identity instead of collapsing distinct local
    repositories into one canonical identity.

    The identity is `host/path` with the trailing `.git` removed. A non-default
    port is included as `host:port/path`; default ports (ssh 22, git 9418,
    http 80, https 443, ftp 21, ftps 990) are omitted.
    """

    value = remote.strip()
    if not value:
        raise ValueError("git remote must not be empty")

    if "://" not in value:
        if not _is_scp_like(value):
            raise ValueError("git remote is a local path, not a network URL")
        user_host, path = value.split(":", 1)
        value = f"ssh://{user_host}/{path}"

    parsed = urlsplit(value)
    host = parsed.hostname
    if not host:
        raise ValueError("git remote does not contain a host")
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path:
        raise ValueError("git remote does not contain a repository path")

    port = parsed.port
    if port is not None and port != _DEFAULT_PORTS.get(parsed.scheme):
        host = f"{host.lower()}:{port}"
    else:
        host = host.lower()
    return f"{host}/{path}"


def repository_display_name(identity: str) -> str:
    """Humanize the final repository path component."""

    name = identity.rstrip("/").rsplit("/", 1)[-1]
    words = name.replace("_", "-").split("-")
    return " ".join(word.capitalize() for word in words if word)
