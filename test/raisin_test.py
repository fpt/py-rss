# -*- coding: utf-8 -*-

from nose.tools import with_setup, raises

import raisin
from raisin.raisin import Persistence
from raisin.raisin import FeedFetcher
from raisin.raisin import OpmlImporter
import feedparser

MONGO_URL = 'mongodb://192.168.56.101/TEST_DATABASE'

class TestFeedFetcher:
    # このクラスのテストケースを実行する前に１度だけ実行する
    @classmethod
    def setup_class(clazz):
        pass
 
    # このクラスのテストケースをすべて実行した後に１度だけ実行する
    @classmethod
    def teardown_class(clazz):
        client = pymongo.MongoClient(MONGO_URL)
        client.drop_database('TEST_DATABASE')
 
    # このクラスの各テストケースを実行する前に実行する
    def setup(self):
        pass
 
    # このクラスの各テストケースを実行した後に実行する
    def teardown(self):
        pass

    def test_persistence_start_stop(self):
        fetcher = Persistence.start(MONGO_URL).proxy()
        fetcher.stop()
        assert(True)

    def test_feedfetcher_start_stop(self):
        fetcher = FeedFetcher().start().proxy()
        fetcher.stop()
        assert(True)

    def test_opmlimporter_start_stop(self):
        fetcher = OpmlImporter.start().proxy()
        fetcher.stop()
        assert(True)

# class name must start with "[Tt]est"