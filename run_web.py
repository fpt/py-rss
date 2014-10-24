#!/usr/bin/env python
# coding:utf-8

import os, sys
from raisinweb.app import app, app_initialize, app_terminate


def main():
    mongo_url = os.environ.get('MONGODB_URL')
    app_initialize(mongo_url)

    port = int(os.environ.get('PORT', 5000))
    try:
        app.run(host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print "Stopped by keybord interrupt."
    except:
        print "Unexpected error:", sys.exc_info()[0]
        raise
    finally:
        print('Finalizing...')
        app_terminate()


main()

# http://flask.pocoo.org/docs/0.10/quickstart/#static-files
# http://stackoverflow.com/questions/20646822/how-to-serve-static-files-in-flask
# http://stackoverflow.com/questions/13714205/deploying-flask-app-to-heroku
