import argparse
from configparser import ConfigParser
import datetime as dt
import re
import socket

from elasticsearch import Elasticsearch

import utils


cp = ConfigParser()
with open(".irccreds") as ff:
    cp.read(ff)
PASSWD = cp.get("default", "password")
HOST = cp.get("default", "host")
es_client = Elasticsearch(host=HOST)

MSG_PAT = re.compile(r":([^!]+)!~([^@]+)@(\S+) PRIVMSG (\S+) :(.+)")
SERVER = "chat.freenode.net"
NICK_BASE = "irclogbot_"
CHANNELS_PER_BOT = 20


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
    def __init__(self, nick, channels):
        self.nick = nick
        self.channels = channels
        super(IRCLogBot, self).__init__()


    def run(self):
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ircsock.connect((SERVER, 6667))
        # We are basically filling out a form with this line and saying to set
        # all the fields to the bot nickname.
        msg = "USER %s %s %s %s\n" % (self.nick, self.nick, self.nick,
                self.nick)
        self.ircsock.send(bytes(msg, "UTF-8"))
        # assign the nick to the bot
        msg = "NICK %s\n" % self.nick
        self.ircsock.send(bytes(msg, "UTF-8"))
        self.wait_for("NickServ identify <password>")
        # Send the nick password to the nick server
        msg = "PRIVMSG NickServ :IDENTIFY %s\n" % PASSWD
        self.ircsock.send(bytes(msg, "UTF-8"))
        self.wait_for("You are now identified")

        print("#" * 88)
        for chan in self.channels:
            print(chan)
        print("#" * 88)

        for chan in self.channels:
            self.joinchan(chan)

        print("@" * 88)
        print("And away we go!!!!")
        print("@" * 88)
        while True:
            ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            ircmsg = ircmsg.strip(" \n\r")
            self.process_msg(ircmsg)


    def process_msg(self, ircmsg):
        if not ircmsg:
            return
        # This can be useful for debugging
        print(dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ircmsg)
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
                return
            self.process_msg(ircmsg)


    def joinchan(self, chan):
        print("-" * 88)
        print("JOINING", chan)
        self.ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
#        self.wait_for(["End of /NAMES list.", "Cannot join channel"])
        print("-" * 88)
        print("!!!!!JOINED", chan)


    def ping(self): # respond to server Pings.
        self.ircsock.send(bytes("PONG :pingis\n", "UTF-8"))
        print("PONG!")


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
    bot = IRCLogBot(nick, channels)
    print("NICK:", nick)
    # Start it!
    bot.run()

#    chan_count = len(channels)
#    if chan_count > 10 * CHANNELS_PER_BOT:
#        # Only have 10 bots registered
#        print("Too many channels: %s. Need to register more bots.")
#        exit()
#    thread_list = []
#    while channels:
#        bot_chans, channels = (channels[:CHANNELS_PER_BOT],
#                channels[CHANNELS_PER_BOT:])
#        nick = "%s%s" % (NICK_BASE, len(thread_list))
#        bot = IRCLogBot(nick, bot_chans)
#        thread_list.append(bot)
#        print(nick, len(bot_chans))
#    for thd in thread_list:
#        thd.start()
#    for thd in thread_list:
#        thd.join()


if __name__ == "__main__":
    main()
