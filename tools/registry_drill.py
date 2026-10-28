"""Exercise a configured registry on disposable, fixture-only local state.

    python tools/registry_drill.py

No state/output/assessor options. Reuses CP16's private workspace, credential
isolation, subprocess checks, server cleanup and zero-spend assertions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

sys.dont_write_bytecode = True
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.operator_drill import ALLOW_ID, DENY_ID, HELD_ID, MESSAGE, Drill, DrillFailure, _workspace
from forge_vigil.registry import export_snapshot, parse_registry
from forge_vigil.store import Store


class RegistryDrill(Drill):
    def command(self, *args: str) -> list[str]:
        command = super().command(*args)
        if args[0] == "serve":
            command += ["--authority", "registry"]
        return command

    def submit(self, port, journal, request_id, *, approval=True, document="bracket-public-r1",
               recipient="harborline-r1", message=MESSAGE, expected=0):
        args = ["submit", "--document", document, "--recipient", recipient, "--message", message,
                "--request-id", request_id, "--port", str(port), "--journal", journal]
        if approval:
            args += ["--approval", "APR-HARBORLINE-R1"]
        return self.cli(*args, expected=expected)

    def exercise(self) -> None:
        live = self.root/"live"
        live.mkdir(mode=0o700)
        db, journal, source = live/"state.sqlite3", live/"sent.jsonl", live/"registry.json"
        registry = parse_registry((REPO_ROOT/"examples/registry.example.json").read_bytes())
        export_snapshot(registry, source)
        self.cli("registry", "validate", "--file", source)
        self.cli("registry", "activate", "--file", source, "--db", db)
        self.check(Store(db, read_only=True).registry_state()[0].digest, registry.digest, "activated snapshot")
        self.passed("Validated and activated the fictional registry in fresh state")
        with self.server(db) as port:
            self.submit(port,journal,ALLOW_ID)
            self.submit(port,journal,HELD_ID,approval=False)
            self.submit(port,journal,DENY_ID,document="bracket-cost-r1",recipient="summit-r1")
            self.check_state(db,released=False)
            for request_id in (ALLOW_ID,HELD_ID,DENY_ID):
                receipt = self.show(db,request_id)["receipt"]
                self.check(receipt["authority"]["snapshot"],registry.digest,"receipt snapshot")
            self.passed("Recorded registry ALLOW, REVIEW and DENY with pinned authority")
            before = journal.read_bytes()
            self.check("(replayed)" in self.submit(port,journal,ALLOW_ID),True,"ALLOW replay")
            self.submit(port,journal,ALLOW_ID,message="Different synthetic request.",expected=1)
            self.check(journal.read_bytes(),before,"journal after replay/conflict")
            self.check_state(db,released=False)
            self.passed("Replay/conflict created no second delivery or journal entry")
            self.cli("registry","activate","--file",source,"--db",db,expected=2)
            self.passed("Activation refused while the server holds the database lock")
            self.cli("review","release",HELD_ID,"--db",db,"--reviewer","synthetic-drill-operator")
            self.check_state(db,released=True)
            self.check(self.show(db,HELD_ID)["review"]["binding_check"],"matched","release binding")
            self.passed("Local review released the original bound document and destination")
            cases, exported, result = self.root/"cases.json", self.root/"snapshot.json", self.root/"eval.json"
            self.cli("review","export",HELD_ID,"--db",db,"--from-journal","--journal",journal,"--out",cases)
            self.cli("registry","export","--db",db,"--snapshot",registry.digest,"--out",exported)
            self.cli("eval","--cases",cases,"--registry-file",exported,"--assessor","fixture","--json",result)
            summary = json.loads(result.read_text())["summary"]
            self.check((summary["registry_snapshot"],summary["critical"],summary["benign"]["correct"],summary["spend_usd"]),
                       (registry.digest,[],1,"0.00"),"registry fixture evaluation")
            self.passed("Exported a pinned case and evaluated it against its exact registry")
            backup_root = self.root/"backups"
            self.cli("backup","create","--db",db,"--journal",journal,"--to",backup_root)
            folders = list(backup_root.iterdir())
            self.check(len(folders),1,"one complete backup")
            backup = folders[0]
            self.cli("backup","verify",backup)
            manifest = json.loads((backup/"manifest.json").read_text())
            self.check((manifest["format"],manifest["counts"]["request_authority"]),("forgevigil.backup.v2",3),"backup authority")
            self.passed("Verified a complete registry backup while the server was running")
        source.unlink()
        restored = self.root/"restored"/"state.sqlite3"
        restored_journal = restored.parent/"sent.jsonl"
        self.cli("backup","restore",backup,"--db",restored,"--journal",restored_journal)
        with self.server(restored) as port:
            self.check("(replayed)" in self.submit(port,restored_journal,ALLOW_ID),True,"restored ALLOW replay")
            self.check("(replayed)" in self.submit(port,restored_journal,HELD_ID,approval=False),True,"restored review replay")
            self.check_state(restored,released=True)
        self.passed("Restored and replayed without the original configuration or another delivery")
        self.check(len(Store(restored,read_only=True).spend_entries()),0,"empty provider ledger")
        self.passed("Finished with zero model calls/spend and both servers stopped")


def run_drill(out: TextIO = sys.stdout) -> int:
    try:
        with _workspace() as root:
            RegistryDrill(root,out).exercise()
    except KeyboardInterrupt:
        print("RESULT: FAIL (cancelled)",file=out)
        return 130
    except Exception as exc:
        detail = str(exc) if isinstance(exc,DrillFailure) else type(exc).__name__
        print(f"RESULT: FAIL ({detail})",file=out)
        return 1
    print("RESULT: PASS",file=out)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    return run_drill()


if __name__ == "__main__":
    sys.exit(main())
