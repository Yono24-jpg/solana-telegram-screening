"""Persist one bounded, evidence-based 12-run production verification checkpoint."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_SUCCESS_RUNS = 12
SCANNER_FILES = (
    ".github/workflows/screen.yml",
    "scanner_v5.py", "chain_intelligence.py", "filter_audit.py",
    "protocol_layouts_v54.json", "smart_discovery.py", "data_intelligence.py",
    "birdeye_standard.py", "global_intelligence.py", "social_intelligence.py",
    "hunter_modes.py", "hunter_memory.py", "token_extensions.py",
    "discovery_watchlist.json", "narrative_v3.py", "security_v3.py", "bot.py",
    "scanner_v2.py", "market_data.py", "vault_checks.py", "screening_rules.py",
    "evidence.py", "state_store.py", "persist_state.py", "signal_quality.py",
)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def code_fingerprint(root: str | Path, revision: str | None = None) -> str:
    """Hash only scanner-affecting sources, ignoring per-run state.json commits."""
    root = Path(root)
    digest = hashlib.sha256()
    for relative in SCANNER_FILES:
        if revision:
            result = subprocess.run(["git", "show", f"{revision}:{relative}"], cwd=root, check=False,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                raise ValueError("scanner_source_missing_from_revision")
            content = result.stdout
        else:
            path = root / relative
            if not path.is_file():
                raise ValueError("scanner_source_missing")
            content = path.read_bytes()
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(content); digest.update(b"\0")
    return digest.hexdigest()

def new_checkpoint(fingerprint: str, source_sha: str, started_at: str) -> dict[str, Any]:
    return {"schema_version":1,"target_successful_runs":TARGET_SUCCESS_RUNS,
            "scanner_fingerprint":fingerprint,"scanner_source_sha":source_sha,
            "tracking_started_at":started_at,"status":"monitoring","consecutive_successes":0,
            "successful_runs":[],"failed_runs":[],"updated_at":started_at}

def eligible_run(run: dict[str, Any], repository: str) -> bool:
    if not isinstance(run,dict) or run.get("event") not in ("push","workflow_dispatch"): return False
    if run.get("head_branch")!="main" or (run.get("head_repository") or {}).get("full_name")!=repository: return False
    return isinstance(run.get("id"),(int,str)) and str(run.get("id")).isdigit()

def _number(value: Any) -> int | float | None:
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) else None

def _cycle(run: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    hydration=report.get("market_hydration") or {}; sources=hydration.get("sources") or {}
    gecko=sources.get("gecko_pools") or {}; statuses=gecko.get("status_counts") or {}
    recovery=report.get("data_recovery") or {}; social=report.get("social_discovery") or {}
    x=((report.get("provider_access") or {}).get("x") or {})
    narrative=report.get("narrative") or {}
    trend_count=_number(narrative.get("trend_count"))
    if trend_count is None and isinstance(narrative.get("trends"),list): trend_count=len(narrative["trends"])
    return {
        "run_id":str(run["id"]),"run_number":run.get("run_number"),"run_attempt":run.get("run_attempt",1),
        "event":run.get("event"),"head_sha":run.get("head_sha"),"created_at":run.get("created_at"),
        "conclusion":run.get("conclusion"),"version":report.get("version"),"mode":report.get("mode"),
        "health":report.get("health"),"seen":_number(report.get("seen")),"sent":_number(report.get("sent")),
        "coverage_pct":_number(recovery.get("coverage_pct")),
        "young_complete":_number(recovery.get("young_complete")),"young_total":_number(recovery.get("young_total")),
        "gecko_attempts":_number(gecko.get("attempts")),"gecko_successes":_number(gecko.get("successes")),
        "gecko_status_counts":{str(k):int(v) for k,v in (statuses.items() if isinstance(statuses,dict) else [])
                               if isinstance(k,str) and isinstance(v,int) and not isinstance(v,bool) and v>=0},
        "incomplete_after":_number(hydration.get("incomplete_after")),
        "social_status":social.get("status"),
        "social_search_statuses":sorted({str(v.get("search_status")) for v in (social.get("details") or {}).values()
                                         if isinstance(v,dict) and v.get("search_status") is not None}),
        "narrative_trend_count":trend_count,
        "x_reads_enabled":x.get("reads_enabled") is True,
    }

def update_checkpoint(checkpoint: dict[str,Any] | None, run: dict[str,Any], report: dict[str,Any] | None,
                      repository: str, fingerprint: str) -> tuple[dict[str,Any] | None,bool,str]:
    """Accept only distinct main-branch runs whose report matches ALERT ONLY."""
    if not eligible_run(run,repository): return checkpoint,False,"run_not_eligible"
    run_id=str(run["id"])
    if checkpoint is None or checkpoint.get("scanner_fingerprint")!=fingerprint:
        checkpoint=new_checkpoint(fingerprint,str(run.get("head_sha") or ""),str(run.get("created_at") or utc_now()))
    known={str(row.get("run_id")) for key in ("successful_runs","failed_runs")
           for row in checkpoint.get(key,[]) if isinstance(row,dict)}
    if run_id in known: return checkpoint,False,"duplicate_run"
    if checkpoint.get("status")=="verified_12_consecutive_runs": return checkpoint,False,"already_complete"
    reason=None
    if run.get("conclusion")!="success": reason="workflow_not_success"
    elif not isinstance(report,dict): reason="report_missing"
    elif str(report.get("run_id"))!=run_id: reason="report_run_id_mismatch"
    elif report.get("mode")!="ALERT ONLY": reason="unexpected_mode"
    elif not isinstance(report.get("version"),str): reason="report_version_missing"
    if reason:
        checkpoint["failed_runs"]=(checkpoint.get("failed_runs") or [])+[{
            "run_id":run_id,"run_number":run.get("run_number"),"run_attempt":run.get("run_attempt",1),
            "event":run.get("event"),"head_sha":run.get("head_sha"),"created_at":run.get("created_at"),
            "conclusion":run.get("conclusion"),"reason":reason}]
        checkpoint["failed_runs"]=checkpoint["failed_runs"][-100:]
        checkpoint["consecutive_successes"]=0; checkpoint["status"]="monitoring"; checkpoint["updated_at"]=utc_now()
        return checkpoint,True,reason
    checkpoint["successful_runs"]=(checkpoint.get("successful_runs") or [])+[_cycle(run,report)]
    checkpoint["successful_runs"]=checkpoint["successful_runs"][-100:]
    checkpoint["consecutive_successes"]=int(checkpoint.get("consecutive_successes",0))+1
    checkpoint["updated_at"]=utc_now()
    checkpoint["status"]="verified_12_consecutive_runs" if checkpoint["consecutive_successes"]>=checkpoint["target_successful_runs"] else "monitoring"
    return checkpoint,True,"recorded"

def load_json(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: return None

def atomic_write_json(path: Path, value: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+"\n"
    fd,temporary=tempfile.mkstemp(prefix=path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass

def record_event(checkpoint_path: Path,event_path: Path,report_path: Path,repository: str,root: Path):
    event=load_json(event_path) or {}; run=event.get("workflow_run") or {}
    if not eligible_run(run,repository): return load_json(checkpoint_path),False,"run_not_eligible"
    report=load_json(report_path)
    fingerprint=code_fingerprint(root,str(run.get("head_sha") or ""))
    checkpoint,changed,reason=update_checkpoint(load_json(checkpoint_path),run,report,repository,fingerprint)
    if changed and checkpoint is not None: atomic_write_json(checkpoint_path,checkpoint)
    return checkpoint,changed,reason

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--event",type=Path,default=Path(os.environ.get("GITHUB_EVENT_PATH","event.json")))
    parser.add_argument("--report",type=Path,default=Path("/tmp/hunter-run-report/latest.json"))
    parser.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY",""))
    parser.add_argument("--root",type=Path,default=Path("."))
    parser.add_argument("--checkpoint",type=Path,default=Path("production_checkpoint.json"))
    args=parser.parse_args()
    if not args.repository: raise SystemExit("GITHUB_REPOSITORY is required")
    checkpoint,changed,reason=record_event(args.checkpoint,args.event,args.report,args.repository,args.root)
    summary={"changed":changed,"reason":reason,"status":checkpoint.get("status") if checkpoint else None,
             "consecutive_successes":checkpoint.get("consecutive_successes",0) if checkpoint else 0,
             "target":checkpoint.get("target_successful_runs",TARGET_SUCCESS_RUNS) if checkpoint else TARGET_SUCCESS_RUNS}
    print("PRODUCTION_CHECKPOINT "+json.dumps(summary,separators=(",",":")))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
