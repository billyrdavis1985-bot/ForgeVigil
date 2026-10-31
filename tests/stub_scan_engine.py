"""Stub scan engine for tests only. Behavior comes from STUB_SCAN_MODE.

Modes: clean, threat, fail_hr, exit2_bare, exit0_bare, crash, noisy, sleep.
Argv is echoed as JSON to $STUB_SCAN_ARGV_LOG when set, so tests can pin the
exact fixed argument tail without a shell.
"""
import json
import os
import sys
import time

MODES = {
    # Observed Windows shape: markers, exit status.
    "clean": (0, "Scan starting...\nScan finished.\nScanning X found no threats.\n"),
    "threat": (2, "Scan starting...\nThreat detected: EICAR-Test-File in X\nScan finished.\n"),
    "fail_hr": (2, "Scan starting...\nCmdTool: Failed with hr = 0x80508023.\n"),
    "exit2_bare": (2, "Scan starting...\nScan finished.\n"),
    "exit0_bare": (0, "Scan starting...\nScan finished.\n"),
    "crash": (1, "traceback: boom\n"),
    "noisy": (0, "Scan starting...\nfound no threats\n" + ("filler line padding to overflow capture\n" * 8000)),
}

mode = os.environ.get("STUB_SCAN_MODE", "clean")
log = os.environ.get("STUB_SCAN_ARGV_LOG")
if log:
    with open(log, "w", encoding="ascii") as handle:
        json.dump(sys.argv, handle)
if mode in ("tamper", "vanish"):
    target = sys.argv[sys.argv.index("-File") + 1]
    if mode == "tamper":
        with open(target, "ab") as handle:
            handle.write(b"tampered-during-scan")
    else:
        os.unlink(target)
    sys.stdout.write("Scan starting...\nScan finished.\nScanning X found no threats.\n")
    sys.exit(0)
if mode == "sleep":
    time.sleep(float(os.environ.get("STUB_SCAN_SLEEP_S", "30")))
    sys.stdout.write("Scan finished.\n found no threats\n")
    sys.exit(0)
code, text = MODES[mode]
sys.stdout.write(text)
sys.exit(code)
