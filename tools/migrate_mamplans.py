#!/usr/bin/env python3
"""Migrate old YAML Mamplans to mampok v2 JSON format.

Default behaviour (no flags): dry-run — analyse all files, print report, write nothing.
Use --migrate to enable file writing (requires confirmation).

Usage:
    python tools/migrate_mamplans.py INPUT_DIR [OUTPUT_DIR]
    python tools/migrate_mamplans.py --migrate INPUT_DIR OUTPUT_DIR
    python tools/migrate_mamplans.py --migrate --keep-path INPUT_DIR
    python tools/migrate_mamplans.py --migrate --keep-path --interactive INPUT_DIR
    python tools/migrate_mamplans.py --migrate --keep-path --cleanup INPUT_DIR
    python tools/migrate_mamplans.py -o report.txt INPUT_DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml
from referencing import Registry, Resource

# Fields allowed in container overrides (MamplateProperties from mamplate_schema.json)
_MAMPLATE_PROPERTIES = frozenset({
    "tool", "image", "containertype", "resources", "ports", "env",
    "volume", "readinessProbe", "imagePullPolicy", "annotation",
})

# Fields that move from old `tags` section into the new `service` section
_SERVICE_KEYS = frozenset({
    "analyst", "owner", "user", "organization", "datatype",
    "metadata", "download_allowed",
})

# Fields consumed elsewhere (not passed through to new `tags`)
_CONSUMED_TAG_KEYS = _SERVICE_KEYS | {"total_project_size", "creationdate"}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_mamplan_files(input_dir: Path) -> list[Path]:
    """Recursively find all old YAML mamplan files under input_dir."""
    results = []
    for path in sorted(input_dir.rglob("*")):
        name_lower = path.name.lower()
        if name_lower.endswith((".yaml", ".yml")) and "mamplan" in name_lower:
            results.append(path)
    return results


# ---------------------------------------------------------------------------
# Date conversion
# ---------------------------------------------------------------------------

def convert_date(date_str: str) -> str:
    """Convert DD/MM/YY or DD/MM/YYYY to ISO 8601 UTC datetime string.

    Raises:
        ValueError: if the date string cannot be parsed.
    """
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


def mtime_as_iso(path: Path) -> str:
    """Return the file modification time as ISO 8601 UTC string."""
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_list(value: object) -> list:
    """Normalise a string-or-list field to always return a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(old: dict, source_path: Path) -> tuple[dict, list[str], list[str]]:
    """Convert an old YAML mamplan dict to the new mampok v2 JSON structure.

    Returns:
        (new_mamplan, warnings, hints)
        warnings: issues that were auto-resolved with a fallback
        hints:    informational notes for manual review (auth=false, no metadata)
    """
    warnings: list[str] = []
    hints: list[str] = []

    project_old = old.get("project", {})
    deployment_old = old.get("deployment", {})
    tags_old = old.get("tags", {})
    container_old = old.get("container", {})

    # ------------------------------------------------------------------ project
    project: dict = {}
    project["project_id"] = project_old["id"]
    project["tool"] = project_old["tool"]
    project["files"] = to_list(project_old.get("files", []))

    # init_container: s3download is now a built-in default in v2 — drop it.
    # Only keep non-s3download entries.
    init_raw = project_old.get("init_container")
    if init_raw is not None:
        init_list = [x for x in to_list(init_raw) if x != "s3download"]
        if init_list:
            project["init_container"] = init_list

    # creation_date: try tags.creationdate, fall back to mtime
    creationdate_raw = tags_old.get("creationdate")
    if creationdate_raw:
        try:
            project["creation_date"] = convert_date(str(creationdate_raw))
        except ValueError:
            project["creation_date"] = mtime_as_iso(source_path)
            warnings.append(
                f"creation_date '{creationdate_raw}' nicht parsebar → mtime genutzt"
            )
    else:
        project["creation_date"] = mtime_as_iso(source_path)
        warnings.append("creation_date fehlend → mtime genutzt")

    # project_size: convert bytes → kilobytes
    total_size = tags_old.get("total_project_size")
    if total_size is not None:
        project["project_size"] = int(total_size) // 1024

    # --------------------------------------------------------------- deployment
    deployment: dict = {}
    deployment["cluster"] = deployment_old["cluster"]
    deployment["status"] = deployment_old.get("active", False)
    deployment["auth"] = deployment_old.get("auth", False)
    deployment["bucket"] = deployment_old.get("bucket", "")
    deployment["random_url_suffix"] = deployment_old.get("random", False)
    deployment["url"] = deployment_old.get("url", "")

    lifetime_raw = deployment_old.get("lifetime", "")
    if lifetime_raw:
        try:
            deployment["lifetime"] = convert_date(str(lifetime_raw))
        except ValueError:
            deployment["lifetime"] = ""
            warnings.append(f"lifetime '{lifetime_raw}' nicht parsebar → leer gesetzt")
    else:
        deployment["lifetime"] = ""
        warnings.append("lifetime fehlend → leer gesetzt")

    # hints for manual review
    if not deployment["auth"]:
        hints.append("auth: false")

    # ----------------------------------------------------------------- service
    owner = tags_old.get("owner", "")
    analyst_raw = tags_old.get("analyst")
    if analyst_raw is None:
        analyst = [owner] if owner else []
        warnings.append("analyst fehlend → owner übernommen")
    else:
        analyst = to_list(analyst_raw)

    metadata_raw = tags_old.get("metadata")
    metadata = to_list(metadata_raw) if metadata_raw is not None else []
    if not metadata:
        hints.append("keine Metadaten")

    service: dict = {
        "owner": owner,
        "analyst": analyst,
        "datatype": to_list(tags_old.get("datatype", [])),
        "download_allowed": tags_old.get("download_allowed", False),
        "metadata": metadata,
        "organization": to_list(tags_old.get("organization", [])),
        "user": to_list(tags_old.get("user", [])),
    }

    # -------------------------------------------- tags (pass-through remainder)
    remaining_tags = {k: v for k, v in tags_old.items() if k not in _CONSUMED_TAG_KEYS}

    # --------------------------------------------------------------- container
    new_container: dict = {}
    for section in ("main", "init"):
        section_old = container_old.get(section) or {}
        # Keep only fields known to MamplateProperties; drop extra_args etc.
        section_new = {k: v for k, v in section_old.items() if k in _MAMPLATE_PROPERTIES}
        if section_new:
            new_container[section] = section_new

    # ---------------------------------------------------------------- assemble
    new: dict = {
        "project": project,
        "deployment": deployment,
        "service": service,
    }
    if new_container:
        new["container"] = new_container
    if remaining_tags:
        new["tags"] = remaining_tags

    return new, warnings, hints


# ---------------------------------------------------------------------------
# Schema loading & validation
# ---------------------------------------------------------------------------

def _build_registry(schema_dir: Path) -> Registry:
    """Build a referencing.Registry from mamplan_schema.json and mamplate_schema.json."""
    resources = []
    for name in ("mamplan_schema.json", "mamplate_schema.json"):
        with open(schema_dir / name, encoding="utf-8") as f:
            schema_dict = json.load(f)
        resources.append((name, Resource.from_contents(schema_dict)))
    return Registry().with_resources(resources)


def load_schema_and_registry(schema_path: Path) -> tuple[dict, Registry]:
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    registry = _build_registry(schema_path.parent)
    return schema, registry


def _format_validation_error(e: jsonschema.ValidationError) -> str:
    """Return a concise error message, replacing full-value pattern errors
    with just the offending characters."""
    field = ".".join(str(p) for p in e.absolute_path) or "root"
    if e.validator == "pattern" and isinstance(e.instance, str):
        # Extract only the characters that violate the pattern ^[^A-Z_]*$
        bad = sorted(set(c for c in e.instance if c.isupper() or c == "_"))
        bad_str = ", ".join(f"'{c}'" for c in bad) if bad else "ungültige Zeichen"
        return f"{field}: enthält {bad_str} (nicht erlaubt laut Schema)"
    return f"{field}: {e.message}"


def validate(new: dict, schema: dict, registry: Registry) -> list[str]:
    """Validate new mamplan dict against mamplan_schema.json.

    Returns a list of error messages (empty = valid).
    """
    errors = []
    try:
        jsonschema.validate(instance=new, schema=schema, registry=registry)
    except jsonschema.ValidationError as e:
        errors.append(_format_validation_error(e))
    except jsonschema.SchemaError as e:
        errors.append(f"Schema-Fehler: {e.message}")
    return errors


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def process_file(path: Path, schema: dict, registry: Registry) -> dict:
    """Parse, convert and validate one YAML mamplan file.

    Returns a result dict with keys:
        path, new, project_id, status, warnings, errors, hints
    """
    try:
        with open(path, encoding="utf-8") as f:
            old = yaml.safe_load(f)
        new, warnings, hints = convert(old, path)
        errors = validate(new, schema, registry)
        status = "ERROR" if errors else ("WARNING" if warnings else "OK")
        return {
            "path": path,
            "new": new,
            "project_id": new["project"]["project_id"],
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "hints": hints,
        }
    except Exception as exc:
        return {
            "path": path,
            "new": None,
            "project_id": None,
            "status": "ERROR",
            "warnings": [],
            "errors": [str(exc)],
            "hints": [],
        }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int) -> list[str]:
    """Split text into lines of at most `width` characters, breaking on spaces."""
    if len(text) <= width:
        return [text]
    result = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut == -1:
            cut = width
        result.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        result.append(text)
    return result


def format_report(results: list[dict], total: int | None = None) -> str:
    lines: list[str] = []
    lines.append("Mamplan Migration Report")

    col_file = max((len(r["path"].name) for r in results), default=38) + 2
    col_status = 9
    col_msg = 45
    col_hint = 30
    table_width = col_file + col_status + col_msg + col_hint + 3
    lines.append("=" * table_width)
    shown = len(results)
    total = total if total is not None else shown
    if shown < total:
        lines.append(f"Gefunden: {total} Dateien  (angezeigt: {shown})\n")
    else:
        lines.append(f"Gefunden: {total} Dateien\n")

    header = (
        f"{'Datei':<{col_file}} {'Status':<{col_status}} "
        f"{'Fehler/Warnung':<{col_msg}} {'Hinweise':<{col_hint}}"
    )
    lines.append(header)
    lines.append("-" * table_width)

    pad = " " * (col_file + col_status + 1)

    for r in results:
        msgs = r["errors"] + r["warnings"]
        msg_str = "; ".join(msgs) if msgs else "-"
        hint_str = ", ".join(r["hints"]) if r["hints"] else "-"

        msg_lines = _wrap(msg_str, col_msg)
        hint_lines = _wrap(hint_str, col_hint)

        # Merge both columns row by row
        row_count = max(len(msg_lines), len(hint_lines))
        msg_lines += [""] * (row_count - len(msg_lines))
        hint_lines += [""] * (row_count - len(hint_lines))

        for i, (m, h) in enumerate(zip(msg_lines, hint_lines)):
            if i == 0:
                lines.append(
                    f"{r['path'].name:<{col_file}} {r['status']:<{col_status}} "
                    f"{m:<{col_msg}} {h:<{col_hint}}"
                )
            else:
                lines.append(f"{pad}{m:<{col_msg}} {h:<{col_hint}}")

    all_results = results  # summary always reflects the filtered set passed in
    ok = sum(1 for r in all_results if r["status"] == "OK")
    warn = sum(1 for r in all_results if r["status"] == "WARNING")
    err = sum(1 for r in all_results if r["status"] == "ERROR")
    lines.append("")
    suffix = f" (von {total} gesamt)" if shown < total else ""
    lines.append(f"Zusammenfassung: {ok} OK, {warn} WARNING, {err} ERROR{suffix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def output_path_for(result: dict, output_dir: Path | None, keep_path: bool) -> Path:
    filename = f"{result['project_id']}-mamplan.json"
    if keep_path:
        return result["path"].parent / filename
    assert output_dir is not None
    return output_dir / filename


# ---------------------------------------------------------------------------
# Interactive confirmation
# ---------------------------------------------------------------------------

def interactive_confirm(result: dict) -> bool:
    """Ask the user whether to migrate a WARNING/ERROR file. Default: No."""
    print(f"\n[{result['status']}] {result['path'].name}")
    if result["errors"]:
        print(f"  Fehler:   {'; '.join(result['errors'])}")
    if result["warnings"]:
        print(f"  Warnung:  {'; '.join(result['warnings'])}")
    if result["hints"]:
        print(f"  Hinweise: {', '.join(result['hints'])}")
    answer = input("  Migrieren? [y/N]: ").strip().lower()
    return answer == "y"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate old YAML Mamplans to mampok v2 JSON format.\n"
            "Default: dry-run — analyse all files and print report, nothing is written."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_dir", type=Path, help="Verzeichnis mit alten YAML-Mamplans (rekursiv)")
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        help="Zielverzeichnis für neue JSON-Dateien (nicht nötig mit --keep-path)",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Schreibmodus aktivieren (nach Bestätigung). Ohne diesen Flag: nur Dry-Run.",
    )
    parser.add_argument(
        "--keep-path",
        action="store_true",
        help="JSON neben der Quelldatei ablegen statt in OUTPUT_DIR.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Bei WARNING/ERROR jede Datei einzeln bestätigen (erfordert --migrate).",
    )
    parser.add_argument(
        "-o",
        metavar="REPORT_FILE",
        type=Path,
        help="Report zusätzlich als Textdatei speichern.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Alte YAML-Quelldateien nach erfolgreicher Migration löschen (erfordert --migrate).",
    )
    parser.add_argument(
        "--show",
        metavar="LEVEL",
        nargs="+",
        choices=["ok", "warning", "error"],
        default=["ok", "warning", "error"],
        help="Welche Status-Level in der Tabelle angezeigt werden. "
             "Werte: ok warning error (mehrere kombinierbar, z.B. --show warning error). "
             "Standard: alle.",
    )
    args = parser.parse_args()

    # Argument validation
    if args.migrate and not args.keep_path and args.output_dir is None:
        parser.error("Mit --migrate muss entweder OUTPUT_DIR oder --keep-path angegeben werden.")
    if args.cleanup and not args.migrate:
        parser.error("--cleanup erfordert --migrate.")

    # Locate schema
    schema_path = (
        Path(__file__).parent.parent
        / "src/mampok/mamplan/schemas/mamplan_schema.json"
    )
    if not schema_path.exists():
        print(f"Schema nicht gefunden: {schema_path}", file=sys.stderr)
        sys.exit(1)

    schema, registry = load_schema_and_registry(schema_path)

    # Discover files
    files = find_mamplan_files(args.input_dir)
    if not files:
        print("Keine Mamplan-Dateien gefunden.")
        sys.exit(0)

    # Process all files
    results = [process_file(p, schema, registry) for p in files]

    # Print / save report
    show_levels = {s.upper() for s in args.show}
    visible = [r for r in results if r["status"] in show_levels]
    report = format_report(visible, total=len(results))
    print(report)

    if args.o:
        args.o.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport gespeichert: {args.o}")

    if not args.migrate:
        print("\n(Dry-Run — keine Dateien geschrieben. Mit --migrate aktivieren.)")
        return

    # Confirm before writing
    answer = input("\nJetzt migrieren? [y/N]: ").strip().lower()
    if answer != "y":
        print("Abgebrochen.")
        return

    if args.output_dir and not args.keep_path:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    migrated: list[tuple[Path, Path]] = []
    skipped: list[Path] = []

    for result in results:
        # ERROR files: skip by default; ask in interactive mode
        if result["status"] == "ERROR":
            if args.interactive:
                if not interactive_confirm(result):
                    skipped.append(result["path"])
                    continue
            else:
                print(f"  SKIP (ERROR): {result['path'].name}")
                skipped.append(result["path"])
                continue

        # WARNING files: ask individually in interactive mode
        if result["status"] == "WARNING" and args.interactive:
            if not interactive_confirm(result):
                skipped.append(result["path"])
                continue

        out = output_path_for(result, args.output_dir, args.keep_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result["new"], f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  OK: {result['path'].name} → {out}")
        migrated.append((result["path"], out))

    print(f"\nMigriert: {len(migrated)}, Übersprungen: {len(skipped)}")

    if args.cleanup and migrated:
        answer = input(
            f"\n{len(migrated)} alte YAML-Datei(en) löschen? [y/N]: "
        ).strip().lower()
        if answer == "y":
            for source, _ in migrated:
                source.unlink()
                print(f"  Gelöscht: {source}")
        else:
            print("Cleanup abgebrochen.")


if __name__ == "__main__":
    main()
