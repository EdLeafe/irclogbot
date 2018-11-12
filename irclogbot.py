import argparse
from configparser import ConfigParser
import datetime as dt
import os
import re
import socket
import time

from elasticsearch import Elasticsearch

import utils


cp = ConfigParser()
with open(".irccreds") as ff:
    cp.read_file(ff)
PASSWD = cp.get("default", "password")
HOST = cp.get("default", "host")
es_client = Elasticsearch(host=HOST)

MSG_PAT = re.compile(r":([^!]+)!~([^@]+)@(\S+) PRIVMSG (\S+) :(.+)")
#SERVER = "chat.freenode.net"
SERVER = "204.225.96.251"
NICK_BASE = "irclogbot_"
CHANNELS_PER_BOT = 40
PAUSE_BETWEEN_JOINS = 5
HEARTBEAT_FILE = "/ALIVE"


def heartbeat():
    cmd = "touch %s" % HEARTBEAT_FILE
    os.system(cmd)


def record(nick, channel, remark):
    tm = dt.datetime.utcnow().replace(microsecond=0)
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%S")
    doc = {"channel": channel, "nick": nick, "posted": tmstr, "remark": remark}
    hashval = utils.gen_key(doc)
    doc["id"] = hashval
    try:
        es_client.index(index="irclog", doc_type="irc", body=doc)
#        print("RECORDING", doc)
    except Exception as e:
        print("Elasticsearch exception: %s" % e)


class IRCLogBot():
    def __init__(self, nick, channels, verbose=False):
        self.nick = nick
        self.channels = channels
        self.verbose = verbose
        super(IRCLogBot, self).__init__()


    def logit(self, *msgs, force=False):
        if force or self.verbose:
            print(*msgs)


    def run(self):
        self.logit("Running...")
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logit("Connecting socket to", SERVER)
        self.ircsock.connect((SERVER, 6667))
        self.logit("Connected to %s!" % SERVER)
        # We are basically filling out a form with this line and saying to set
        # all the fields to the bot nickname.
        msg = "USER %s %s %s %s\n" % (self.nick, self.nick, self.nick,
                self.nick)
        self.ircsock.send(bytes(msg, "UTF-8"))
        # assign the nick to the bot
        msg = "NICK %s\n" % self.nick
        self.ircsock.send(bytes(msg, "UTF-8"))
        self.logit("NICK sent", msg)
        self.wait_for("NickServ identify <password>")
        # Send the nick password to the nick server
        msg = "PRIVMSG NickServ :IDENTIFY %s\n" % PASSWD
        self.ircsock.send(bytes(msg, "UTF-8"))
        self.logit("PASSWD sent")
        self.wait_for("You are now identified")

        for chan in self.channels:
            self.joinchan(chan)

        self.logit("@" * 88)
        self.logit("And away we go!!!!")
        self.logit("@" * 88)
        heartbeat()
        while True:
            ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            ircmsg = ircmsg.strip(" \n\r")
            self.process_msg(ircmsg)


    def process_msg(self, ircmsg):
        if not ircmsg:
            return
        # This can be useful for debugging
        is_ping = "PING :" in ircmsg
        self.logit(dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ircmsg,
                force=is_ping)
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
                print("Odd nick: %s" % nick)
                return
            record(nick, channel, remark)


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
                self.logit(ircmsg, "FOUND", *txt)
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
        self.logit("-" * 88)
        self.logit("JOINING", chan, "AT", dt.datetime.utcnow(), force=True)
        self.ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
        # See if this makes the IRC server happier about flooding it with
        # requests...
        self.pause(PAUSE_BETWEEN_JOINS)
        self.logit("!!!!!JOINED", chan, "AT", dt.datetime.utcnow(),
                force=True)


    def ping(self): # respond to server Pings.
        self.ircsock.send(bytes("PONG :pingis\n", "UTF-8"))
        self.logit("PONG!")
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
        islice = 0
    if not channels:
        print("You must specify at least one channel")
        exit(1)
    nick = "%s%s" % (NICK_BASE, islice)
    bot = IRCLogBot(nick, channels, verbose=args.verbose)
    if args.verbose:
        print("NICK:", nick)
    # Start it!
    bot.run()


if __name__ == "__main__":
    main()
