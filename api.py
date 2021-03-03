# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24
from flask import Flask, request, jsonify
from badger import BadgerDB
app = Flask(__name__)
badger = BadgerDB(is_test=True)


@app.route('/query/', methods=['POST'])
def run_query():
    query = request.json
    answer = badger.answer_query(query)
    return jsonify(answer)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=105)
