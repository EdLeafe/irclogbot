import os
import sys
import time

MAX_INTERVAL = 180
TEST_FILE = "/ALIVE"

def nope(msg):
    print("NOPE", msg)
    sys.exit(1)

if not os.path.exists(TEST_FILE):
    nope("- doesn't exist")
mtime = os.stat(TEST_FILE).st_mtime
if time.time() - mtime > MAX_INTERVAL:
    nope("- too old")
print("health check OK")
