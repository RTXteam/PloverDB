# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24
from flask import Flask, request
from badger import BadgerDB
app = Flask(__name__)
badger = BadgerDB(is_test=True)


@app.route('/query/', methods=['POST'])
def query():
    json_query = request.json
    return badger.answer_query(json_query)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=105)
