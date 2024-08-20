FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

RUN mkdir -p /home/nobody
ENV HOME=/home/nobody
COPY ./.git /home/nobody/.git
COPY ./app /app
RUN chown -R nobody /home/nobody
RUN chown -R nobody /app

RUN touch /var/log/ploverdb.log
RUN chown nobody /var/log/ploverdb.log

USER nobody

RUN python /app/app/build_indexes.py
