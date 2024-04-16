import os
import sys
import time
import pygit2
import datetime
import logging
import flask
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import plover


# Thank you https://towardsdatascience.com/creating-restful-apis-using-flask-and-python-655bad51b24

app = flask.Flask(__name__)
start = time.time()
plover_obj = plover.PloverDB()
plover_obj.load_indexes()


@app.route('/query', methods=['POST'])
def run_query():
    query = flask.request.json
    answer = plover_obj.answer_query(query)
    return flask.jsonify(answer)


@app.route('/healthcheck', methods=['GET'])
def run_health_check():
    return ''


def handle_error(e: Exception) -> flask.Response:
    error_msg = str(e)
    logging.error(error_msg)
    response = flask.jsonify(error_msg)
    response.status_code = 500
    response.status = 'Internal Server Error'
    return response


@app.route('/code_version', methods=['GET'])
def run_code_version():
    try:
        print(f"HOME: {os.environ['HOME']}", file=sys.stderr)
        repo = pygit2.Repository(os.environ['HOME'])
        repo_head_name = repo.head.name
        timestamp_int = repo.revparse_single('HEAD').commit_time
        date_str = str(datetime.date.fromtimestamp(timestamp_int))
        ret_str = f"HEAD: {repo_head_name}; Date: {date_str}"
        response = flask.jsonify(ret_str)
    except Exception as e:
        response = handle_error(e)
    return response


@app.route('/get_logs', methods=['GET'])
def run_get_logs():
    try:
        with open(plover.LOG_FILENAME, 'r') as f:
            log_data_plover = f.readlines()
        with open('/var/log/uwsgi.log', 'r') as f:
            log_data_uwsgi = f.readlines()
        ret_data = {'plover': log_data_plover,
                    'uwsgi': log_data_uwsgi}
        response = flask.jsonify(ret_data)
    except Exception as e:
        response = handle_error(e)
    return response
