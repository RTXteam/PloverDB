import os
import sys
import time
import pygit2
import datetime
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import plover


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

start = time.time()
plover_obj = plover.PloverDB()
plover_obj.load_indexes()


@app.post('/query')
def run_query(query: dict):
    logging.info(f"In run query, query body is: {query}")
    answer = plover_obj.answer_query(query)
    return answer
    # TODO: Need to fix for fastapi..
    # if isinstance(answer, tuple):  # Indicates an error
    #     return flask.Response(answer[1], status=answer[0])
    # else:
    #     return flask.jsonify(answer)


@app.get('/meta_knowledge_graph')
def get_meta_knowledge_graph():
    return plover_obj.meta_kg


@app.get('/healthcheck')
def run_health_check():
    return ''


# def handle_error(e: Exception) -> flask.Response:
#     error_msg = str(e)
#     logging.error(error_msg)
#     response = flask.jsonify(error_msg)
#     response.status_code = 500
#     response.status = 'Internal Server Error'
#     return response


@app.get('/code_version')
def run_code_version():
    try:
        print(f"HOME: {os.environ['HOME']}", file=sys.stderr)
        repo = pygit2.Repository(os.environ['HOME'])
        repo_head_name = repo.head.name
        timestamp_int = repo.revparse_single('HEAD').commit_time
        date_str = str(datetime.date.fromtimestamp(timestamp_int))
        ret_str = f"HEAD: {repo_head_name}; Date: {date_str}"
        response = ret_str
    except Exception as e:
        response = "handle_error(e) - need to fix"  # TODO: fix
    return response


@app.get('/get_logs')
def run_get_logs():
    try:
        with open(plover.LOG_FILENAME, 'r') as f:
            log_data_plover = f.readlines()
        ret_data = {'plover': log_data_plover}
        response = ret_data
    except Exception as e:
        response = "handle_error(e) - need to fix"  # TODO: fix
    return response
