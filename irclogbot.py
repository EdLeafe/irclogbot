import argparse
import datetime as dt
import re
import socket

from elasticsearch import Elasticsearch

HOST = "dodb"
es_client = Elasticsearch(host=HOST)

MSG_PAT = re.compile(r":([^!]+)!~([^@]+)@([a-zA-Z0-9.]+) PRIVMSG (\S+) :(.+)")
ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server = "chat.freenode.net"
CHANNELS = ["##irclogbot"]
botnick = "fulltextbot"
adminname = "edleafe"
exitcode = "take a hike %s" % botnick


def wait_for(txt):
    """Waits for the server to send a message containing the requested text."""
    ircmsg = ""
    while txt not in ircmsg:
        ircmsg = ircsock.recv(2048).decode("UTF-8")
        ircmsg = ircmsg.strip("\n\r")
        print(ircmsg)


def joinchan(chan):
    ircsock.send(bytes("JOIN %s\n" % chan, "UTF-8")) 
    wait_for("End of /NAMES list.")


def ping(): # respond to server Pings.
    ircsock.send(bytes("PONG :pingis\n", "UTF-8"))


def sendmsg(msg, target):
    """Sends messages to the target."""
    ircsock.send(bytes("PRIVMSG %s :%s\r\n" % (target, msg), "UTF-8"))


def logit(nick, channel, remark):
    tm = dt.datetime.utcnow().replace(microsecond=0)
    tmstr = tm.strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"channel": channel, "nick": nick, "posted": tm, "remark": remark}
    try:
        es_client.index(index="irclog", doc_type="irc", body=doc)
    except Exception as e:
        print("Elasticsearch exception: %s" % e)


def main():
    while True:
        ircmsg = ircsock.recv(2048).decode("UTF-8")
        ircmsg = ircmsg.strip(" \n\r")
        if not ircmsg:
            continue
        print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ircmsg)
        if "PING :" in ircmsg:
            ping()
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
            if ((nick.lower() == adminname.lower()) and 
                    (remark.rstrip() == exitcode)):
                sendmsg("oh...okay. :'(", channel)
                ircsock.send(bytes("QUIT \n", "UTF-8"))
                return
            logit(nick, channel, remark)


def connect_socket():
    ircsock.connect((server, 6667))
    # We are basically filling out a form with this line and saying to set all
    # the fields to the bot nickname.
    msg = "USER %s %s %s %s\n" % (botnick, botnick, botnick, botnick)
    ircsock.send(bytes(msg, "UTF-8"))
    # assign the nick to the bot
    msg = "NICK %s\n" % botnick
    ircsock.send(bytes(msg, "UTF-8"))
    wait_for("NickServ identify <password>")
    # Send the nick password to the nick server
    with open(".irccreds") as ff:
        pw = ff.read().strip()
    msg = "PRIVMSG NickServ :IDENTIFY %s\n" % pw
    ircsock.send(bytes(msg, "UTF-8"))
    wait_for("You are now identified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRC Bot")
    parser.add_argument("--channel", "-c", action="append",
            help="""Channels for the bot to join. Can be specified multiple
            times to join multiple channels.""")
    args = parser.parse_args()
    connect_socket()
    channels = args.channel or CHANNELS
    for channel in channels:
        joinchan(channel)
    main()
