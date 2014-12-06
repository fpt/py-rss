#!/usr/bin/env python
# coding:utf-8

from flask import Flask, redirect, url_for, session, request, render_template
from flask_oauth import OAuth
import logging
from logging.handlers import RotatingFileHandler

from raisin.raisin import Persistence
from raisin.raisin import FeedFetcher
from raisin.raisin import OpmlImporter
import pprint
from tools import jsonify
import os

# for session
SECRET_KEY = 'development key'
# for debug
DEBUG = True
page_count = 10

# oauth
oauth = OAuth()

facebook = oauth.remote_app('facebook',
    base_url='https://graph.facebook.com/',
    request_token_url=None,
    request_token_params={'scope': 'email'},
    access_token_url='/oauth/access_token',
    authorize_url='https://www.facebook.com/dialog/oauth',
    consumer_key=os.environ.get('FB_C_KEY'),
    consumer_secret=os.environ.get('FB_C_SECRET')
)

twitter = oauth.remote_app('twitter',
    base_url='https://api.twitter.com/1/',
    request_token_url='https://api.twitter.com/oauth/request_token',
    access_token_url='https://api.twitter.com/oauth/access_token',
    authorize_url='https://api.twitter.com/oauth/authenticate',
    consumer_key=os.environ.get('TW_C_KEY'),
    consumer_secret=os.environ.get('TW_C_SECRET')
)

root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
tmpl_dir = os.path.join(root_dir, 'templates')
static_dir = os.path.join(root_dir, 'static')
app = Flask(__name__, template_folder=tmpl_dir, static_folder=static_dir)
app.debug = DEBUG
app.secret_key = SECRET_KEY

# app global
pers = None
crawler = None

@app.route('/')
def index():
    print("jiji")
    return render_template('index.html', name = 'yoyo')

@app.route('/feeds')
def feeds():
    print("jiji")
    return render_template('feeds.html', name = 'yoyo')

# API

@app.route('/api/1/feeds', methods=['GET'])
def feeds_list():
    feeds = pers.get_feeds().get()

    res = [f for f in feeds.find()]

    return jsonify({'feeds': res})

@app.route('/api/1/posts', methods=['GET'])
def posts_list():
    posts = pers.fetch_posts(page_count).get()

    return make_posts_response(posts)

@app.route('/api/1/posts/<category>', methods=['GET'])
def posts_list_category(category):
    if category == 'all':
        category = None
    posts = pers.fetch_posts(page_count, category).get()

    return make_posts_response(posts)

@app.route('/api/1/posts/<category>/newer/<previd>', methods=['GET'])
def posts_list_category_newer(category, previd):
    if category == 'all':
        category = None

    posts = pers.fetch_posts_after(page_count, category, previd).get()

    return make_posts_response(posts)

@app.route('/api/1/posts/<category>/older/<previd>', methods=['GET'])
def posts_list_category_older(category, previd):
    if category == 'all':
        category = None

    posts = pers.fetch_posts_before(page_count, category, previd).get()

    return make_posts_response(posts)

def make_posts_response(posts):
    if len(posts) > 0:
        return jsonify({'first_id' : posts[0]['_id'], 'last_id' : posts[-1]['_id'], 'posts': posts})
    else:
        return jsonify({'error' : "no post"})

@app.route('/api/1/crawl', methods=['GET'])
def crawl_trigger():
    global crawler
    if not crawler:
        crawler = FeedFetcher.start().proxy()

    crawler.fetch(pers)

    return jsonify({'result' : 'success'})


# auth

@app.route('/auth')
def auth():
    return redirect(url_for('tw_login'))
    #return redirect(url_for('go_login'))
    #return redirect(url_for('db_login'))

@app.route('/fb_login')
def fb_login():
    return facebook.authorize(callback=url_for('fb_authorized',
        next=request.args.get('next') or request.referrer or None,
        _external=True))


@app.route('/tw_login')
def tw_login():
    return twitter.authorize(callback=url_for('tw_authorized',
        next=request.args.get('next') or request.referrer or None,
        _external=True))


@app.route('/fb_login/authorized')
@facebook.authorized_handler
def fb_authorized(resp):
    if resp is None:
        return 'Access denied: reason=%s error=%s' % (
            request.args['error_reason'],
            request.args['error_description']
        )
    session['fb_oauth_token'] = (resp['access_token'], '')
    me = facebook.get('/me')
    return 'Logged in as id=%s name=%s redirect=%s' % \
        (me.data['id'], me.data['name'], request.args.get('next'))


@app.route('/tw_login/authorized')
@twitter.authorized_handler
def tw_authorized(resp):
    next_url = request.args.get('next') or url_for('index')
    if resp is None:
        return 'Access denied: reason=%s error=%s' % (
            request.args['error_reason'],
            request.args['error_description']
        )
    session['tw_oauth_token'] = (
        resp['oauth_token'],
        resp['oauth_token_secret']
    )
    session['tw_username'] = resp['screen_name']
    return 'Logged in as name=%s' % \
        (resp['screen_name'])


@facebook.tokengetter
def get_facebook_oauth_token():
    return session.get('fb_oauth_token')


@twitter.tokengetter
def get_twitter_oauth_token(token=None):
    return session.get('tw_oauth_token')

@app.route('/static/<path:filepath>')
def static_proxy(filepath):
    print(filepath)
    # send_static_file will guess the correct MIME type
    return app.send_static_file(os.path.join(filepath))


# public methods

def app_initialize(mongo_url):
    global pers
    pers = Persistence.start(mongo_url).proxy()

    handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)


def app_terminate():
    global pers, crawler

    if pers:
        pers.stop()
    if crawler:
        crawler.stop()


# http://flask.pocoo.org/docs/0.10/quickstart/#static-files
# http://stackoverflow.com/questions/20646822/how-to-serve-static-files-in-flask
#   To put your app in other package, you need to specify 'static_dir' otherwise path confilicts.