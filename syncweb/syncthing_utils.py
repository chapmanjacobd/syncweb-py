import re
from pathlib import Path
from typing import List


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
