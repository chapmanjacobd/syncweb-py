import datetime, re
from pathlib import Path
from typing import Generator, Iterable, List

import requests
from library.utils.log_utils import log


class EventSource:
    def __init__(
        self,
        node,  # SyncthingNode
        event_types: Iterable[str] | None = None,
        since: int = 0,
        start: datetime.datetime | None = None,
        timeout: int = 60,
        limit: int = 0,
    ):
        self.node = node
        self.event_types = list(event_types or [])
        self.since = since
        self.start = start or datetime.datetime.now(datetime.timezone.utc)
        self.timeout = timeout
        self.limit = limit

    def fetch_once(self) -> list[dict]:
        params = {"since": str(self.since), "timeout": str(self.timeout)}
        if self.limit:
            params["limit"] = str(self.limit)
        if self.event_types:
            params["events"] = ",".join(self.event_types)

        try:
            resp = self.node.session.get(f"{self.node.api_url}/rest/events", params=params, timeout=self.timeout + 10)
        except requests.RequestException as e:
            log.warning("[%s] request failed: %s", self.node.name, e)
            return []

        if resp.status_code in (400, 404):
            # Syncthing probably restarted or dropped event buffer
            log.warning("[%s] Event buffer reset (status %s)", self.node.name, resp.status_code)
            self.since = 0
            return []

        resp.raise_for_status()
        events = resp.json()

        filtered = []
        for e in events:
            try:
                t = datetime.datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            except Exception:
                continue
            if t >= self.start:
                filtered.append(e)
            self.since = max(self.since, e.get("id", self.since))
        return filtered

    def __iter__(self) -> Generator[dict, None, None]:
        last_id = self.since
        while True:
            events = self.fetch_once()
            for e in events:
                cur_id = e.get("id", 0)
                if last_id and cur_id > last_id + 1:
                    log.warning("[%s] Missed events: gap from %s → %s", self.node.name, last_id, cur_id)
                last_id = cur_id
                yield e


class IgnorePattern:
    def __init__(self, pattern: str, ignored=True, casefold=False, deletable=False):
        self.pattern = pattern
        self.ignored = ignored
        self.casefold = casefold
        self.deletable = deletable

        # Convert Syncthing-style pattern to Python regex
        pat = pattern.lstrip("/")
        # escape, then restore wildcards
        pat = re.escape(pat)
        pat = pat.replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", ".")
        anchor = pattern.startswith("/")
        self.regex = re.compile(f"^{pat}$" if anchor else f"(^|.*/)({pat})$", re.IGNORECASE if casefold else 0)

    def match(self, relpath: str) -> bool:
        return bool(self.regex.search(relpath))


class IgnoreMatcher:
    # see interface in syncthing/lib/ignore/matcher.go

    def __init__(self, folder_path: Path):
        self.folder_path = Path(folder_path)
        self.patterns: List[IgnorePattern] = []
        self.load(self.folder_path / ".stignore")

    def load(self, file: Path):
        if not file.exists():
            return
        seen = set()
        for line in file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line in seen:
                continue
            seen.add(line)
            self.patterns.extend(self.parse_line(line))

    def parse_line(self, line: str) -> List[IgnorePattern]:
        ignored = True
        casefold = False
        deletable = False

        # parse prefixes
        while True:
            if line.startswith("!"):
                ignored = not ignored
                line = line[1:]
            elif line.startswith("(?i)"):
                casefold = True
                line = line[4:]
            elif line.startswith("(?d)"):
                deletable = True
                line = line[4:]
            else:
                break

        if not line:
            return []

        pats = []
        # rooted vs unrooted handling
        if line.startswith("/"):
            pats.append(IgnorePattern(line, ignored, casefold, deletable))
        else:
            # both direct and recursive match
            pats.append(IgnorePattern(line, ignored, casefold, deletable))
            pats.append(IgnorePattern("**/" + line, ignored, casefold, deletable))
        return pats

    def match(self, relpath: str) -> bool:
        relpath = relpath.replace("\\", "/")
        result = False
        for p in self.patterns:
            if p.match(relpath):
                result = p.ignored
        return result
