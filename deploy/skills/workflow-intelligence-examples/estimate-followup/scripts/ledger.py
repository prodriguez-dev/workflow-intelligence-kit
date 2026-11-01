"""Local record of which estimates were already put in front of the operator.

The source is read-only, so the skill cannot mark an estimate as "follow-up
drafted" in the CRM. Without some memory, the same drafts would arrive every
morning until the operator sent them and the CRM logged it. This file is that
memory: {"version": 1, "surfaced": {"<estimate id>": "YYYY-MM-DD"}}.

It lives under HERMES_HOME, never in the business system, and is written only
when the CLI runs with --record (the scheduled pulse). A manual preview never
changes it.
"""

from __future__ import annotations

import json
import os
import tempfile


def load(path):
    """Return (surfaced, warning). A missing file is empty; a corrupt one warns."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as exc:
        return {}, f"ignoring unreadable ledger {path}: {exc}"
    surfaced = data.get("surfaced") if isinstance(data, dict) else None
    if not isinstance(surfaced, dict):
        return {}, f"ignoring malformed ledger {path}"
    return {str(k): str(v) for k, v in surfaced.items()}, None


def updated(surfaced, open_ids, newly_surfaced, today):
    """Drop estimates that are no longer open, then stamp today's."""
    keep = {k: v for k, v in surfaced.items() if k in open_ids}
    for eid in newly_surfaced:
        keep[eid] = today.isoformat()
    return keep


def save(path, surfaced):
    """Atomic write, private to the service user."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".surfaced.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "surfaced": dict(sorted(surfaced.items()))}, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
