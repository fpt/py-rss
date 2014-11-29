py-rss
======

## Design

### Terminology

* User - an user of this service
* Feed - RSS or Atom feed
* Category - a named group of subscription
* Subscription - user and feed relation
* Post - An article within a feed
* History - Fav, Saved, Read history(no deletion)

### Functionality

* OAuth login
* View posts
* Manage categories and subscriptions
* Add new feed sources
* Import OPML

### Crawling

1. Fetch RSS and store it to GridFS.
2. Parse it and store parsed object.
3. Format parsed object to view and store it.

### Collections

* Users
    * key: _id, mail
* Categories
    * key: _id, name
* Subscriptions
    * key: user_id, category_id, feedsource_id
* FeedSources
    * key: _id, feed_url, site_url
* RawFeed (GridFS)
    * key: _id, feed_id
* ParsedPost
    * key: _id, rawfeed_id
* ViewPost
    * key: _id, parsedpost_id, posted_at
    * thumbnail_url
* UserHistory
    * key: user_id, kind, (any)_id, registed_at
* JobQueue
    * key: _id, queue_name

### Class

#### Actor

* FeedCrawler
* FeedParser
* PostMaker
* OpmlImporter

#### Instance

* FeedSource
* User
* Subscription
