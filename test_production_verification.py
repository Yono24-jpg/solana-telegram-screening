import tempfile
import unittest
from pathlib import Path
from production_verification import SCANNER_FILES, code_fingerprint, update_checkpoint

REPO="Yono24-jpg/solana-telegram-screening"
FINGERPRINT="a"*64
SHA="f"*40

def make_run(run_id=1,**updates):
    run={"id":run_id,"run_number":run_id,"run_attempt":1,"event":"workflow_dispatch",
         "head_branch":"main","head_sha":SHA,"head_repository":{"full_name":REPO},
         "created_at":"2026-11-18T00:05:00Z","conclusion":"success"}
    run.update(updates);return run

def make_report(run_id=1,**updates):
    report={"run_id":str(run_id),"version":"5.4","mode":"ALERT ONLY","health":"degraded",
            "seen":100,"sent":0,
            "data_recovery":{"coverage_pct":25.5,"young_complete":20,"young_total":100},
            "market_hydration":{"incomplete_after":75,"sources":{"gecko_pools":{
                "attempts":4,"successes":3,"status_counts":{"ok":3,"http_429":1}}}},
            "social_discovery":{"status":"sampled","details":{"trend":{
                "search_status":"authentication_required_or_forbidden"}}},
            "provider_access":{"x":{"reads_enabled":False}},"narrative":{"trend_count":60}}
    report.update(updates);return report

class CheckpointTests(unittest.TestCase):
    def test_code_fingerprint_stable_and_changes_with_scanner_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i,name in enumerate(SCANNER_FILES):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(f"source-{i}".encode())
            first=code_fingerprint(root)
            self.assertEqual(first,code_fingerprint(root))
            (root/SCANNER_FILES[0]).write_bytes(b"changed")
            self.assertNotEqual(first,code_fingerprint(root))

    def test_records_main_run_with_bounded_evidence_and_x_off(self):
        cp,changed,reason=update_checkpoint(None,make_run(),make_report(),REPO,FINGERPRINT)
        self.assertTrue(changed);self.assertEqual(reason,"recorded");self.assertEqual(cp["consecutive_successes"],1)
        row=cp["successful_runs"][0]
        self.assertEqual(row["coverage_pct"],25.5);self.assertEqual(row["gecko_status_counts"],{"ok":3,"http_429":1})
        self.assertFalse(row["x_reads_enabled"]);self.assertEqual(row["mode"],"ALERT ONLY")
        self.assertNotIn("token"," ".join(row.keys()).lower())

    def test_duplicate_run_never_counts_twice(self):
        cp,_,_=update_checkpoint(None,make_run(7),make_report(7),REPO,FINGERPRINT)
        same,changed,reason=update_checkpoint(cp,make_run(7),make_report(7),REPO,FINGERPRINT)
        self.assertFalse(changed);self.assertEqual(reason,"duplicate_run");self.assertEqual(same["consecutive_successes"],1)

    def test_non_main_or_untrusted_run_is_ignored(self):
        for run in (make_run(2,head_branch="feature/x"),make_run(3,event="pull_request"),
                    make_run(4,head_repository={"full_name":"attacker/repo"})):
            with self.subTest(run=run):
                cp,changed,reason=update_checkpoint(None,run,make_report(run["id"]),REPO,FINGERPRINT)
                self.assertIsNone(cp);self.assertFalse(changed);self.assertEqual(reason,"run_not_eligible")

    def test_failed_run_and_missing_report_do_not_count_and_reset_streak(self):
        cp,_,_=update_checkpoint(None,make_run(1),make_report(1),REPO,FINGERPRINT)
        failed,changed,reason=update_checkpoint(cp,make_run(2,conclusion="failure"),make_report(2),REPO,FINGERPRINT)
        self.assertTrue(changed);self.assertEqual(reason,"workflow_not_success");self.assertEqual(failed["consecutive_successes"],0)
        missing,_,reason=update_checkpoint(failed,make_run(3),None,REPO,FINGERPRINT)
        self.assertEqual(reason,"report_missing");self.assertEqual(missing["consecutive_successes"],0)
        self.assertEqual(len(missing["failed_runs"]),2)

    def test_report_must_match_run_and_alert_only_mode(self):
        for report,reason in ((make_report(99),"report_run_id_mismatch"),(make_report(1,mode="TRADING"),"unexpected_mode")):
            cp,changed,got=update_checkpoint(None,make_run(1),report,REPO,FINGERPRINT)
            self.assertTrue(changed);self.assertEqual(got,reason);self.assertEqual(cp["consecutive_successes"],0)

    def test_fingerprint_change_starts_new_verification_window(self):
        old,_,_=update_checkpoint(None,make_run(1),make_report(1),REPO,FINGERPRINT)
        new,changed,reason=update_checkpoint(old,make_run(2),make_report(2),REPO,"b"*64)
        self.assertTrue(changed);self.assertEqual(reason,"recorded");self.assertEqual(new["scanner_fingerprint"],"b"*64)
        self.assertEqual(new["scanner_source_sha"],SHA);self.assertEqual(new["consecutive_successes"],1)
        self.assertEqual(len(new["successful_runs"]),1)

    def test_twelve_consecutive_successes_mark_checkpoint_complete(self):
        cp=None
        for run_id in range(1,13):
            cp,changed,reason=update_checkpoint(cp,make_run(run_id),make_report(run_id),REPO,FINGERPRINT)
            self.assertTrue(changed);self.assertEqual(reason,"recorded")
        self.assertEqual(cp["status"],"verified_12_consecutive_runs");self.assertEqual(cp["consecutive_successes"],12)

if __name__=="__main__": unittest.main()
