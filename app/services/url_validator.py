"""SSRF-safe URL validation for the 'paste a link' flow.

Rules:
- http/https only.
- Host must resolve (every A/AAAA record checked) to a *public* IP only.
  Loopback, private, link-local (incl. 169.254.169.254 cloud metadata),
  multicast and reserved ranges are blocked.
- Redirects are followed manually (max 5) and every hop is re-validated
  after DNS resolution.
- YouTube / streaming pages are NOT downloadable sources; they return a
  clear, honest explanation instead of pretending to fetch them.
"""
import ipaddress
import socket
from urllib.parse import urlparse

import requests

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata"}
PAGE_ONLY_HOSTS = (
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    "netflix.com", "primevideo.com", "hotstar.com", "disneyplus.com",
)
DIRECT_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
MAX_REDIRECTS = 5


class URLValidationError(Exception):
    pass


def _resolve_ips(hostname):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise URLValidationError(f"Could not resolve host '{hostname}'.") from exc
    ips = set()
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            ips.add(sockaddr[0])
    if not ips:
        raise URLValidationError(f"Could not resolve host '{hostname}'.")
    return ips


def assert_public_url(url):
    """Validate scheme + host and that ALL resolved IPs are public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLValidationError("Only http:// and https:// links are allowed.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise URLValidationError("The link has no host.")
    if host in BLOCKED_HOSTNAMES:
        raise URLValidationError("This host is not allowed.")
    if host.endswith(".local") or host.endswith(".internal"):
        raise URLValidationError("Internal hostnames are not allowed.")
    # Literal IP in the URL
    try:
        ip = ipaddress.ip_address(host)
        candidates = [ip]
    except ValueError:
        candidates = [ipaddress.ip_address(x) for x in _resolve_ips(host)]
    for ip in candidates:
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            raise URLValidationError("Links to private or internal addresses are blocked.")
    return parsed


def classify_url(url):
    """Return 'page_only' for watch-page hosts, otherwise 'direct'."""
    host = (urlparse(url).hostname or "").lower()
    bare = host[4:] if host.startswith("www.") else host
    bare = bare[2:] if bare.startswith("m.") else bare
    if bare in PAGE_ONLY_HOSTS or any(bare.endswith("." + h) for h in PAGE_ONLY_HOSTS):
        return "page_only"
    return "direct"


def validate_remote_video_url(url, session=None, timeout=15):
    """Full pre-flight: SSRF checks + redirect walk + content check.

    Returns dict(final_url, content_type, content_length).
    Raises URLValidationError with a user-honest message.
    """
    url = (url or "").strip()
    if not url:
        raise URLValidationError("Please paste a video URL.")
    # Watch-page check comes FIRST (host/scheme only, no DNS yet) so streaming
    # pages always get the honest explanation, whatever DNS does with them.
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise URLValidationError("Only http:// and https:// links are allowed.")
    if classify_url(url) == "page_only":
        raise URLValidationError(
            "This is a streaming/watch page. Downloading from this source is not "
            "permitted or technically available here, so it cannot be split from a "
            "link. Please download the video with the rights holder's permission "
            "and upload the file instead."
        )
    assert_public_url(url)
    session = session or requests.Session()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_public_url(current)  # re-validate every hop after DNS/redirects
        try:
            resp = session.head(current, allow_redirects=False, timeout=timeout)
            if resp.status_code in (405, 501):  # some servers dislike HEAD
                resp = session.get(current, allow_redirects=False, stream=True,
                                   timeout=timeout)
                resp.close()
        except requests.RequestException as exc:
            raise URLValidationError(f"Could not reach the URL: {exc}") from exc
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise URLValidationError("The URL redirected without a destination.")
            from urllib.parse import urljoin
            current = urljoin(current, location)
            continue
        if resp.status_code != 200:
            raise URLValidationError(f"The server returned HTTP {resp.status_code} for this link.")
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        path_ext = "." + current.rsplit(".", 1)[-1].lower().split("?")[0] if "." in current else ""
        if not (ctype.startswith("video/") or path_ext in DIRECT_VIDEO_EXTS):
            raise URLValidationError(
                "This link does not point to a direct video file. Only direct, "
                "authorized video-file URLs (MP4/MOV/MKV/AVI/WebM) can be fetched."
            )
        length = resp.headers.get("Content-Length")
        return {
            "final_url": current,
            "content_type": ctype,
            "content_length": int(length) if length and length.isdigit() else None,
        }
    raise URLValidationError("Too many redirects.")
