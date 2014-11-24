#!/usr/bin/env python
# coding:utf-8

import shelve
import feedparser
import pykka
import io, sys, os
import pprint
from pymongo import MongoClient
from bson.objectid import ObjectId
import pymongo
import datetime
import xml.etree.ElementTree as etree
import json
import logging
from raisin.raisin import Persistence
from raisin.raisin import FeedFetcher
from raisin.raisin import OpmlImporter


# global config
mongo_url = os.environ.get('MONGODB_URL')
opml_file = os.environ.get('OPML_FILE')
#logging.basicConfig(filename='example.log',level=logging.DEBUG)
logging.basicConfig(level = logging.DEBUG)


class RssShell:
    def __init__(self, pers):
        self.pers = pers
        pass

    def run(self):
        while True:
            sys.stdout.write('>> ')
            instr = sys.stdin.readline()
            instr = instr.strip()
            if instr == "exit" or instr == "quit":
                break
            self.interpret(instr)
        # do shutdown
        return 0

    def interpret(self, instr):
        cmds = instr.split()
        if len(cmds) == 0:
            return

        cmd = cmds[0]
        args = cmds[1:]
        if cmd == "crawl":
            self._crawl()
        elif cmd == "fetch":
            posts = self.pers.fetch_posts(5, *args).get()
            logging.debug(pprint.pformat(posts))
        elif cmd == "dump":
            self._dump_all()
        elif cmd == "dump_feeds":
            self._dump_feeds()
        elif cmd == "dump_posts":
            self._dump_posts()
        elif cmd == "import":
            self._import_opml()
        elif cmd == "add_feed" and len(args) > 1:
            add_source(args[1])
        elif cmd == "drop_posts":
            self.pers.drop_posts().get()
        elif cmd == "drop_all":
            self.pers.drop_all().get()
        else:
            logging.warning("unknown command: %s" % instr)

    def _dump_all(self):
        self._dump_feeds()
        self._dump_posts()

    def _dump_feeds(self):
        feeds = self.pers.get_feeds().get()

        for f in feeds.find():
            logging.debug(pprint.pformat(f))


    def _dump_posts(self):
        posts = self.pers.get_posts().get()

        posts = posts.find()
        for ar in posts:
            logging.debug(pprint.pformat(ar))

    def _import_opml(self):
        imp = OpmlImporter.start().proxy()

        imp.import_opml(opml_file, self.pers).get()

        imp.stop()

    def _crawl(self):
        fetcher = FeedFetcher.start().proxy()
        feeds = self.pers.get_feeds().get()

        fetcher.fetch(feeds, self.pers)

        fetcher.stop()

        return 0


if __name__ == '__main__':
    pers = Persistence.start(mongo_url).proxy()

    s = RssShell(pers)
    s.run()

    pers.stop()


# references
# http://stackoverflow.com/questions/493386/how-to-print-in-python-without-newline-or-space
# http://www.diveintopython3.net/xml.html
# http://api.mongodb.org/python/current/tutorial.html
# http://stackoverflow.com/questions/7745952/python-expand-list-to-function-arguments