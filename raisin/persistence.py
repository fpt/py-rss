#!/usr/bin/env python
# coding:utf-8

import pykka
import io, sys
import pprint
import re
import datetime
import logging
import zlib

# mongo
from pymongo import MongoClient
import gridfs
from bson.objectid import ObjectId
import pymongo
from mongoqueue import MongoQueue

from lxml import etree
import lxml.html


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
        db.parsedposts.ensure_index('rawfeed_id')
        db.parsedposts.ensure_index('post_url')
        #db.parsedposts.ensure_index('feed_id')

        db.viewposts.ensure_index('link_url')
        db.viewposts.ensure_index('feed_id')
        
        db.feeds.ensure_index([('feed_url', pymongo.ASCENDING), ('site_url', pymongo.ASCENDING)])

        # queue
        self.crawl_queue = MongoQueue(
            db.crawl_queue,
            consumer_id="consumer-1",
            timeout=300,
            max_attempts=3)
        self.parsedpost_queue = MongoQueue(
            db.parsedpost_queue,
            consumer_id="consumer-1",
            timeout=300,
            max_attempts=3)
        self.viewpost_queue = MongoQueue(
            db.viewpost_queue,
            consumer_id="consumer-2",
            timeout=300,
            max_attempts=3)

    # queue

    def get_crawl_queue(self):
        return self.crawl_queue

    def get_parsedpost_queue(self):
        return self.parsedpost_queue

    def get_viewpost_queue(self):
        return self.viewpost_queue

    # history

    def put_history(self, data):
        histories = self.db.histories
        hist_id = histories.insert(data)
        return hist_id

    # gridfs

    def put_fs(self, feed_id, body):
        return self.fs.put(zlib.compress(body), feed_id = feed_id, )

    def get_fs(self, file_id):
        f = self.fs.get(file_id)
        body = zlib.decompress(f.read())
        return f, body, f.feed_id

    # parsedpost

    def get_parsedpost_body(self, post_id):
        post = self.db.parsedposts.find_one({"_id": post_id})
        if post:
            return post['data']
        else:
            None

    def add_parsedpost(self, rawfeed_id, post_url, data):
        posts = self.db.parsedposts

        keys = {
            "post_url": post_url,
        }
        data = {
            'rawfeed_id' : rawfeed_id,
            "post_url": post_url,
            "data": data,
        }
        post = posts.find_and_modify(keys, data, upsert = True, new = True)
        return post['_id']

    # feeds

    def get_feeds(self):
        return self.db.feeds

    def get_feed(self, feed_id):
        feed = self.db.feeds.find_one({"_id": feed_id})
        return feed

    def put_feed(self, feed):
        feeds = self.db.feeds

        keys = {
            "_id": feed['_id'],
        }
        result = feeds.update(keys, feed, upsert = True)
        logging.debug({'action' : 'put_feed', 'result' : result})

    def add_feed(self, hist_id, title, feed_url, site_url, cat):
        feeds = self.db.feeds

        keys = {
            "feed_url": feed_url,
            "site_url": site_url,
        }
        data = {
            'hist_id' : hist_id,
            "title": title,
            "feed_url": feed_url,
            "site_url": site_url,
            "category": cat,
        }
        feed_id = feeds.update(keys, data, upsert = True)
        #print(feed_id)
        #print(feeds.find_one({"_id": feed_id}))

    # viewpost

    def get_viewposts(self):
        return self.db.viewposts

    def add_viewpost(self, item_dict):
        posts = self.db.viewposts

        if not item_dict.has_key('link_url'):
            return 1 # error
        idx_dict = {'link_url': item_dict['link_url']}
        result = posts.update(idx_dict, item_dict, upsert = True)
        #logging.debug(result)

    def _process_post(self, feeds, post):
        post['feed'] = feeds[post['feed_id']]
        if post.has_key('content'):
            post['content'] = post['content'][0]['value']
        if post.has_key('summary'):
            summary = post['summary']
            if not post.has_key('content'):
                post['content'] = summary

            try:
                element = lxml.html.fromstring(summary)
                summary = "\n".join(element.xpath("//text()"))
            except etree.XMLSyntaxError:
                print("html parse error")
                
            summary = summary[:200]
            # post['summary'] = re.sub(r'class="[^"]*"', '', post['summary'])
            post['summary'] = summary
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

        posts = self.get_viewposts()

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
        db.parsedposts.drop()
        db.viewposts.drop()
        db.drop_collection('fs')

        db.crawl_queue.drop()
        db.parsedpost_queue.drop()
        db.viewpost_queue.drop()

    def drop_posts(self):
        db = self.db
        logging.debug(db.collection_names())
        db.parsedposts.drop()
        db.viewposts.drop()

        db.parsedpost_queue.drop()
        db.viewpost_queue.drop()

# http://stackoverflow.com/questions/2950131/python-lxml-cleaning-out-html-tags
# http://stackoverflow.com/questions/19866172/bootstrap-3-accordion-collapse-does-not-work-on-iphone