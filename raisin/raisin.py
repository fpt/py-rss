#!/usr/bin/env python
# coding:utf-8

import shelve
import feedparser
import pykka
import io, sys
import pprint
import re
import datetime
import dateutil.parser
import logging
import requests
import zlib

from lxml import etree
import lxml.html
import xml.etree.ElementTree as ElementTree
import json

from persistence import Persistence


num_crawler = 4
min_crawl_span = 60 * 10

# feedparser hack
while len(feedparser._date_handlers) > 0:
    feedparser._date_handlers.pop()


class FeedFetcher(pykka.ThreadingActor):
    def __init__(self):
        super(FeedFetcher, self).__init__()


    def fetch(self, pers):
        init = FetcherInitiator()
        init.run(pers)

        crawlers = []
        for i in range(num_crawler):
            crawler = CrawlerWorker.start().proxy()
            crawlers.append(crawler)

        futures = [c.run(pers) for c in crawlers]
        f = futures[0].join(*futures[1:])
        logging.debug({'action' : 'fetcher_crawler', 'result' : f.get()})
        for c in crawlers:
            c.stop()

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


class CrawlerWorker(pykka.ThreadingActor):
    def __init__(self):
        super(CrawlerWorker, self).__init__()

    def _fetch_file(self, feed, pers):
        try:
            r = requests.get(feed['feed_url'])
        except:
            logging.error({'feed_url' : feed['feed_url'], 'error' : sys.exc_info()[0]})
            return None

        logging.debug({'feed_url' : feed['feed_url'], 'status_code' : r.status_code})
        if r.status_code != 200:
            return None
        body = r.text.encode("UTF-8")
        file_id = pers.put_fs(feed['_id'], body).get()
        return file_id

    def _to_skip(self, feed):
        if feed.has_key('last_crawled_at'):
            lc_at = feed['last_crawled_at']
            now = datetime.datetime.utcnow()
            dsec = (now - lc_at).total_seconds()
            logging.debug({'old' : lc_at, 'now' : now, 'dsec' : dsec, 'span' : min_crawl_span})
            if dsec < min_crawl_span:
                return True
        return False

    def run(self, pers):
        crawl_queue = pers.get_crawl_queue().get()
        while crawl_queue.size() > 0:
            job = crawl_queue.next()
            if not job:
                break
            if not job.payload.has_key('feed_id'):
                logging.error({'action' : 'crawlerworker.run', 'msg' : 'invalid job in crawl_queue', 'param' : job})
                continue

            feed_id = job.payload['feed_id']

            f = pers.get_feed(feed_id).get()
            if not f.has_key('feed_url'):
                logging.info({'action' : 'crawlerworker.run', 'msg' : 'feed ignored', 'param' : f})
                continue
            if self._to_skip(f):
                logging.info({'action' : 'crawlerworker.run', 'msg' : 'skipping', 'param' : f})
                continue

            file_id = self._fetch_file(f, pers)
            logging.info({'action' : 'crawlerworker.run.fetch', 'result' : file_id})
            if not file_id:
                logging.info({'action' : 'crawlerworker.run', 'msg' : 'maybe bad feed', 'param' : feed_id})
                continue
            pers.get_parsedpost_queue().get().put({"file_id": file_id, "feed_id": feed_id})

            f['last_crawled_at'] = datetime.datetime.utcnow()
            pers.put_feed(f)

        return 0


class ParserWorker:

    def _parse_stored_feed(self, pers, file_id):
        stored_file, body, feed_id = pers.get_fs(file_id).get()
        logging.info({'action' : 'ParserWorker._parse_stored_feed', 'file' : stored_file})

        posts = self._parse_feed(body, pers, file_id, feed_id)

        # update file TODO: method
        pers.fs.get().put(stored_file, parsed_at=datetime.datetime.utcnow())

        return posts

    def _parse_feed(self, body, pers, file_id, feed_id):
        feed = feedparser.parse(body)
        for e in reversed(feed['entries']):
            if e.has_key('updated'):
                upd_str = e['updated']
                upd_dt = dateutil.parser.parse(upd_str, yearfirst=True, dayfirst=False)
                e['updated_at'] = upd_dt
            elif e.has_key('data') and e['data'].has_key('updated'):
                upd_str = e['data']['updated']
                upd_dt = dateutil.parser.parse(upd_str, yearfirst=True, dayfirst=False)
                e['updated_at'] = upd_dt
            elif e.has_key('summary_detail') and e['summary_detail'].has_key('updated'):
                upd_str = e['summary_detail']['updated']
                upd_dt = dateutil.parser.parse(upd_str, yearfirst=True, dayfirst=False)
                e['updated_at'] = upd_dt
            elif e.has_key('published'):
                upd_str = e['published']
                upd_dt = dateutil.parser.parse(upd_str, yearfirst=False, dayfirst=True)
                e['updated_at'] = upd_dt
            else:
                logging.info({'action' : 'ParserWorker._parse_feed', 'msg' : 'no data.updated field', 'param' : e})
                e['updated_at'] = datetime.datetime.utcnow()

            parsed_id = pers.add_parsedpost(file_id, e['link'], e).get()

            pers.get_viewpost_queue().get().put({"parsed_id": parsed_id, "feed_id": feed_id})

    def run(self, pers):
        parsedpost_queue = pers.get_parsedpost_queue().get()
        while parsedpost_queue.size() > 0:
            job = parsedpost_queue.next()
            if not job:
                break
            if not job.payload.has_key('file_id') or not job.payload.has_key('feed_id'):
                logging.error({'action' : 'ParserWorker.run', 'msg' : 'invalid job in persepost_queue', 'param' : job})
                continue

            file_id = job.payload['file_id']
            feed_id = job.payload['feed_id']
            logging.info({'action' : 'ParserWorker.run', 'file_id' : file_id, 'param' : file_id})

            posts = self._parse_stored_feed(pers, file_id)

        return 0


class ViewPostWorker:
    def _make_viewpost(self, pers, parsed_id):
        e = pers.get_parsedpost_body(parsed_id).get()

        d = dict()
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
        return d

    def _store_post(self, feed_id, post, pers):
        post['feed_id'] = feed_id
        pers.add_viewpost(post)

    def run(self, pers):
        viewpost_queue = pers.get_viewpost_queue().get()
        while viewpost_queue.size() > 0:
            job = viewpost_queue.next()
            if not job:
                break
            if not job.payload.has_key('parsed_id') or not job.payload.has_key('feed_id'):
                logging.error({'action' : 'parserworker.run', 'msg' : 'invalid job in viewpost_queue', 'param' : job})
                continue

            parsed_id = job.payload['parsed_id']
            feed_id = job.payload['feed_id']
            logging.debug({'action' : 'viewpostworker_run', 'parsed_id' : parsed_id})

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
                logging.debug({'action' : 'import_opml', 'param' : category})
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

        logging.debug({'action' : 'import_outline', 'param' : [title, feed_url, site_url]})
        pers.add_feed(hist_id, title, feed_url, site_url, cat)

# http://stackoverflow.com/questions/2950131/python-lxml-cleaning-out-html-tags
# http://stackoverflow.com/questions/19866172/bootstrap-3-accordion-collapse-does-not-work-on-iphone
# http://stackoverflow.com/questions/20013608/pymongo-update-multifalse-get-id-of-updated-document