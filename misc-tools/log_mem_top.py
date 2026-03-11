#!/usr/bin/env python3
# Logs memory (free -h) every 10 seconds. Keeps only the 100 snapshots
# with the highest "used" memory. Writes to free_log.txt in this directory.

import subprocess
import time
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "free_log.txt"
MAX_ENTRIES = 100
INTERVAL = 10


def get_memory_snapshot():
    used_bytes = None
    try:
        out = subprocess.run(
            ["free", "-b"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        for line in out.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                if len(parts) >= 3:
                    used_bytes = int(parts[2])
                break
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        pass
    out_h = subprocess.run(
        ["free", "-h"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return used_bytes or 0, out_h.stdout.rstrip()


def main():
    entries = []
    while True:
        used, free_h = get_memory_snapshot()
        ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        entries.append((used, ts, free_h))
        entries.sort(key=lambda x: -x[0])
        entries = entries[:MAX_ENTRIES]
        with open(LOG_FILE, "w") as f:
            for used, ts, free_h in entries:
                f.write("=== %s (used %d bytes) ===\n" % (ts, used))
                f.write("%s\n\n" % free_h)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
