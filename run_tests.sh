#!/bin/bash

python -m unittest discover -t . -s ./test -p '*_test.py'
