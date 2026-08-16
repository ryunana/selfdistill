#!/usr/bin/env python3
"""Build and verify a local continuous-distillation evidence package.

The command deliberately does no semantic analysis and never edits canonical
or inbox inputs.  It only reads ``canonical/**/*.md`` and ``inbox/*.json``
and writes a complete report under ``reports/latest/``.

Usage::

    python3 distill_audit.py audit
    python3 distill_audit.py verify reports/latest

Only Python's standard library is used so the public toolkit remains easy to
run locally on Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
EVIDENCE_RE = re.compile(r"^ev-[0-9a-f]{16}$")
EVIDENCE_TOKEN_RE = re.compile(r"\bev-[0-9a-f]{16}\b")
ANY_EVIDENCE_TOKEN_RE = re.compile(r"\bev-[A-Za-z0-9_-]+\b")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
HEADING_RE = re.compile(r"(?m)^##(?!#)[ \t]+([^\n]+?)\s*$")
H1_RE = re.compile(r"(?m)^#(?!#)[ \t]+([^\n]+?)\s*$")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
ALLOWED_STATUS = {"pending", "accepted", "rejected", "unknown"}
ALLOWED_LAYERS = {"L1", "L2", "L3", "L4", "unknown"}
ALLOWED_SCOPES = {"universal", "contextual", "temporary", "one_off", "unknown"}
ALLOWED_SENSITIVITY = {"normal", "sensitive"}


class AuditError(RuntimeError):
    """Raised when an audit input or report violates the local contract."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_id(*parts: str) -> str:
    """Derive a content-independent evidence ID from source identity."""

    raw = "\x1f".join(parts).encode("utf-8")
    return "ev-" + hashlib.sha256(raw).hexdigest()[:16]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise AuditError(f"path escapes project root: {path}") from exc


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _read_bytes(path: Path, root: Path) -> bytes:
    rel = _relative(path, root)
    if path.is_symlink():
        raise AuditError(f"symlink input is not allowed: {rel}")
    if not path.is_file():
        raise AuditError(f"missing input file: {rel}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AuditError(f"reading {rel} failed: {exc}") from exc


def _read_text(path: Path, root: Path) -> str:
    data = _read_bytes(path, root)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError(f"file is not UTF-8: {_relative(path, root)}") from exc


def _require_dict(data: Any, key: str) -> dict[str, Any]:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        raise AuditError(f"missing or invalid {key}")
    return value


def _require_string(data: dict[str, Any], path: str, *, allow_empty: bool = True) -> str:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise AuditError(f"missing {path}")
        current = current[part]
    if not isinstance(current, str) or (not allow_empty and not current):
        raise AuditError(f"invalid {path}")
    return current


def _reject_extra(data: dict[str, Any], allowed: set[str], prefix: str = "") -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        label = prefix or "candidate"
        raise AuditError(f"unknown field in {label}: {', '.join(extra)}")


def _is_rediscovery_candidate(data: dict[str, Any]) -> bool:
    source = data.get("source")
    source_type = source.get("type", "") if isinstance(source, dict) else ""
    source_type = source_type.lower() if isinstance(source_type, str) else ""
    candidate_id = data.get("id", "")
    reference = source.get("reference", "") if isinstance(source, dict) else ""
    return (
        source_type == "rediscovery"
        or source_type.startswith("rediscovery")
        or source_type == "approved_conflict_resolution"
        or (isinstance(candidate_id, str) and candidate_id.startswith("rediscovery-"))
        or (isinstance(reference, str) and "discoveries" in reference)
    )


def validate_v2_candidate(data: dict[str, Any]) -> None:
    """Validate one inbox v2 object without third-party JSON-schema support."""

    if not isinstance(data, dict):
        raise AuditError("candidate must be an object")

    required = {
        "schema_version",
        "id",
        "created_at",
        "source",
        "classification",
        "change",
        "evidence_ids",
        "conflicts",
        "status",
    }
    _reject_extra(data, required)
    if data.get("schema_version") != 2:
        raise AuditError("invalid schema_version")

    candidate_id = _require_string(data, "id", allow_empty=False)
    if len(candidate_id) < 8 or not ID_RE.fullmatch(candidate_id):
        raise AuditError("invalid id")
    created_at = _require_string(data, "created_at", allow_empty=False)
    if len(created_at) < 10:
        raise AuditError("invalid created_at")

    source = _require_dict(data, "source")
    _reject_extra(source, {"type", "reference", "quote"}, "source")
    _require_string(data, "source.type", allow_empty=False)
    _require_string(data, "source.reference", allow_empty=False)
    _require_string(data, "source.quote")

    classification = _require_dict(data, "classification")
    _reject_extra(
        classification,
        {"feedback_type", "target_layer", "target_section", "scope", "sensitivity"},
        "classification",
    )
    feedback_type = classification.get("feedback_type")
    if not isinstance(feedback_type, list) or any(not isinstance(item, str) for item in feedback_type):
        raise AuditError("invalid classification.feedback_type")
    if classification.get("target_layer") not in ALLOWED_LAYERS:
        raise AuditError("invalid classification.target_layer")
    _require_string(data, "classification.target_section")
    if classification.get("scope") not in ALLOWED_SCOPES:
        raise AuditError("invalid classification.scope")
    if classification.get("sensitivity") not in ALLOWED_SENSITIVITY:
        raise AuditError("invalid classification.sensitivity")

    change = _require_dict(data, "change")
    _reject_extra(change, {"scene", "wrong", "correct", "proposed_action"}, "change")
    for field in ("scene", "wrong", "correct", "proposed_action"):
        _require_string(data, f"change.{field}")

    evidence_ids = data.get("evidence_ids")
    if not isinstance(evidence_ids, list):
        raise AuditError("invalid evidence_ids")
    if any(not isinstance(item, str) or not EVIDENCE_RE.fullmatch(item) for item in evidence_ids):
        raise AuditError("invalid evidence_ids")
    if len(set(evidence_ids)) != len(evidence_ids):
        raise AuditError("duplicate evidence_ids")
    if _is_rediscovery_candidate(data) and not evidence_ids:
        raise AuditError("rediscovery candidate requires evidence_ids")

    conflicts = data.get("conflicts")
    if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
        raise AuditError("invalid conflicts")
    if data.get("status") not in ALLOWED_STATUS:
        raise AuditError("invalid status")


def parse_v2_file(path: Path, root: Path) -> list[dict[str, Any]]:
    """Parse one JSON candidate into one evidence record."""

    text = _read_text(path, root)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuditError(f"invalid JSON in {_relative(path, root)}: {exc.msg}") from exc
    validate_v2_candidate(data)

    relative = _relative(path, root)
    evidence_id = _stable_id("inbox-v2", relative, data["id"], "1")
    source = data["source"]
    classification = data["classification"]
    change = data["change"]
    source_type = source["type"].lower()
    external_markers = ("external", "evaluation", "counter", "review", "feedback")
    supporting_evidence: list[str] = []
    if data["conflicts"] or any(marker in source_type for marker in external_markers):
        supporting_evidence = [source["reference"]]

    return [
        {
            "evidence_id": evidence_id,
            "kind": "inbox_candidate",
            "format": "v2-json",
            "source_path": relative,
            "title": data["id"],
            "occurrence": 1,
            "line_start": 1,
            "line_end": max(1, len(text.splitlines())),
            "created_at": data["created_at"],
            "status": data["status"],
            "status_raw": data["status"],
            "feedback_types": data["classification"]["feedback_type"],
            "user_quotes": [source["quote"]] if source["quote"] else [],
            "supporting_evidence": supporting_evidence,
            "context": source["reference"],
            "proposed_action": change["proposed_action"],
            "sensitive": classification["sensitivity"] == "sensitive",
            "content": json.dumps(data, ensure_ascii=False, indent=2),
        }
    ]


def _title_for_file(text: str, path: Path) -> str:
    match = H1_RE.search(text)
    return match.group(1).strip() if match else path.stem


def _canonical_sections(path: Path, root: Path) -> list[dict[str, Any]]:
    text = _read_text(path, root)
    relative = _relative(path, root)
    headings = list(HEADING_RE.finditer(text))
    parts: list[tuple[str, int, int]] = []
    if headings:
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            parts.append((heading.group(1).strip(), heading.start(), end))
    else:
        parts.append((_title_for_file(text, path), 0, len(text)))

    counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for title, start, end in parts:
        counts[title] += 1
        content = text[start:end].strip()
        line_end_offset = max(start, end - 1) if end else 0
        records.append(
            {
                "evidence_id": _stable_id("canonical", relative, title, str(counts[title])),
                "kind": "canonical_section",
                "format": "markdown",
                "source_path": relative,
                "title": title,
                "occurrence": counts[title],
                "line_start": _line_number(text, start),
                "line_end": _line_number(text, line_end_offset),
                "created_at": "unknown",
                "status": "confirmed",
                "status_raw": "confirmed",
                "feedback_types": [],
                "user_quotes": [],
                "supporting_evidence": [],
                "context": "",
                "proposed_action": "",
                "sensitive": "[SENSITIVE]" in content,
                "content": content,
            }
        )
    return records


def _assert_real_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise AuditError(f"{label} must not be a symlink")
    if not path.is_dir():
        raise AuditError(f"missing {label}")


def discover_inputs(root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    root = root.resolve()
    canonical_root = root / "canonical"
    inbox_root = root / "inbox"
    _assert_real_directory(canonical_root, "canonical/")
    _assert_real_directory(inbox_root, "inbox/")

    canonical = sorted(canonical_root.rglob("*.md"))
    inbox_json = sorted(inbox_root.glob("*.json"))
    readme = inbox_root / "README.md"
    instructions = [readme] if _lexists(readme) else []
    for path in canonical + inbox_json + instructions:
        _read_bytes(path, root)
    return canonical, inbox_json, instructions


def _inventory_entry(path: Path, root: Path, role: str) -> dict[str, Any]:
    data = _read_bytes(path, root)
    return {
        "path": _relative(path, root),
        "role": role,
        "sha256": _sha256_bytes(data),
        "bytes": len(data),
        "parse_status": "ok",
    }


def build_audit(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read all source inputs and return an inventory plus evidence records."""

    root = root.resolve()
    canonical, inbox_json, instructions = discover_inputs(root)
    files: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for path in canonical:
        files.append(_inventory_entry(path, root, "canonical"))
        evidence.extend(_canonical_sections(path, root))
    for path in inbox_json:
        files.append(_inventory_entry(path, root, "inbox"))
        evidence.extend(parse_v2_file(path, root))
    for path in instructions:
        files.append(_inventory_entry(path, root, "instruction"))

    ids = [record["evidence_id"] for record in evidence]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise AuditError("duplicate evidence IDs: " + ", ".join(duplicates))

    inventory = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_root": ".",
        "summary": {
            "canonical_files": len(canonical),
            "inbox_files": len(inbox_json),
            "candidate_units": len(inbox_json),
            "content_files": len(canonical) + len(inbox_json),
            "instruction_files": len(instructions),
            "evidence_records": len(evidence),
        },
        "files": sorted(files, key=lambda item: item["path"]),
    }
    return inventory, evidence


def _coverage_sources(evidence: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for record in evidence:
        path = record["source_path"]
        kind = record["kind"]
        evidence_id = record["evidence_id"]
        if kind == "inbox_candidate":
            for dimension in ("D2", "D3", "D4", "D6"):
                result[dimension].append(evidence_id)
            if record.get("supporting_evidence"):
                result["D5"].append(evidence_id)
        elif kind == "canonical_section":
            if "canonical/03-l3" in path or "canonical/04-domain-playbooks" in path:
                result["D1"].append(evidence_id)
            if "canonical/01-l1" in path or path.endswith("writing-style.md"):
                result["D3"].append(evidence_id)
            if (
                "canonical/02-l2" in path
                or path.endswith("agent-work.md")
                or path.endswith("product-work.md")
            ):
                result["D4"].append(evidence_id)
            if DATE_RE.search(record["content"]) or any(
                marker in record["content"] for marker in ("[as_of:", "[temporary]", "已过期", "不再")
            ):
                result["D6"].append(evidence_id)
    return {key: sorted(set(values)) for key, values in result.items()}


def _render_evidence(evidence: list[dict[str, Any]]) -> str:
    lines = [
        "# 完整证据包",
        "",
        "> 本文件由 canonical + inbox 全量生成，可能含敏感内容。仅在用户授权的当前 AI 会话中使用，不要上传到其他服务。",
        "",
    ]
    for record in evidence:
        sensitivity = "SENSITIVE" if record["sensitive"] else "normal"
        lines.extend(
            [
                f"## {record['evidence_id']} · {record['title']}",
                "",
                f"- 来源：`{record['source_path']}`，行 {record['line_start']}-{record['line_end']}",
                f"- 类型：{record['kind']} / {record['format']}",
                f"- 状态：{record['status']}（原始：{record['status_raw'] or '缺失'}）",
                f"- 敏感性：{sensitivity}",
                "",
                record["content"],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_coverage(inventory: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    definitions = {
        "D1": "作品与实际输出",
        "D2": "对话中的明确修正",
        "D3": "表达方式",
        "D4": "决策与真实取舍",
        "D5": "外部评价与反证",
        "D6": "时间变化与过期规则",
    }
    sources = _coverage_sources(evidence)
    summary = inventory["summary"]
    lines = [
        "# 六维覆盖报告",
        "",
        "## 全量边界",
        "",
        f"- canonical：{summary['canonical_files']} 个文件",
        f"- inbox：{summary['inbox_files']} 个文件，{summary['candidate_units']} 个候选单元",
        f"- 授权内容文件：{summary['content_files']} 个；说明文件：{summary['instruction_files']} 个",
        f"- evidence：{summary['evidence_records']} 条",
        "- 覆盖结论基于来源类型与显式字段，只表示“有可供分析的证据”，不等于该维度已经充分蒸馏。",
        "",
    ]
    for key, title in definitions.items():
        ids = sources.get(key, [])
        lines.extend([f"## {key} · {title}", ""])
        if not ids:
            lines.extend(["- 状态：gap", "- 当前授权材料中没有可直接归入该维度的显式证据。", ""])
            continue
        state = "limited" if key == "D5" and len(ids) < 3 else "available"
        lines.extend([f"- 状态：{state}", f"- 可用 evidence：{len(ids)} 条", "- 引用：" + "、".join(ids), ""])
    return "\n".join(lines).rstrip() + "\n"


def _write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _remove_existing_directory(path: Path) -> None:
    if path.is_symlink():
        raise AuditError(f"refusing to remove symlink: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif _lexists(path):
        path.unlink()


def audit_project(root: Path = PROJECT_ROOT) -> Path:
    """Build reports/latest atomically and return its path."""

    root = root.resolve()
    inventory, evidence = build_audit(root)
    reports = root / "reports"
    if reports.is_symlink():
        raise AuditError("reports/ must not be a symlink")
    if _lexists(reports) and not reports.is_dir():
        raise AuditError("reports/ is not a directory")
    reports.mkdir(mode=0o700, exist_ok=True)
    os.chmod(reports, 0o700)

    latest = reports / "latest"
    if latest.is_symlink():
        raise AuditError("reports/latest must be a real directory")
    if _lexists(latest) and not latest.is_dir():
        raise AuditError("reports/latest must be a real directory")

    temp_dir = Path(tempfile.mkdtemp(prefix=".audit-", dir=os.fspath(reports)))
    os.chmod(temp_dir, 0o700)
    try:
        _write_private(temp_dir / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
        _write_private(
            temp_dir / "evidence.jsonl",
            "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in evidence),
        )
        _write_private(temp_dir / "evidence.md", _render_evidence(evidence))
        _write_private(temp_dir / "coverage.md", _render_coverage(inventory, evidence))

        previous = reports / f".latest-previous-{os.getpid()}"
        if _lexists(previous):
            _remove_existing_directory(previous)
        moved_previous = False
        if _lexists(latest):
            latest.rename(previous)
            moved_previous = True
        try:
            temp_dir.rename(latest)
            os.chmod(latest, 0o700)
        except Exception:
            if moved_previous and not _lexists(latest) and _lexists(previous):
                previous.rename(latest)
            raise
        if _lexists(previous):
            _remove_existing_directory(previous)
        return latest
    except Exception:
        if _lexists(temp_dir):
            _remove_existing_directory(temp_dir)
        raise


def _safe_report_path(root: Path, report: Path) -> Path:
    """Resolve a report path while rejecting outside and symlink paths."""

    root = root.resolve()
    raw = report if report.is_absolute() else root / report
    lexical = Path(os.path.abspath(os.fspath(raw)))
    reports = Path(os.path.abspath(os.fspath(root / "reports")))
    try:
        relative = lexical.relative_to(reports)
    except ValueError as exc:
        raise AuditError("report path must be inside reports/") from exc
    if reports.is_symlink() or not reports.is_dir():
        raise AuditError("reports/ is missing or is a symlink")
    current = reports
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AuditError("report path must not contain symlinks")
    return lexical


def _require_report_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"{label} is missing or is a symlink")


def _load_evidence_ids(path: Path) -> set[str]:
    _require_report_file(path, "evidence.jsonl")
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AuditError(f"cannot read {path.name}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditError(f"invalid evidence.jsonl at line {line_number}") from exc
        if not isinstance(record, dict):
            raise AuditError(f"invalid evidence record at line {line_number}")
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not EVIDENCE_RE.fullmatch(evidence_id):
            raise AuditError(f"invalid evidence ID at line {line_number}")
        if evidence_id in ids:
            raise AuditError(f"duplicate evidence ID: {evidence_id}")
        ids.add(evidence_id)
    return ids


def _read_report_text(path: Path, label: str) -> str:
    _require_report_file(path, label)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AuditError(f"cannot read {label}") from exc


def _referenced_evidence_ids(report: Path) -> set[str]:
    refs: set[str] = set()
    discoveries = report / "discoveries.md"
    if _lexists(discoveries):
        text = _read_report_text(discoveries, "discoveries.md")
        refs.update(EVIDENCE_TOKEN_RE.findall(text))
        malformed = sorted(set(ANY_EVIDENCE_TOKEN_RE.findall(text)) - refs)
        if malformed:
            raise AuditError("invalid evidence reference: " + ", ".join(malformed))

    candidates = report / "candidates"
    if _lexists(candidates):
        if candidates.is_symlink() or not candidates.is_dir():
            raise AuditError("candidates must be a real directory")
        for path in sorted(candidates.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise AuditError(f"candidate path is invalid: {path.name}")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise AuditError(f"invalid candidate JSON: {path.name}") from exc
            except (OSError, UnicodeError) as exc:
                raise AuditError(f"cannot read candidate: {path.name}") from exc
            if not data.get("evidence_ids"):
                raise AuditError("rediscovery candidate requires evidence_ids")
            validate_v2_candidate(data)
            refs.update(data["evidence_ids"])
            for conflict in data.get("conflicts", []):
                refs.update(EVIDENCE_TOKEN_RE.findall(conflict))
                malformed = sorted(set(ANY_EVIDENCE_TOKEN_RE.findall(conflict)) - set(EVIDENCE_TOKEN_RE.findall(conflict)))
                if malformed:
                    raise AuditError("invalid evidence reference: " + ", ".join(malformed))
    return refs


def verify_report(root: Path = PROJECT_ROOT, report: Path | None = None) -> dict[str, Any]:
    """Fail closed if sources, evidence IDs, or generated references drift."""

    root = root.resolve()
    report_path = _safe_report_path(root, report or (root / "reports" / "latest"))
    if report_path.is_symlink() or not report_path.is_dir():
        raise AuditError("report directory is missing or is a symlink")

    required = ["inventory.json", "evidence.jsonl", "evidence.md", "coverage.md"]
    for name in required:
        _require_report_file(report_path / name, name)
    try:
        inventory = json.loads(_read_report_text(report_path / "inventory.json", "inventory.json"))
    except json.JSONDecodeError as exc:
        raise AuditError("invalid inventory.json") from exc
    if not isinstance(inventory, dict) or not isinstance(inventory.get("files"), list):
        raise AuditError("invalid inventory.json")

    current_inventory, _ = build_audit(root)
    expected: dict[str, str] = {}
    for item in inventory["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise AuditError("invalid inventory file entry")
        if item["path"] in expected:
            raise AuditError("duplicate inventory path: " + item["path"])
        expected[item["path"]] = item["sha256"]
    current = {item["path"]: item["sha256"] for item in current_inventory["files"]}
    if set(expected) != set(current):
        added = sorted(set(current) - set(expected))
        removed = sorted(set(expected) - set(current))
        raise AuditError(f"source drift: file set changed; added={added}, removed={removed}")
    changed = sorted(path for path in expected if expected[path] != current[path])
    if changed:
        raise AuditError("source drift: hash changed for " + ", ".join(changed))
    if inventory.get("files") != current_inventory.get("files"):
        raise AuditError("source drift: inventory metadata changed")
    if inventory.get("summary") != current_inventory.get("summary"):
        raise AuditError("source drift: inventory summary changed")

    evidence_ids = _load_evidence_ids(report_path / "evidence.jsonl")
    refs = _referenced_evidence_ids(report_path)
    unknown = sorted(refs - evidence_ids)
    if unknown:
        raise AuditError("unknown evidence ID: " + ", ".join(unknown))
    return {"files": len(expected), "evidence_ids": len(evidence_ids), "references": len(refs)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("audit", help="build reports/latest from canonical + inbox")
    verify_parser = subparsers.add_parser("verify", help="fail-closed verification of a report")
    verify_parser.add_argument("report", nargs="?", default="reports/latest")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            report = audit_project(PROJECT_ROOT)
            inventory = json.loads((report / "inventory.json").read_text(encoding="utf-8"))
            summary = inventory["summary"]
            print(
                "audit: OK "
                f"content_files={summary['content_files']} "
                f"candidate_units={summary['candidate_units']} "
                f"evidence={summary['evidence_records']}"
            )
        else:
            report_arg = Path(args.report)
            report = report_arg if report_arg.is_absolute() else PROJECT_ROOT / report_arg
            result = verify_report(PROJECT_ROOT, report)
            print(f"verify: OK files={result['files']} evidence={result['evidence_ids']} refs={result['references']}")
        return 0
    except (AuditError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
