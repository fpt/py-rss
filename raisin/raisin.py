#!/usr/bin/env python
# coding:utf-8

import shelve
import feedparser
import pykka
import io, sys
import pprint
import re
import datetime
import logging
import requests
import zlib

import xml.etree.ElementTree as etree
import json

# mongo
from pymongo import MongoClient
import gridfs
from bson.objectid import ObjectId
import pymongo



class Persistence(pykka.ThreadingActor):
    def __init__(self, mongo_url):
        super(Persistence, self).__init__()

        client = MongoClient(mongo_url)
        db = client.get_default_database()

        self.client = client
        self.db = db

        # gridfs
        self.fs = gridfs.GridFS(self.db)

        # index
        db.posts.ensure_index('link_url')
        db.feeds.ensure_index([('feed_url', pymongo.ASCENDING), ('site_url', pymongo.ASCENDING)])

    # gridfs

    def put_fs(self, feed_id, body):
        return self.fs.put(zlib.compress(body), feed_id = feed_id, )

    def get_fs(self, file_id):
        f = self.fs.get(file_id)
        body = zlib.decompress(f.read())
        return f, body

    # feeds

    def get_feeds(self):
        return self.db.feeds

    def get_posts(self):
        return self.db.posts

    def add_feed(self, title, feed_url, site_url, cat):
        feeds = self.db.feeds

        keys = {
            "feed_url": feed_url,
            "site_url": site_url,
        }
        data = {
            "feed_url": feed_url,
            "site_url": site_url,
            "title": title,
            "category": cat,
        }
        feed_id = feeds.update(keys, data, upsert = True)
        #print(feed_id)
        #print(feeds.find_one({"_id": feed_id}))

    def add_post(self, item_dict):
        posts = self.db.posts

        if not item_dict.has_key('link_url'):
            return 1 # error
        idx_dict = {'link_url': item_dict['link_url']}
        post_id = posts.update(idx_dict, item_dict, upsert = True)
        logging.debug(post_id)

    def _process_post(self, feeds, post):
        post['feed'] = feeds[post['feed_id']]
        if post.has_key('summary'):
            post['summary'] = re.sub(r'class="[^"]*"', '', post['summary'])
        return post

    def fetch_posts_after(self, count = 10, category = None, post_id = None, unread_only = False):
        res = self.fetch_posts(count, category, None, post_id, unread_only)
        if len(res) < count:
            res = self.fetch_posts(count, category, None, None, unread_only)
        return res

    def fetch_posts_before(self, count = 10, category = None, post_id = None, unread_only = False):
        res = self.fetch_posts(count, category, post_id, None, unread_only)
        # temporary
        if len(res) < count:
            res = self.fetch_posts(count, category, None, None, unread_only)
        return res

    def fetch_posts(self, count = 10, category = None, prev_post_id = None, after_post_id = None, unread_only = False):
        feeds = self.get_feeds()
        if category:
            cat_feeds = feeds.find({'category': category})
        else:
            cat_feeds = feeds.find()

        posts = self.get_posts()

        print(category)
        print(prev_post_id)
        print(cat_feeds)
        feeds_dic = {f['_id'] : f for f in cat_feeds}
        find_dic = dict()
        if category:
            find_dic['feed_id'] = {'$in': feeds_dic.keys()}
        if prev_post_id:
            find_dic['_id'] = {'$lt': ObjectId(prev_post_id)}
        elif after_post_id:
            find_dic['_id'] = {'$gt': ObjectId(after_post_id)}
        print(find_dic)

        page_posts = posts.find(find_dic).limit(count).sort('_id', direction = pymongo.DESCENDING)

        res = [self._process_post(feeds_dic, p) for p in page_posts]

        return res

    def drop_all(self):
        db = self.db
        logging.debug(db.collection_names())
        db.feeds.drop()
        db.posts.drop()
        db.drop_collection('fs')

    def drop_posts(self):
        db = self.db
        logging.debug(db.collection_names())
        db.posts.drop()


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

        posts = self._parse_feed(body, pers)

        # update file TODO: method
        pers.fs.get().put(stored_file, parsed_at=datetime.datetime.utcnow())

        return posts

    def _parse_feed(self, body, pers):
        feed = feedparser.parse(body)
        posts = []
        #d['raw'] = pprint.pformat(feed)
        for e in reversed(feed['entries']):
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

            #print(e['description'])
            #print(e['url'])
            #print(e['description_detail'])
            #print(e['date'])
            posts.append(d)

        return posts


class OpmlImporter(pykka.ThreadingActor):

    def import_opml(self, filename, pers):
        tree = etree.parse(filename)
        root = tree.getroot()
        first_outlines = root.findall('body/outline')

        for fo in first_outlines:
            if (fo.attrib.has_key('type')):
                self.import_outline(fo, pers)
            else:
                category = fo.attrib['title']
                logging.debug(pprint.pformat(category))
                second_outlines = fo.findall('outline')
                for so in second_outlines:
                    self.import_outline(so, pers, category)


    def import_outline(self, elem, pers, cat = None):
        attrs = elem.attrib
        title = attrs['title']
        feed_url = attrs['xmlUrl']

        site_url = None
        if attrs.has_key('htmlUrl'):
            site_url = attrs['htmlUrl']

        logging.debug(pprint.pformat([title, feed_url, site_url]))
        pers.add_feed(title, feed_url, site_url, cat)

