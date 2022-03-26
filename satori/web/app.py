#!/usr/bin/env python
# -*- coding: utf-8 -*-

# run with:
# sudo nohup /app/anaconda3/bin/python app.py > /dev/null 2>&1 &

'''
this is the backend server which listens to messages from and sends messages
to the nodejs server so it can communicate with the streamr light client.

Communication model
NodeJS Streamr Light Client <-> Python Flask <-> DataManager <-> ModelManager

Frankly, this flask app could be considered the front end if we want. Whatever
is easiest to implement.


'''
import os
import sys
import random
import secrets
import satori
import requests
import pandas as pd
import datetime as dt
from flask import Flask, url_for, render_template, redirect, jsonify
from flask import send_from_directory, session, request, flash, Markup
#from flask_mobility import Mobility
from waitress import serve


###############################################################################
## Globals ####################################################################
###############################################################################

app = Flask(__name__)
#Mobility(app)
app.config['SECRET_KEY'] = secrets.token_urlsafe(16)
CWD = os.path.dirname(os.path.abspath(__file__))
PORT = 24685

ENGINE = satori.getLearner(path=None)

###############################################################################
## Functions ##################################################################
###############################################################################

def get_user_id():
    return session.get('user_id', '0')

###############################################################################
## Errors #####################################################################
###############################################################################

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

###############################################################################
## Routes - static ############################################################
###############################################################################

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static/img/favicon'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon')

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)


@app.route('/generated/<path:path>')
def send_generated(path):
    return send_from_directory('generated', path)

@app.route('/home')
def home():
    return redirect(url_for('dashboard'))

@app.route('/index')
def index():
    return redirect(url_for('dashboard'))

@app.route('/test')
def test():
    # print(session)
    # print(request)
    print(request.MOBILE)
    return render_template('test.html')

@app.route('/kwargs')
def kwargs():
    ''' ...com/kwargs?0-name=widget_name0&0-value=widget_value0&0-type=widget_type0&1-name=widget_name1&1-value=widget_value1&1-#type=widget_type1 '''
    kwargs = {}
    for i in range(25):
        if request.args.get(f'{i}-name') and request.args.get(f'{i}-value'):
            kwargs[request.args.get(f'{i}-name')] = request.args.get(f'{i}-value')
            kwargs[request.args.get(f'{i}-name') + '-type'] = request.args.get(f'{i}-type')
    return jsonify(kwargs)

@app.route('/ping', methods=['GET'])
def ping():
    from datetime import datetime
    return jsonify({'now': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

###############################################################################
## Routes - dashboard #########################################################
###############################################################################

@app.route('/')
@app.route('/dashboard')
def dashboard():
    ''' 
    UI
    - send to setup process if first time running the app...
    - show earnings
    - access to wallet
    - access metrics for published streams
        (which streams do I have?)
        (how often am I publishing to my streams?)
    - access to data management (monitor storage resources)
    - access to model metrics 
        (show accuracy over time)
        (model inputs and relative strengths)
        (access to all predictions and the truth)
    '''
    resp = {}
    return render_template('dashboard.html', **resp)

###############################################################################
## Routes - subscription ######################################################
###############################################################################

@app.route('/subscription/update')
def update():
    ''' from streamr - datastream has a new observation
    upon a new observation of a datastream, the nodejs app will send this 
    python flask app a message on this route. The flask app will then pass the
    message to the data manager, specifically the scholar (and subscriber)
    threads by adding it to the appropriate subject. (the scholar, will add it
    to the correct table in the database history, notifying the subscriber who
    will, if used by any current best models, notify that model's predictor
    thread via a subject that a new observation is available by providing the
    observation directly in the subject).
    
    This app needs to create the DataManager, ModelManagers, and Learner in
    in order to have access to those objects. Specifically the DataManager,
    we need to be able to access it's BehaviorSubjects at data.newData
    so we can call .on_next() here to pass along the update got here from the 
    Streamr LightClient, and trigger a new prediction.
    '''
    resp = {}
    return render_template('dashboard.html', **resp)

###############################################################################
## Routes - history ###########################################################
# we may be able to make these reque
###############################################################################

@app.route('/history/request')
def publsih():
    ''' to streamr - create a new datastream to publish to '''
    resp = {}
    return render_template('dashboard.html', **resp)


@app.route('/history/')
def publsihMeta():
    ''' to streamr - publish to a stream '''
    resp = {}
    return render_template('dashboard.html', **resp)

###############################################################################
## Entry ######################################################################
###############################################################################

if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=PORT)
# sudo nohup /app/anaconda3/bin/python app.py > /dev/null 2>&1 &