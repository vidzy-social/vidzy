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
from app import app, session, mysql, Comment, SQLAlchemy_session

@app.route('/login', methods=['POST', 'GET'])
def login_page():
    if "username" in session:
        return "<script>window.location.href='/';</script>"

    if "username" in request.form:
        username = request.form["username"]
        password = request.form["password"]

        mycursor = mysql.connection.cursor()

        mycursor.execute(
            "SELECT * FROM users WHERE username = %s;", (username,))

        myresult = mycursor.fetchall()

        if len(myresult) == 0:
            return "<br><h1 style='text-align:center'>User doesn't exist. Would you like to <a href='/register'>sign up?</a></h1>"

        for x in myresult:
            if x["password"] == hashlib.sha256(password.encode()).hexdigest():
                session["username"] = username
                session["id"] = x["id"]
                session["user"] = x
                return "<script>window.location.href='/';</script>"
            return "<script>window.location.href='/login';</script>"
    else:
        return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return app.make_response(redirect(url_for("login_page")))

@app.route('/register', methods =['GET', 'POST'])
def register():
    if "username" in session:
        return "<script>window.location.href='/';</script>"

    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in request.form:
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM users WHERE username = %s', (username, ))
        account = cursor.fetchone()
        if account:
            msg = 'Account already exists!'
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
        elif not re.match(r'[A-Za-z0-9]+', username):
            msg = 'Username must contain only characters and numbers!'
        elif not username or not password or not email:
            msg = 'Please fill out the form!'
        else:
            cursor.execute('INSERT INTO users (`username`, `password`, `email`) VALUES (%s, %s, %s)', (username, hashlib.sha256(password.encode()).hexdigest(), email, ))
            mysql.connection.commit()
            msg = 'You have successfully registered! <a href="/login">Click here to login</a>'
    elif request.method == 'POST':
        msg = 'Please fill out the form!'
    return render_template('register.html', msg = msg)
