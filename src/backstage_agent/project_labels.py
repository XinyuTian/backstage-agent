from __future__ import annotations

import re


NOISE_LINES = {
    "$ paid",
    "paid",
    "nonunion",
    "union",
    "sag-aftra",
}

BOUNDARY_LINES = {
    "backstage",
    "verify data",
    "trusted by",
    "basic filter",
    "edit this search",
    "change email frequency",
    "more",
    "apply",
    "share",
    "view all matching jobs",
}


def extract_backstage_project_labels(text: str) -> list[str]:
    """Return Backstage-provided project labels without inventing categories."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    labels: list[str] = []
    seen: set[str] = set()

    for posted_index, line in enumerate(lines):
        if not line.lower().startswith("posted "):
            continue
        for candidate in reversed(lines[max(0, posted_index - 10) : posted_index]):
            if _is_metadata_boundary(candidate):
                if labels:
                    break
                continue
            if not _is_project_label_candidate(candidate):
                if labels:
                    break
                continue
            key = candidate.lower()
            if key not in seen:
                labels.append(candidate)
                seen.add(key)
        break

    labels.reverse()
    return labels


def _is_project_label_candidate(line: str) -> bool:
    lower = line.lower()
    if lower in NOISE_LINES:
        return False
    if lower in BOUNDARY_LINES:
        return False
    if len(line) > 80:
        return False
    if lower.startswith(
        (
            "posted ",
            "seeking talent",
            "estimated pay amount",
            "rate:",
            "total pay:",
            "work-from-home",
            "roles in this project",
            "collapse all roles",
            "expand all roles",
            "actors & performers",
            "pre-screen requests:",
        )
    ):
        return False
    if re.search(r"\b\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\b|\b\d{1,2}\+", line):
        return False
    if re.search(r"\bnew jobs?\b|\bmatching your search\b", lower):
        return False
    if re.search(r"\b(hours?|days?) of work\b", lower):
        return False
    if re.search(r"\b(worldwide|nationwide|remote|local to)\b", lower):
        return False
    if re.search(r"\b(lead|supporting|background|principal|featured)\b", lower) and "," in line:
        return False
    return True


def _is_metadata_boundary(line: str) -> bool:
    lower = line.lower()
    if lower in NOISE_LINES:
        return False
    if lower in BOUNDARY_LINES:
        return True
    if lower.startswith(
        (
            "seeking talent",
            "estimated pay amount",
            "rate:",
            "total pay:",
            "work-from-home",
            "pre-screen requests:",
        )
    ):
        return True
    if re.search(r"\b\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\b|\b\d{1,2}\+", line):
        return True
    if re.search(r"\bnew jobs?\b|\bmatching your search\b", lower):
        return True
    if re.search(r"\b(hours?|days?) of work\b", lower):
        return True
    return False
