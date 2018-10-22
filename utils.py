import copy
from datetime import datetime
from functools import wraps, update_wrapper
from hashlib import blake2b
import logging
from math import log
import os
from subprocess import Popen, PIPE
import uuid

import pymysql


main_cursor = None
HOST = "dodb"
conn = None
CURDIR = os.getcwd()

LOG = logging.getLogger(__name__)

IntegrityError = pymysql.err.IntegrityError


def runproc(cmd):
    proc = Popen([cmd], shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE,
            close_fds=True)
    stdout_text, stderr_text = proc.communicate()
    return stdout_text, stderr_text


def _parse_creds():
    fpath = os.path.join(CURDIR, ".dbcreds")
    with open(fpath) as ff:
        lines = ff.read().splitlines()
    ret = {}
    for ln in lines:
        key, val = ln.split("=")
        ret[key] = val
    return ret


def connect():
    cls = pymysql.cursors.DictCursor
    creds = _parse_creds()
    ret = pymysql.connect(host=HOST, user=creds["DB_USERNAME"],
            passwd=creds["DB_PWD"], db=creds["DB_NAME"], charset="utf8",
            cursorclass=cls)
    return ret


def gen_uuid():
    return str(uuid.uuid4())


def get_cursor():
    global conn, main_cursor
    if not (conn and conn.open):
        LOG.debug("No DB connection")
        main_cursor = None
        conn = connect()
    if not main_cursor:
        LOG.debug("No cursor")
        main_cursor = conn.cursor(pymysql.cursors.DictCursor)
    return main_cursor


def commit():
    conn.commit()


def debugout(*args):
    with open("/tmp/debugout", "a") as ff:
        ff.write("YO!")
    argtxt = [str(arg) for arg in args]
    msg = "  ".join(argtxt) + "\n"
    with open("/tmp/debugout", "a") as ff:
        ff.write(msg)


def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Last-Modified"] = datetime.now()
        response.headers["Cache-Control"] = "no-store, no-cache, " \
                "must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
        return response
    return update_wrapper(no_cache, view)


def human_fmt(num):
    """Human friendly file size"""
    # Make sure that we get a valid input. If an invalid value is passed, we
    # want the exception to be raised.
    num = int(num)
    units = list(zip(["bytes", "K", "MB", "GB", "TB", "PB"],
            [0, 0, 1, 2, 2, 2]))
    if num > 1:
        exponent = min(int(log(num, 1024)), len(units) - 1)
        quotient = float(num) / 1024**exponent
        unit, num_decimals = units[exponent]
        format_string = "{:.%sf} {}" % (num_decimals)
        return format_string.format(quotient, unit)
    if num == 0:
        return "0 bytes"
    if num == 1:
        return "1 byte"


def gen_key(orig_rec, digest_size=8):
    """Generates a hash value by concatenating the values in the dictionary."""
    # Don't modify the original dict
    rec = copy.deepcopy(orig_rec)
    # Remove the 'id' field, if present
    rec.pop("id", None)
    m = blake2b(digest_size=digest_size)
    txt_vals = ["%s" % val for val in rec.values()]
    txt_vals.sort()
    txt = "".join(txt_vals)
    m.update(txt.encode("utf-8"))
    return m.hexdigest()
