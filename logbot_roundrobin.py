import argparse
from configparser import ConfigParser
import datetime as dt
from multiprocessing import Pipe
from multiprocessing import Pool
from multiprocessing import Process
from multiprocessing import Queue
import os
import re
import socket
import smtplib
import time

from elasticsearch import Elasticsearch
from twilio.rest import Client

import utils
from utils import logit as logit

HOMEDIR = utils.HOMEDIR

cp = ConfigParser()
cred_file = os.path.join(HOMEDIR, ".irccreds")
with open(cred_file) as ff:
    cp.read_file(ff)
PASSWD = cp.get("default", "password")
HOST = cp.get("default", "host")
es_client = Elasticsearch(host=HOST)
MAX_RETRIES = 5
SMS_USER = cp.get("sms", "user")
SMS_PASSWORD = cp.get("sms", "password")
SMS_FROM_ADDRESS = cp.get("sms", "from_address")
SMS_TO_ADDRESS = cp.get("sms", "to_address")

MSG_PAT = re.compile(r":([^!]+)!~?([^@]+)@(\S+) PRIVMSG (\S+) :(.+)")
SERVER = "chat.freenode.net"
#SERVER = "204.225.96.251"
IRC_NICK_BASE = "irclogbot_"
ALT_NICK_BASE = "altlogbot_"
CHANNELS_PER_BOT = 40
PAUSE_BETWEEN_JOINS = 3
HEARTBEAT_FILE_BASE = os.path.join(HOMEDIR, "heartbeats", "%s_ALIVE_%s")

process_pids = []


def heartbeat(bot):
    cmd = "touch %s" % bot.heartbeat_file
    os.system(cmd)
    logit("HEARTBEAT!!", cmd, force=True)


def record(nick, channel, remark, tm, force=False):
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%S")
    body = {"channel": channel, "nick": nick, "posted": tmstr,
            "remark": remark}
    # Leave the time out of the hash, as two bots could differ on when they saw
    # a posting, and generate different IDs, which would result in duplicate
    # postings.
    hash_body = {"channel": channel, "nick": nick, "remark": remark}
    hashval = utils.gen_key(hash_body)
    body["id"] = hashval
    attempts = 0
    while True:
        try:
            logit("RECORDING", body, "ID =", hashval, force=True)
            es_client.index(index="irclog", doc_type="irc", id=hashval,
                    body=body)
            break
        except Exception as e:
            attempts += 1
            if attempts >= MAX_RETRIES:
                logit("Elasticsearch exception: %s" % e, force=True)
                break


def notify_me(nick, channel, remark, tm):
    client = Client(SMS_USER, SMS_PASSWORD)
    msg = """
'{nick}' mentioned you in {channel} at {tm}
"{remark}" """.format(nick=nick, channel=channel, tm=tm, remark=remark).strip()
    message = client.messages.create(body=msg, from_=SMS_FROM_ADDRESS,
            to=SMS_TO_ADDRESS)


def join_channels(bot, queue):
    while True:
        chan = queue.get()
        if not chan:
            break
        bot.join_chan(chan)


def connect_bot(bot):
    bot.connect()


def runbot(bot):
    bot.run()


class LogBot():
    def __init__(self, nick_base, num, verbose=False):
        self.num = num
        self.verbose = verbose
        self.nick = "%s%s" % (nick_base, num)
        self.heartbeat_file = HEARTBEAT_FILE_BASE % (nick_base[:3], num)
        self.channels = []
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        super(LogBot, self).__init__()


    def start(self):
        heartbeat(self)
        connect()
        join()
        listen()


    def connect(self):
        logit("Connecting socket to", SERVER, force=self.verbose)
        self.ircsock.connect((SERVER, 6667))
        logit("Connected to %s!" % SERVER, force=self.verbose)
        # We are basically filling out a form with this line and saying to set
        # all the fields to the bot nickname.
        msg = "USER %s %s %s %s\n" % (self.nick, self.nick, self.nick,
                self.nick)
        self.ircsock.send(bytes(msg, "UTF-8"))
        # assign the nick to the bot
        msg = "NICK %s\n" % self.nick
        self.ircsock.send(bytes(msg, "UTF-8"))
        logit("NICK sent", msg, force=self.verbose)
        self.wait_for("NickServ identify <password>")
        # Send the nick password to the nick server
        msg = "PRIVMSG NickServ :IDENTIFY %s\n" % PASSWD
        self.ircsock.send(bytes(msg, "UTF-8"))
        logit("PASSWD sent", force=self.verbose)
        self.wait_for("You are now identified")

        logit(self.nick[-1] * 88, force=True)
        logit("And away we go!!!!", force=self.verbose)
        logit(self.nick[-1] * 88, force=self.verbose)
        heartbeat(self)


    def run(self):
        while True:
            raw_ircmsg = self.ircsock.recv(2048)
            try:
                ircmsg = raw_ircmsg.decode("UTF-8")
            except UnicodeDecodeError as e:
                logit("Received non-UTF8 encoded message: '%s'" % raw_ircmsg,
                        force=True)
            ircmsg = ircmsg.strip(" \n\r")
            self.process_msg(ircmsg)


    def process_msg(self, ircmsg):
        if not ircmsg:
            return
        # This can be useful for debugging
        is_ping = self.verbose or "PING :" in ircmsg
        logit(self.nick, ircmsg, force=is_ping)
        if "PING :" in ircmsg:
            self.ping()
            return
        mtch = MSG_PAT.match(ircmsg)
        if mtch:
            groups = mtch.groups()
            nick = groups[0]
            channel = groups[3]
            remark = groups[4]
            if remark.startswith("ACTION "):
                remark = remark.replace("ACTION ", "/me ")
            if len(nick) >= 17:
                logit("Odd nick: %s" % nick, force=True)
                return
            tm = dt.datetime.utcnow().replace(microsecond=0)
            record(nick, channel, remark, tm, force=self.verbose)
            if "edleafe" in remark:
                notify_me(nick, channel, remark, tm)


    def wait_for(self, txt):
        """Waits for the server to send a message containing the requested
        text. 'txt' can be a list of strings, or a single string.
        """
        if not isinstance(txt, (list, tuple)):
            txt = [txt]
        while True:
            ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            ircmsg = ircmsg.strip("\n\r")
            if any(word in ircmsg for word in txt):
                logit(ircmsg, "FOUND", *txt, force=self.verbose)
                return
            self.process_msg(ircmsg)


    def pause(self, seconds):
        start = dt.datetime.utcnow()
        end = start + dt.timedelta(seconds=seconds)
        curr_timeout = self.ircsock.gettimeout()
        self.ircsock.settimeout(0.5)
        nowtime = dt.datetime.utcnow()
        while nowtime < end:
            try:
                ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            except socket.timeout:
                ircmsg = ""
                time.sleep(0.1)
            ircmsg = ircmsg.strip("\n\r")
            self.process_msg(ircmsg)
            nowtime = dt.datetime.utcnow()
        self.ircsock.settimeout(curr_timeout)


    def join_chan(self, chan):
        logit("-" * 88, force=True)
        logit("JOINING", chan, force=True)
        self.ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
        # See if this makes the IRC server happier about flooding it with
        # requests...
        self.pause(PAUSE_BETWEEN_JOINS)
        logit("!!!!!JOINED", chan, force=True)
        heartbeat(self)


    def ping(self): # respond to server Pings.
        self.ircsock.send(bytes("PONG :pingis\n", "UTF-8"))
        logit("PONG!", force=self.verbose)
        heartbeat(self)


    def sendmsg(self, msg, target):
        """Sends messages to the target."""
        self.ircsock.send(bytes("PRIVMSG %s :%s\r\n" % (target, msg), "UTF-8"))


def main():
    parser = argparse.ArgumentParser(description="IRC Bot")
    nick_choices = ["irc", "alt"]
    parser.add_argument("--nick-base", "-n", choices=nick_choices,
            help="The base name for the nick to be used by the "
            "bots; options are either 'irc' or 'alt'.")
    parser.add_argument("--channel-file", "-f", help="The path of the file "
            "containing the names of the channels to join, one per line.")
    parser.add_argument("--verbose", "-v", action="store_true",
            help="Enables verbose output.")
    args = parser.parse_args()
    if args.verbose:
        utils.LOG.level = utils.logging.DEBUG
    nick_base = IRC_NICK_BASE
    if args.nick_base and args.nick_base.lower() == "alt":
        nick_base = ALT_NICK_BASE

    # Create a pool of channels for the bots to pick from
    channel_queue = Queue()
    if args.channel_file:
        with open(args.channel_file) as ff:
            chan_lines = ff.read().splitlines()
        [channel_queue.put(chan.strip()) for chan in chan_lines]
    else:
        print("You must specify a channel file")
        exit(1)
    # Add flags for the bots to know the queue is empty
    for i in range(4):
        channel_queue.put(None)
    # We need four bots to cover all the channels
    bots = []
    procs = []
    for num in range(4):
        bot = LogBot(nick_base, num, args.verbose)
        logit("NICK:", bot.nick, force=True)
        bots.append(bot)
        proc = Process(target=connect_bot, args=(bot,))
        procs.append(proc)
        proc.start()
    for p in procs:
        p.join()

    procs = []
    for bot in bots:
        proc = Process(target=join_channels, args=(bot, channel_queue),
                daemon=False)
        proc.start()
        procs.append(proc)
    [p.join() for p in procs]
    logit("All channels joined for %s bot." % args.nick_base, force=True)

    procs = []
    for bot in bots:
        proc = Process(target=runbot, args=(bot,))
        proc.start()
        procs.append(proc)
        process_pids.append(proc.pid)
    [p.join() for p in procs]


if __name__ == "__main__":
    main()
