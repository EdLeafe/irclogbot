import glob
import os
import sys
import time

os.chdir("/home/ed/projects/irclogbot/")

import utils

utils.logit("KEEPALIVE STARTING UP", force=True)
STARTUP_INTERVAL = 600
MAX_INTERVAL = 180
CHECK_INTERVAL = 120
ALIVE_PATH = os.path.join(utils.HOMEDIR, "heartbeats", "*")

while True:
    rightnow = time.time()
    utils.logit(f"KEEPALIVE CHECKING AT {rightnow}", force=True)
    beats = glob.glob(ALIVE_PATH)
    for beat in beats:
        fname = os.path.basename(beat)
        mtime = os.stat(beat).st_mtime
        duration = rightnow - mtime
        utils.logit(f"DURATION: {duration} - {fname}")
        if duration > MAX_INTERVAL:
            prefix = fname[:3]
            utils.logit("KEEPALIVE DAEMON:", f"No heartbeat for {duration} "
                    f"seconds; restarting the {prefix} bots", force=True)
            utils.runproc(f"./restart.sh {prefix}", wait=False)
            break
        else:
            utils.logit(f"HEARTBEAT: {fname} {duration}", force=True)
    utils.logit("KEEPALIVE sleeeeeeeping...", force=True)
    time.sleep(CHECK_INTERVAL)
