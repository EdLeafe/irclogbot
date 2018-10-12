import argparse
import datetime as dt
import re
import socket
import threading

from elasticsearch import Elasticsearch

import utils

HOST = "dodb"
es_client = Elasticsearch(host=HOST)

MSG_PAT = re.compile(r":([^!]+)!~([^@]+)@(\S+) PRIVMSG (\S+) :(.+)")
SERVER = "chat.freenode.net"
NICK_BASE = "irclogbot_"
CHANNELS_PER_BOT = 20
with open(".irccreds") as ff:
    PASSWD = ff.read().strip()


def record(nick, channel, remark):
    tm = dt.datetime.utcnow().replace(microsecond=0)
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"channel": channel, "nick": nick, "posted": tmstr, "remark": remark}
    hashval = utils.gen_key(doc)
    doc["id"] = hashval
    try:
        es_client.index(index="irclog", doc_type="irc", body=doc)
#        print("RECORDING", doc)
    except Exception as e:
        print("Elasticsearch exception: %s" % e)


class IRCLogBot(threading.Thread):
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

        for chan in self.channels:
            self.joinchan(chan)

        while True:
            ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            ircmsg = ircmsg.strip(" \n\r")
            if not ircmsg:
                continue
            # This can be useful for debugging
#            print(dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), ircmsg)
            if "PING :" in ircmsg:
                self.ping()
                continue
            mtch = MSG_PAT.match(ircmsg)
            if mtch:
                groups = mtch.groups()
                nick = groups[0]
                channel = groups[3]
                remark = groups[4]
                if len(nick) >= 17:
                    print("Odd nick: %s" % nick)
                    continue
                record(nick, channel, remark)


    def wait_for(self, txt):
        """Waits for the server to send a message containing the requested
        text.
        """
        ircmsg = ""
        while txt not in ircmsg:
            ircmsg = self.ircsock.recv(2048).decode("UTF-8")
            ircmsg = ircmsg.strip("\n\r")
            print(ircmsg)


    def joinchan(self, chan):
        self.ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
        self.wait_for("End of /NAMES list.")


    def ping(self): # respond to server Pings.
        self.ircsock.send(bytes("PONG :pingis\n", "UTF-8"))


    def sendmsg(self, msg, target):
        """Sends messages to the target."""
        self.ircsock.send(bytes("PRIVMSG %s :%s\r\n" % (target, msg), "UTF-8"))


def main():
    parser = argparse.ArgumentParser(description="IRC Bot")
    parser.add_argument("--channel-file", "-f", help="The path of the file "
            "containing the names of the channels to join, one per line.")
    parser.add_argument("--channel", "-c", action="append",
            help="Channels for the bot to join. Can be specified multiple "
            "times to join multiple channels.")
    args = parser.parse_args()
    if args.channel_file:
        with open(args.channel_file) as ff:
            chan_lines = ff.read().splitlines()
        channels = [chan.strip() for chan in chan_lines]
    else:
        channels = args.channel
    if not channels:
        print("You must specify at least one channel")
        exit(1)
    chan_count = len(channels)
    if chan_count > 10 * CHANNELS_PER_BOT:
        # Only have 10 bots registered
        print("Too many channels: %s. Need to register more bots.")
        exit()
    thread_list = []
    while channels:
        bot_chans, channels = (channels[:CHANNELS_PER_BOT],
                channels[CHANNELS_PER_BOT:])
        nick = "%s%s" % (NICK_BASE, len(thread_list))
        bot = IRCLogBot(nick, bot_chans)
        thread_list.append(bot)
        print(nick, len(bot_chans))
    for thd in thread_list:
        thd.start()
    for thd in thread_list:
        thd.join()


if __name__ == "__main__":
    main()
