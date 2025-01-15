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

@app.route("/comments/<shortid>")
def comments_route(shortid):
    comments = SQLAlchemy_session.query(Comment).filter(Comment.short_id == shortid).order_by(Comment.path)

    try:
        return render_template("comments.html", comments=comments)
    except sqlalchemy.exc.PendingRollbackError:
        SQLAlchemy_session.rollback()
        return render_template("comments.html", comments=comments)

@app.route("/send_comment")
def send_comment_page():
    if "user" not in session:
        return "NotLoggedIn"

    parent_comment = request.args.get("parent", default=None)
    if parent_comment is not None:
        parent_comment = SQLAlchemy_session.query(Comment).get(int(parent_comment))

    shortid = request.args.get("shortid")

    cursor = mysql.connection.cursor()
    cursor.execute("SELECT count(*) comment_count FROM `comments` WHERE short_id = %s AND user_id = %s;", (shortid, session["user"]["id"]))
    comment_count = int(cursor.fetchall()[0]["comment_count"])

    if comment_count >= 40:
        return "TooManyComments"

    mycomment = Comment(text=request.args.get("txt"), author=session["user"]["id"], short_id=int(shortid), parent=parent_comment)

    with app.app_context():
        mycomment.save()

    for comment in SQLAlchemy_session.query(Comment).order_by(Comment.path):
        print('{}{}: {}'.format('  ' * comment.level(), comment.author, comment.text))

    return "Success"
