import hashlib
import json
import re
import os
import math
import uuid
import collections
from collections import defaultdict
import random
import time

from operator import itemgetter
from datetime import datetime
from urllib.parse import urlparse
import urllib.parse

import requests
import nh3
import boto3

from flask import *

from flask_mysqldb import MySQL
from flask_htmlmin import HTMLMIN

from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend as crypto_default_backend

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import sqlalchemy

from moviepy import VideoFileClip

import vidzyconfig
from app import app, session, mysql

@app.route("/shorts/<short>/analytics/public")
def video_publicanalytics(short):
    if "user" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()

    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) like_count FROM `shorts` p  WHERE (`id` = %s);", (short,))
    short = cur.fetchall()[0]

    return render_template('public_vid_analytics.html', session=session, short=short, time_uploaded=time)

@app.route("/shorts/<short_id>/analytics/private")
def video_privateanalytics(short_id):
    if "user" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()

    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) like_count FROM `shorts` p  WHERE (`id` = %s);", (short_id,))
    short = cur.fetchall()
    if len(short) == 0:
        return "Video not found."
    short = short[0]

    if session["user"]["id"] != short["user_id"]:
        return "<script>window.location.href='/';</script>"

    return render_template('private_vid_analytics.html', session=session, short=short)

@app.route("/shorts/<short>")
def short_page(short):
    if "username" not in session:
        return "<script>window.location.href='/login';</script>"

    cur = mysql.connection.cursor()
    cur.execute("SELECT *, (SELECT count(*) FROM `likes` WHERE short_id = p.id) likes FROM shorts p WHERE id = %s;", (short,))
    rv = cur.fetchall()[0]

    return render_template('short.html', short=rv, session=session, logged_in = "username" in session)
