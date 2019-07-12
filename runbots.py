#!/usr/bin/python3

import logging
from logging.handlers import SysLogHandler
import os
import signal
import subprocess
import time

import irclogbot
import utils

HOMEDIR = utils.HOMEDIR
ALIVE_FILE_BASE = os.path.join(HOMEDIR, "heartbeats", "ALIVE_%s")
ALIVE_SECONDS = 150
bot_pids = [None, None, None, None]

LOG = logging.getLogger(__name__)
handler = SysLogHandler(address='/dev/log', facility=SysLogHandler.LOG_DAEMON)
LOG.addHandler(handler)
LOG.setLevel(logging.INFO)


def run(num):
    str_num = str(num)
    cmd = ["python3", "/home/ed/projects/irclogbot/irclogbot.py", "-f",
            "/home/ed/projects/irclogbot/channels.txt", "-s", str_num]
    verbose = os.path.exists(os.path.join(HOMEDIR, "VERBOSE"))
    if verbose:
        cmd.append("-v")
    LOG.info("CMD: %s" % cmd)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    LOG.info("Bot started with PID: %s" % proc.pid)
    bot_pids[num] = proc.pid


def is_alive(num):
    # First check the pid
    pid = bot_pids[num]
    if pid:
        try:
            os.kill(pid, 0)
            LOG.info("PID %s found for bot %s" % (pid, num))
        except (OSError, ProcessLookupError):
            # The process isn't running
            LOG.info("Process for bot %s (PID=%s) isn't running" % (num, pid))
            return False
    pth = ALIVE_FILE_BASE % num
    if not os.path.exists(pth):
        return False
    val = os.stat(pth)
    time_since_heartbeat = (time.time() - val.st_mtime)
    LOG.info("Last heartbeat for bot %s was %s seconds ago" %
            (num, time_since_heartbeat))
    return time_since_heartbeat < ALIVE_SECONDS


def kill(num):
    try:
        pid = bot_pids[num]
    except IndexError:
        pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def heartbeat():
    os.system("touch /home/ed/projects/irclogbot/heartbeats/runbot")


def main():
    while True:
        for num in range(4):
            if is_alive(num):
                continue
            LOG.info("Bot %s is not alive; restarting" % num)
            kill(num)
            run(num)
        time.sleep(20)
        heartbeat()


if __name__ == "__main__":
    heartbeat()
    main()
