import raisin
from raisin.raisin import Persistence
from raisin.raisin import FeedFetcher
from raisin.raisin import OpmlImporter
import feedparser

import unittest

def fun(x):
    return x + 1

class FeedFetcherTest(unittest.TestCase):
    def test(self):
        fetcher = FeedFetcher.start().proxy()
        fetcher.stop()
        self.assertEqual(fun(3), 4)
