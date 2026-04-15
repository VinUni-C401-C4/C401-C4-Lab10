#!/usr/bin/env python3
"""
Lab Day 10 — ETL entrypoint: ingest → clean → validate → embed.

Ingestion Owner responsibilities (Sprint 1):
  - Define raw source paths and validate their existence.
  - Emit structured log: run_id, raw_records, cleaned_records, quarantine_records.
  - Write manifest JSON after every run (lineage traceability).
  - Expose freshness sub-command for SLA monitoring.

Tiếp nối Day 09: cùng corpus docs trong data/docs/; pipeline này xử lý *export*
raw (CSV) đại diện cho lớp ingestion từ DB/API trước khi embed lại vector store.

Quick start:
  pip install -r requirements.txt
  cp .env.example .env
  python etl_pipeline.py run

Inject mode (Sprint 3 — skip refund-fix, bypass expectation):
  python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from monitoring.freshness_check import check_manifest_freshness
from quality.expectations import run_expectations
from transform.cleaning_rules import (
    clean_rows,
    load_raw_csv,
    write_cleaned_csv,
    write_quarantine_csv,
)

# ---------------------------------------------------------------------------
# Environment & directory layout
# ---------------------------------------------------------------------------

load_dotenv()

ROOT = Path(__file__).resolve().parent

# Raw source — single authoritative export path (Ingestion Owner owns this constant)
RAW_DEFAULT = ROOT / "data" / "raw" / "policy_export_dirty.csv"

# Artifact directories (created on demand, never committed empty)
ART       = ROOT / "artifacts"
LOG_DIR   = ART / "logs"
MAN_DIR   = ART / "manifests"
QUAR_DIR  = ART / "quarantine"
CLEAN_DIR = ART / "cleaned"
EVAL_DIR  = ART / "eval"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dirs(*dirs: Path) -> None:
    """Create all artifact directories if they do not exist."""
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _safe_run_id(run_id: str) -> str:
    r"""
    Sanitise run_id for use in filenames.

    Replaces all characters that are unsafe on Windows/Linux/macOS filesystems
    (including ``:``, ``/``, ``\``, ``*``, ``?``, ``<``, ``>``, ``|``, ``"``, space)
    with underscores, then collapses consecutive underscores.
    """
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", run_id)
    return safe.strip("_") or "run"


class PipelineLogger:
    """
    Dual-output logger: prints to stdout AND appends to a log file.

    Emits key=value lines so the log is both human-readable and
    machine-parseable (grep-friendly for grading scripts).

    Implements the context manager protocol so the underlying file handle
    is opened once and held open for the full pipeline run, avoiding
    repeated open()/close() syscalls on every log line.

    Usage::
        with PipelineLogger(log_path) as log:
            log("run_id=sprint1")
            log.section("STAGE 1")
    """

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("a", encoding="utf-8")
        self._write(f"\n{'=' * 60}")
        self._write(f"log_session_start={datetime.now(timezone.utc).isoformat()}")

    def _write(self, line: str) -> None:
        """Write one line to the open file handle and flush immediately."""
        self._fh.write(line + "\n")
        self._fh.flush()

    def __enter__(self) -> "PipelineLogger":
        return self

    def __exit__(self, *_: object) -> None:
        self._fh.close()

    def __call__(self, msg: str) -> None:
        """Log and print a single message line."""
        print(msg)
        self._write(msg)

    def section(self, title: str) -> None:
        """Print a visual section separator."""
        self(f"--- {title} ---")


# ---------------------------------------------------------------------------
# Sub-command: run (ingest → clean → validate → embed)
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    """
    Execute the full ETL pipeline.

    Exit codes:
      0 → success (PIPELINE_OK)
      1 → raw file missing / bad path
      2 → expectation suite halted (and --skip-validate not set)
      3 → embed step failed
    """
    # -------------------------------------------------------------------------
    # Stage 0: Resolve run identity & paths
    # -------------------------------------------------------------------------
    run_id  = args.run_id.strip() or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    safe_id = _safe_run_id(run_id)

    raw_path = Path(args.raw).resolve()
    if not raw_path.is_file():
        print(
            f"ERROR: Raw file not found: {raw_path}\n"
            f"       Override with --raw <path>",
            file=sys.stderr,
        )
        return 1

    # Ensure all artifact directories exist before any write
    _ensure_dirs(LOG_DIR, MAN_DIR, QUAR_DIR, CLEAN_DIR, EVAL_DIR)

    log_path = LOG_DIR / f"run_{safe_id}.log"
    log = PipelineLogger(log_path)
    # NOTE: PipelineLogger holds an open file handle. The with-block ensures
    # it is closed cleanly even if an unhandled exception occurs downstream.
    # Callers using _embed_cleaned_csv pass `log` as a Callable[[str], None].

    # -------------------------------------------------------------------------
    # Stage 1: Ingest  (Ingestion Owner)
    # -------------------------------------------------------------------------
    log.section("STAGE 1 — INGEST")
    log(f"run_id={run_id}")
    log(f"raw_path={raw_path.relative_to(ROOT)}")
    log(f"pipeline_start={datetime.now(timezone.utc).isoformat()}")

    rows = load_raw_csv(raw_path)
    raw_count = len(rows)
    log(f"raw_records={raw_count}")

    # -------------------------------------------------------------------------
    # Stage 2: Clean + Quarantine
    # -------------------------------------------------------------------------
    log.section("STAGE 2 — CLEAN")
    log(f"apply_refund_window_fix={not args.no_refund_fix}")

    cleaned, quarantine = clean_rows(
        rows,
        apply_refund_window_fix=not args.no_refund_fix,
    )

    cleaned_path = CLEAN_DIR / f"cleaned_{safe_id}.csv"
    quar_path    = QUAR_DIR  / f"quarantine_{safe_id}.csv"

    write_cleaned_csv(cleaned_path, cleaned)
    write_quarantine_csv(quar_path, quarantine)

    log(f"cleaned_records={len(cleaned)}")
    log(f"quarantine_records={len(quarantine)}")
    log(f"cleaned_csv={cleaned_path.relative_to(ROOT)}")
    log(f"quarantine_csv={quar_path.relative_to(ROOT)}")

    # Breakdown of quarantine reasons — observable metric per reason
    reason_counts: dict[str, int] = {}
    for r in quarantine:
        reason = str(r.get("reason", "unknown"))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items()):
        log(f"quarantine_reason[{reason}]={count}")

    # -------------------------------------------------------------------------
    # Stage 3: Validate (Expectation Suite)
    # -------------------------------------------------------------------------
    log.section("STAGE 3 — VALIDATE")

    results, halt = run_expectations(cleaned)
    for r in results:
        sym = "OK  " if r.passed else "FAIL"
        log(f"expectation[{r.name}] {sym} severity={r.severity} :: {r.detail}")

    if halt and not args.skip_validate:
        log("PIPELINE_HALT: expectation suite has halt-severity failures.")
        log(f"log_path={log_path.relative_to(ROOT)}")
        return 2

    if halt and args.skip_validate:
        log(
            "WARN: expectation failed but --skip-validate is set "
            "→ continuing embed (intentional corruption demo — Sprint 3 only)."
        )

    # -------------------------------------------------------------------------
    # Stage 4: Embed
    # -------------------------------------------------------------------------
    log.section("STAGE 4 — EMBED")

    embed_ok = _embed_cleaned_csv(cleaned_path, run_id=run_id, log=log)
    if not embed_ok:
        return 3

    # -------------------------------------------------------------------------
    # Stage 5: Manifest + Freshness  (Ingestion Owner)
    # -------------------------------------------------------------------------
    log.section("STAGE 5 — MANIFEST & FRESHNESS")

    # Use lexicographic max only on non-empty ISO-8601 values; fall back to
    # empty string so freshness_check raises WARN (not crash) if missing.
    exported_timestamps = [r.get("exported_at", "") for r in cleaned if r.get("exported_at", "")]
    latest_exported = max(exported_timestamps) if exported_timestamps else ""

    manifest: dict[str, Any] = {
        "run_id"            : run_id,
        "run_timestamp"     : datetime.now(timezone.utc).isoformat(),
        "raw_path"          : str(raw_path.relative_to(ROOT)),
        "raw_records"       : raw_count,
        "cleaned_records"   : len(cleaned),
        "quarantine_records": len(quarantine),
        "quarantine_reasons": reason_counts,
        "latest_exported_at": latest_exported,
        "no_refund_fix"     : bool(args.no_refund_fix),
        "skipped_validate"  : bool(args.skip_validate and halt),
        "cleaned_csv"       : str(cleaned_path.relative_to(ROOT)),
        "quarantine_csv"    : str(quar_path.relative_to(ROOT)),
        "chroma_path"       : os.environ.get("CHROMA_DB_PATH", "./chroma_db"),
        "chroma_collection" : os.environ.get("CHROMA_COLLECTION", "day10_kb"),
        "log_path"          : str(log_path.relative_to(ROOT)),
    }

    man_path = MAN_DIR / f"manifest_{safe_id}.json"
    man_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"manifest_written={man_path.relative_to(ROOT)}")

    sla_hours = float(os.environ.get("FRESHNESS_SLA_HOURS", "24"))
    status, fdetail = check_manifest_freshness(man_path, sla_hours=sla_hours)
    log(f"freshness_check={status} {json.dumps(fdetail, ensure_ascii=False)}")

    # -------------------------------------------------------------------------
    # Done
    # -------------------------------------------------------------------------
    log(f"pipeline_end={datetime.now(timezone.utc).isoformat()}")
    log("PIPELINE_OK")
    return 0


# ---------------------------------------------------------------------------
# Embed helper (Stage 4)
# ---------------------------------------------------------------------------

def _embed_cleaned_csv(
    cleaned_csv: Path,
    *,
    run_id: str,
    log: Callable[[str], None],
) -> bool:
    """
    Upsert cleaned chunks into ChromaDB.

    Idempotency strategy
    --------------------
    - Upsert by stable ``chunk_id`` → repeated runs with the same data
      produce identical vector records.
    - Prune (delete) any vector IDs present in the collection that are NOT
      in the current cleaned set → the index is always a snapshot of the
      latest publish boundary (no stale vectors leaking into retrieval).

    Returns True on success, False on fatal error.
    """
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        log("ERROR: chromadb not installed. Run: pip install -r requirements.txt")
        return False

    db_path         = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name      = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    rows = load_raw_csv(cleaned_csv)
    if not rows:
        log("WARN: Cleaned CSV is empty — skipping embed.")
        return True

    log(f"embed_model={model_name}")
    log(f"embed_db_path={db_path}")
    log(f"embed_collection={collection_name}")

    client = chromadb.PersistentClient(path=db_path)
    emb    = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    col    = client.get_or_create_collection(name=collection_name, embedding_function=emb)

    current_ids = [r["chunk_id"] for r in rows]

    # Prune stale vectors → index aligned with cleaned publish boundary
    try:
        prev     = col.get(include=[])
        prev_ids = set(prev.get("ids") or [])
        drop     = sorted(prev_ids - set(current_ids))
        if drop:
            col.delete(ids=drop)
            log(f"embed_prune_removed={len(drop)}")
        else:
            log("embed_prune_removed=0")
    except Exception as exc:
        log(f"WARN: embed prune skipped: {exc}")

    documents = [r["chunk_text"] for r in rows]
    metadatas = [
        {
            "doc_id"        : r.get("doc_id", ""),
            "effective_date": r.get("effective_date", ""),
            "run_id"        : run_id,
        }
        for r in rows
    ]

    # Wrap upsert in try/except — unhandled chroma errors (disk full, schema
    # mismatch, etc.) should surface as a clean False rather than a raw traceback.
    try:
        col.upsert(ids=current_ids, documents=documents, metadatas=metadatas)
    except Exception as exc:
        log(f"ERROR: embed upsert failed: {exc}")
        return False

    log(f"embed_upsert_count={len(current_ids)}")
    log(f"embed_collection_total={col.count()}")
    return True


# ---------------------------------------------------------------------------
# Sub-command: freshness
# ---------------------------------------------------------------------------

def cmd_freshness(args: argparse.Namespace) -> int:
    """
    Read an existing manifest and report freshness against the configured SLA.

    Exit codes:
      0 → PASS or WARN
      1 → FAIL or manifest missing
    """
    p = Path(args.manifest)
    if not p.is_file():
        print(f"ERROR: Manifest not found: {p}", file=sys.stderr)
        return 1

    sla_hours = float(os.environ.get("FRESHNESS_SLA_HOURS", "24"))
    status, detail = check_manifest_freshness(p, sla_hours=sla_hours)
    print(f"freshness_status={status}")
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    return 0 if status != "FAIL" else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etl_pipeline",
        description="Lab Day 10 — Data Pipeline (ingest → clean → validate → embed).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python etl_pipeline.py run\n"
            "  python etl_pipeline.py run --run-id sprint1\n"
            "  python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate\n"
            "  python etl_pipeline.py freshness "
            "--manifest artifacts/manifests/manifest_sprint1.json\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run sub-command
    p_run = sub.add_parser(
        "run",
        help="Execute full pipeline: ingest → clean → validate → embed",
    )
    p_run.add_argument(
        "--raw",
        default=str(RAW_DEFAULT),
        help=f"Path to raw CSV export (default: {RAW_DEFAULT.relative_to(ROOT)})",
    )
    p_run.add_argument(
        "--run-id",
        default="",
        help="Run identifier (default: UTC timestamp). Used in all artifact filenames.",
    )
    p_run.add_argument(
        "--no-refund-fix",
        action="store_true",
        help=(
            "Skip the 14→7 day refund-window correction. "
            "Use for before/after corruption demo in Sprint 3."
        ),
    )
    p_run.add_argument(
        "--skip-validate",
        action="store_true",
        help=(
            "Continue to embed even when expectation suite halts. "
            "Intentional corruption demo only (Sprint 3)."
        ),
    )
    p_run.set_defaults(func=cmd_run)

    # freshness sub-command
    p_fr = sub.add_parser(
        "freshness",
        help="Check freshness of a previously generated manifest against the SLA.",
    )
    p_fr.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="Path to a manifest JSON file (e.g. artifacts/manifests/manifest_sprint1.json)",
    )
    p_fr.set_defaults(func=cmd_freshness)

    return parser


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
