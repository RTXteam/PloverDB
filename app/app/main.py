# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24
import os
import sys
import time

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
