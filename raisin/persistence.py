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
        db.feeds.ensure_index([('feed_url', pymongo.HASHED)])
        db.feeds.ensure_index([('site_url', pymongo.HASHED)])

        db.parsedposts.ensure_index('file_id')
        db.parsedposts.ensure_index([('post_url', pymongo.ASCENDING)], unique=True)

        db.viewposts.ensure_index([('link_url', pymongo.ASCENDING)], unique=True)
        db.viewposts.ensure_index([('feed_id', pymongo.ASCENDING)])

        db.system_histories.ensure_index([('action', pymongo.HASHED)])
        db.system_histories.ensure_index([('created_at', pymongo.DESCENDING)])

        db.user_histories.ensure_index([('user_id', pymongo.ASCENDING), ('action', pymongo.ASCENDING)])
        db.user_histories.ensure_index([('created_at', pymongo.DESCENDING)])

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

    def put_system_history(self, data):
        hists = self.db.system_histories
        data['created_at'] = datetime.datetime.utcnow()
        #logging.debug({'action' : 'put_system_history', 'data' : data})
        hist_id = hists.insert(data)
        return hist_id

    def get_last_system_history(self, action):
        hist = self.db.system_histories.find({"action": action}).sort('created_at',pymongo.DESCENDING).limit(1)
        logging.debug({'action' : 'get_last_system_history', 'data' : hist})
        return hist

    def get_last_crawl_history(self, feed_id):
        hist = self.db.system_histories.find({"action" : 'crawl', 'feed_id' : feed_id}).sort('created_at',pymongo.DESCENDING).limit(1)
        if hist.count() == 0:
            return None
        data = hist[0]
        #logging.debug({'action' : 'get_last_crawl_history', 'data' : data})
        return data

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

    def add_parsedpost(self, feed_id, file_id, post_url, data, force_update = False):
        posts = self.db.parsedposts

        keys = {
            "post_url": post_url,
        }

        if not force_update:
            cur = posts.find(keys).limit(1)
            if cur and cur.count() > 0:
                post = cur[0]
                logging.debug({'action' : 'Persistence.add_parsedpost', 'msg' : 'skipped', 'parsedpost_id' : post['_id']})
                return post['_id']

        data = {
            'feed_id' : feed_id,
            'file_id' : file_id,
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
        logging.debug({'action' : 'Persistence.put_feed', 'feed_id' : feed['_id'], 'result' : result})

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

    def add_viewpost(self, item_dict, force_update=False):
        posts = self.db.viewposts

        if not item_dict.has_key('link_url'):
            return 1 # error
        idx_dict = {'link_url': item_dict['link_url']}

        if not force_update:
            cur = posts.find(idx_dict).limit(1)
            if cur and cur.count() > 0:
                post = cur[0]
                logging.debug({'action' : 'Persistence.add_viewpost', 'msg' : 'skipped', 'viewpost_id' : post['_id']})
                return

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

    def fetch_posts_after(self, count = 10, category = None, feed_id = None, post_id = None, unread_only = False):
        res = self.fetch_posts(count, category, feed_id, None, post_id, unread_only)
        if len(res) < count:
            res = self.fetch_posts(count, category, feed_id, None, None, unread_only)
        return res

    def fetch_posts_before(self, count = 10, category = None, feed_id = None, post_id = None, unread_only = False):
        res = self.fetch_posts(count, category, feed_id, post_id, None, unread_only)
        # temporary
        if len(res) < count:
            res = self.fetch_posts(count, category, feed_id, None, None, unread_only)
        return res

    def fetch_posts(self, count = 10, category = None, feed_id = None, prev_post_id = None, after_post_id = None, unread_only = False):
        feeds_find_dic = None
        if category:
            feeds_find_dic = {'category': category}
        elif feed_id:
            feeds_find_dic = {'_id': ObjectId(feed_id)}

        feeds = self.get_feeds()
        posts = self.get_viewposts()
        cat_feeds = feeds.find(feeds_find_dic)

        print('-----------')
        print(category)
        print(feed_id)
        print(prev_post_id)
        print('-----------')
        feeds_dic = {f['_id'] : f for f in cat_feeds}
        find_dic = dict()
        if category or feed_id:
            find_dic['feed_id'] = {'$in': feeds_dic.keys()}
        if prev_post_id:
            find_dic['_id'] = {'$lt': ObjectId(prev_post_id)}
        elif after_post_id:
            find_dic['_id'] = {'$gt': ObjectId(after_post_id)}
        print(find_dic)

        if after_post_id:
            cur = posts.find(find_dic).sort('_id', direction = pymongo.DESCENDING)
            cnt = cur.count()
            if cnt <= count:
                return []
            page_posts = cur.skip(cnt - count)
        else:
            page_posts = posts.find(find_dic).limit(count).sort('_id', direction = pymongo.DESCENDING)

        res = [self._process_post(feeds_dic, p) for p in page_posts]

        return res

    def drop_all(self):
        db = self.db
        logging.debug(db.collection_names())
        db.feeds.drop()
        db.parsedposts.drop()
        db.viewposts.drop()
        db.histories.drop()
        db.system_histories.drop()
        db.user_histories.drop()
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