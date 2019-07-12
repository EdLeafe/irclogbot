  FROM    python:3.7
  ADD     requirements.txt /
  RUN     apt-get update; apt-get -y upgrade; pip install -r requirements.txt
  ADD     irclogbot.py /
  ADD     .irccreds /
  ADD     channels.txt /
  ADD     utils.py /
  ADD     filemod_check.py /
  WORKDIR /
  ENTRYPOINT  ["python"]
