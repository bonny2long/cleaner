from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CleanerPlan


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id(prefix: str = "cleaner") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def read_recent_jsonl(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"event": "unreadable_log_line", "raw": line})
    return records


def plan_markdown(plan: CleanerPlan) -> str:
    lines = [
        f"# NAS Cleaner Dry-Run Report",
        "",
        f"Run ID: `{plan.run_id}`",
        f"Created: `{plan.created_at}`",
        f"Mode: `{plan.mode}`",
        f"Dry run: `{plan.dry_run}`",
        f"Data root: `{plan.data_root}`",
        f"Minimum age gate: `{plan.min_age_days} days`",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(plan.counts.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Planned Actions", ""])
    if not plan.actions:
        lines.append("No actions planned.")
    for action in plan.actions:
        lines.extend([
            f"### {action.category}: {action.relative_path}",
            "",
            f"- Action: `{action.action}`",
            f"- Safety: `{action.safety_status}`",
            f"- Severity: `{action.severity}`",
            f"- Reason: {action.reason}",
        ])
        if action.evidence:
            lines.extend([
                f"- Evidence manifest: `{action.evidence.manifest_path}`",
                f"- Destination verified: `{action.evidence.destination_verified}`",
                f"- Status after move: `{action.evidence.status_after_move}`",
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_plan_report(reports_dir: Path, log_path: Path, plan: CleanerPlan) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{plan.run_id}.json"
    md_path = reports_dir / f"{plan.run_id}.md"
    latest_path = reports_dir / "latest-plan.json"
    write_json(json_path, plan.to_dict())
    md_path.write_text(plan_markdown(plan), encoding="utf-8")
    write_json(latest_path, plan.to_dict())
    append_jsonl(
        log_path,
        {
            "timestamp": plan.created_at,
            "event": "plan_written",
            "run_id": plan.run_id,
            "json_path": str(json_path),
            "markdown_path": str(md_path),
            "actions": len(plan.actions),
            "dry_run": plan.dry_run,
        },
    )
    return {"json_path": str(json_path), "markdown_path": str(md_path), "latest_path": str(latest_path)}
