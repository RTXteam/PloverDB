# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24
import os
import sys
import time
import pygit2
import datetime

from flask import Flask, request, jsonify
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB


app = Flask(__name__)
start = time.time()
plover = PloverDB()
plover.load_indexes()


@app.route('/query/', methods=['POST'])
def run_query():
    query = request.json
    answer = plover.answer_query(query)
    return jsonify(answer)


@app.route('/healthcheck/', methods=['GET'])
def run_health_check():
    return ''


@app.route('/code_version', methods=['GET'])
def run_code_version():
    repo = pygit2.Repository('.')
    repo_head_name = repo.head.name
    timestamp_int = repo.revparse_single('HEAD').commit_time
    date_str = str(datetime.date.fromtimestamp(timestamp_int))
    return jsonify(f"HEAD: {repo_head_name}; Date: {date_str}")
