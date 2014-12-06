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


    def fetch(self, pers):
        init = FetcherInitiator()
        init.run(pers)

        crawler = CrawlerWorker()
        crawler.run(pers)

        parser = ParserWorker()
        parser.run(pers)

        vpworker = ViewPostWorker()
        vpworker.run(pers)


class FetcherInitiator():
    def run(self, pers):
        feeds = pers.get_feeds().get().find()
        crawl_queue = pers.get_crawl_queue().get()

        for f in feeds:
            feed_id = f['_id']
            crawl_queue.put({"feed_id": feed_id})

        return 0


class CrawlerWorker:

    def _fetch_file(self, feed, pers):
        #logging.debug(pprint.pformat(f))
        r = requests.get(feed['feed_url'])
        if r.status_code != 200:
            return False
        body = r.text.encode("UTF-8")
        file_id = pers.put_fs(feed['_id'], body).get()
        return file_id

    def run(self, pers):
        crawl_queue = pers.get_crawl_queue().get()
        while crawl_queue.size() > 0:
            job = crawl_queue.next()
            if not job:
                break
            if not job.payload.has_key('feed_id'):
                print("invalid job in crawl_queue: " + str(job))
                continue

            feed_id = job.payload['feed_id']
            print("work feed_id: " + str(feed_id))

            f = pers.get_feed(feed_id).get()
            #logging.debug(pprint.pformat(f))
            if not f.has_key('feed_url'):
                continue

            file_id = self._fetch_file(f, pers)
            print("file_id: " + str(file_id))
            if not file_id:
                # TODO: mark as bad feed
                continue
            pers.get_parsedpost_queue().get().put({"file_id": file_id, "feed_id": feed_id})

        return 0


class ParserWorker:

    def _parse_stored_feed(self, pers, file_id):
        stored_file, body, feed_id = pers.get_fs(file_id).get()
        print(stored_file)
        #print(body)

        posts = self._parse_feed(body, pers, file_id, feed_id)

        # update file TODO: method
        pers.fs.get().put(stored_file, parsed_at=datetime.datetime.utcnow())

        return posts

    def _parse_feed(self, body, pers, file_id, feed_id):
        feed = feedparser.parse(body)
        #d['raw'] = pprint.pformat(feed)
        for e in reversed(feed['entries']):
            parsed_id = pers.add_parsedpost(file_id, e['link'], e).get()

            pers.get_viewpost_queue().get().put({"parsed_id": parsed_id, "feed_id": feed_id})

    def run(self, pers):
        parsedpost_queue = pers.get_parsedpost_queue().get()
        while parsedpost_queue.size() > 0:
            job = parsedpost_queue.next()
            if not job:
                break
            if not job.payload.has_key('file_id') or not job.payload.has_key('feed_id'):
                print("invalid job in persepost_queue: " + str(job))
                continue

            file_id = job.payload['file_id']
            feed_id = job.payload['feed_id']
            print("work file_id: " + str(file_id))

            posts = self._parse_stored_feed(pers, file_id)

        return 0


class ViewPostWorker:
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
            if e.has_key('published'):
                d['published'] = e['published']
            if e.has_key('updated'):
                d['updated'] = e['updated']
        #logging.debug(pprint.pformat(e))
        return d

    def _store_post(self, feed_id, post, pers):
        post['feed_id'] = feed_id
        #pprint.pprint(p)
        pers.add_viewpost(post)

    def run(self, pers):
        viewpost_queue = pers.get_viewpost_queue().get()
        while viewpost_queue.size() > 0:
            job = viewpost_queue.next()
            if not job:
                break
            if not job.payload.has_key('parsed_id') or not job.payload.has_key('feed_id'):
                print("invalid job in viewpost_queue: " + str(job))
                continue

            parsed_id = job.payload['parsed_id']
            feed_id = job.payload['feed_id']
            print("yo " + str(parsed_id))

            viewpost = self._make_viewpost(pers, parsed_id)

            self._store_post(feed_id, viewpost, pers)

        return 0


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