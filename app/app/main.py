# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24
import os
import sys
import time

from flask import Flask, request, jsonify
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB


app = Flask(__name__)
print("Starting to load data and build indexes..")
start = time.time()
plover = PloverDB()
plover.load_indexes()
print(f"Finished loading data. Took {round((time.time() - start) / 60, 1)} minutes.")


@app.route('/query/', methods=['POST'])
def run_query():
    query = request.json
    answer = plover.answer_query(query)
    return jsonify(answer)
