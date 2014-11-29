#!/usr/bin/env python
# coding:utf-8

import shelve
import feedparser
import pykka
import io, sys
import pprint
import re
import datetime
#import dateutil.parser
import logging
import requests
import zlib

from lxml import etree
import lxml.html
import xml.etree.ElementTree as ElementTree
import json

from persistence import Persistence


# feedparser hack
while len(feedparser._date_handlers) > 0:
    feedparser._date_handlers.pop()

class FeedFetcher(pykka.ThreadingActor):
    def __init__(self):
        super(FeedFetcher, self).__init__()


    def fetch(self, feeds, pers):
        for f in feeds.find():
            #logging.debug(pprint.pformat(f))
            if not f.has_key('feed_url'):
                continue
            file_id = self._fetch_file(f, pers)
            print(file_id)
            if not file_id:
                # TODO: mark as bad feed
                continue
            posts = self._parse_stored_feed(file_id, pers)
            self._store_posts(f, posts, pers)
        return 0

    def _fetch_file(self, feed, pers):
        #logging.debug(pprint.pformat(f))
        r = requests.get(feed['feed_url'])
        if r.status_code != 200:
            return False
        body = r.text.encode("UTF-8")
        file_id = pers.put_fs(feed['_id'], body).get()
        return file_id

    def _store_posts(self, feed, posts, pers):
        for p in posts:
            p['feed_id'] = feed['_id']
            #pprint.pprint(p)
            pers.add_post(p)

    def _parse_stored_feed(self, file_id, pers):
        stored_file, body = pers.get_fs(file_id).get()
        print(stored_file)
        #print(body)

        posts = self._parse_feed(body, pers, file_id)

        # update file TODO: method
        pers.fs.get().put(stored_file, parsed_at=datetime.datetime.utcnow())

        return posts

    def _make_viewpost(self, pers, parsed_id):
        e = pers.get_parsedpost_body(parsed_id).get()

        d = dict()
        #logging.debug(pprint.pformat(e))
        d['title'] = e['title']
        d['link_url'] = e['link']
        if e.has_key('summary'):
            d['summary'] = e['summary']
        if e.has_key('content'):
            d['content'] = e['content']

        if False:
            if e.has_key('published_parsed'):
                d['published'] = e['published_parsed']
            elif e.has_key('published'):
                d['published'] = e['published']

            if e.has_key('updated_parsed'):
                d['updated'] = e['updated_parsed']
            elif e.has_key('updated'):
                d['updated'] = e['updated']
        logging.debug(pprint.pformat(e))
        return d

    def _parse_feed(self, body, pers, file_id):
        feed = feedparser.parse(body)
        posts = []
        #d['raw'] = pprint.pformat(feed)
        for e in reversed(feed['entries']):
            parsed_id = pers.add_parsedpost(file_id, e['link'], e).get()

            d = self._make_viewpost(pers, parsed_id)
            #print(e['description'])
            #print(e['url'])
            #print(e['description_detail'])
            #print(e['date'])
            posts.append(d)

        return posts


class OpmlImporter(pykka.ThreadingActor):

    def import_opml(self, filename, pers):
        tree = ElementTree.parse(filename)
        root = tree.getroot()
        first_outlines = root.findall('body/outline')

        # need refactor
        hist_id = pers.put_history({'type' : 'import', 'filename' : filename}).get()

        for fo in first_outlines:
            if (fo.attrib.has_key('type')):
                self.import_outline(fo, pers, hist_id)
            else:
                category = fo.attrib['title']
                logging.debug(pprint.pformat(category))
                second_outlines = fo.findall('outline')
                for so in second_outlines:
                    self.import_outline(so, pers, hist_id, category)


    def import_outline(self, elem, pers, hist_id, cat = None):
        attrs = elem.attrib
        title = attrs['title']
        feed_url = attrs['xmlUrl']

        site_url = None
        if attrs.has_key('htmlUrl'):
            site_url = attrs['htmlUrl']

        logging.debug(pprint.pformat([title, feed_url, site_url]))
        pers.add_feed(hist_id, title, feed_url, site_url, cat)

# http://stackoverflow.com/questions/2950131/python-lxml-cleaning-out-html-tags
# http://stackoverflow.com/questions/19866172/bootstrap-3-accordion-collapse-does-not-work-on-iphone
# http://stackoverflow.com/questions/20013608/pymongo-update-multifalse-get-id-of-updated-document