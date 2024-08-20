FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

RUN mkdir -p /home/nobody
ENV HOME=/home/nobody
COPY ./.git /home/nobody/.git
COPY ./app /app

RUN touch /var/log/ploverdb.log
RUN touch /var/log/gunicorn_error.log
RUN touch /var/log/gunicorn_access.log

RUN python /app/app/build_indexes.py
