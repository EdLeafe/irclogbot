import argparse
from configparser import ConfigParser
import datetime as dt
import os
import re
import socket
import time

from elasticsearch import Elasticsearch

import utils

HOMEDIR = utils.HOMEDIR

cp = ConfigParser()
cred_file = os.path.join(HOMEDIR, ".irccreds")
with open(cred_file) as ff:
    cp.read_file(ff)
PASSWD = cp.get("default", "password")
HOST = cp.get("default", "host")
es_client = Elasticsearch(host=HOST)
MAX_RETRIES = 5

MSG_PAT = re.compile(r":([^!]+)!~?([^@]+)@(\S+) PRIVMSG (\S+) :(.+)")
SERVER = "chat.freenode.net"
#SERVER = "204.225.96.251"
NICK_BASE = "irclogbot_"
CHANNELS_PER_BOT = 40
PAUSE_BETWEEN_JOINS = 3
HEARTBEAT_FILE_BASE = os.path.join(HOMEDIR, "heartbeats", "ALIVE_%s")
# This will get set when the nick suffix is chosen
heartbeat_file = None


def heartbeat():
    cmd = "touch %s" % heartbeat_file
    os.system(cmd)


def record(nick, channel, remark, force=False):
    tm = dt.datetime.utcnow().replace(microsecond=0)
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%S")
    body = {"channel": channel, "nick": nick, "posted": tmstr, "remark": remark}
    hashval = utils.gen_key(body)
    body["id"] = hashval
    attempts = 0
    while True:
        try:
            logit("RECORDING", body, "ID =", hashval, force=force)
            es_client.index(index="irclog", doc_type="irc", id=hashval,
                    body=body)
            break
        except Exception as e:
            logit("Encountered exception attempting to write to Elasticsearch",
                    e, force=True)
            attempts += 1
            if attempts >= MAX_RETRIES:
                logit("Elasticsearch exception: %s" % e, force=True)
                break


def logit(*msgs, force=False):
    tm = dt.datetime.utcnow().replace(microsecond=0)
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%S")
    log = utils.LOG
    mthd = log.info if force else log.debug
    msg_str = " ".join(["%s" % m for m in msgs])
    msg = tmstr + " " + msg_str
    mthd(msg)


class IRCLogBot():
    def __init__(self, nick, channels, verbose=False):
        self.nick = nick
        self.channels = channels
        self.verbose = verbose
        super(IRCLogBot, self).__init__()


    def run(self):
        heartbeat()
        logit("Running...", force=self.verbose)
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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

        for chan in self.channels:
            self.joinchan(chan)
            heartbeat()

        logit(self.nick[-1] * 88, force=True)
        logit("And away we go!!!!", force=self.verbose)
        logit(self.nick[-1] * 88, force=self.verbose)
        heartbeat()
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
            record(nick, channel, remark, force=self.verbose)


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


    def joinchan(self, chan):
        logit("-" * 88, force=True)
        logit("JOINING", chan, force=True)
        self.ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
        # See if this makes the IRC server happier about flooding it with
        # requests...
        self.pause(PAUSE_BETWEEN_JOINS)
        logit("!!!!!JOINED", chan, force=True)


    def ping(self): # respond to server Pings.
        self.ircsock.send(bytes("PONG :pingis\n", "UTF-8"))
        logit("PONG!", force=self.verbose)
        heartbeat()


    def sendmsg(self, msg, target):
        """Sends messages to the target."""
        self.ircsock.send(bytes("PRIVMSG %s :%s\r\n" % (target, msg), "UTF-8"))


def main():
    parser = argparse.ArgumentParser(description="IRC Bot")
    parser.add_argument("--channel-file", "-f", help="The path of the file "
            "containing the names of the channels to join, one per line.")
    parser.add_argument("--slice", "-s", help="When used with the channel "
            "file, takes a slice of CHANNELS_PER_BOT to join. Example: if "
            "`slice` == 3, it would start at (3 * CHANNELS_PER_BOT), and "
            "use the next CHANNELS_PER_BOT entries.")
    parser.add_argument("--channel", "-c", action="append",
            help="Channels for the bot to join. Can be specified multiple "
            "times to join multiple channels.")
    parser.add_argument("--verbose", "-v", action="store_true",
            help="Enables verbose output.")
    parser.add_argument("--botnum", "-n", help="Use this as the suffix for "
            "the bot's nick.")
    args = parser.parse_args()
    if args.channel_file:
        with open(args.channel_file) as ff:
            chan_lines = ff.read().splitlines()
        channels = [chan.strip() for chan in chan_lines]
        if args.slice:
            islice = int(args.slice)
            start = (CHANNELS_PER_BOT * islice)
            end = (CHANNELS_PER_BOT * (islice + 1))
            end = start + CHANNELS_PER_BOT
            channels = channels[start:end]
    else:
        channels = args.channel
        islice = args.botnum if args.botnum else 0
    if not channels:
        print("You must specify at least one channel")
        exit(1)
    global heartbeat_file
    heartbeat_file = HEARTBEAT_FILE_BASE % islice
    nick = "%s%s" % (NICK_BASE, islice)
    bot = IRCLogBot(nick, channels, verbose=args.verbose)
    if args.verbose:
        utils.LOG.level = utils.logging.DEBUG
        logit("NICK:", nick, force=True)
    # Start it!
    bot.run()


if __name__ == "__main__":
    main()
