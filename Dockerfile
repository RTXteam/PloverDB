FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt && adduser ploveruser

ENV HOME=/home/ploveruser
COPY ./.git /home/ploveruser/.git
RUN chown -R ploveruser /home/ploveruser/.git
COPY ./app /app
RUN chown -R ploveruser /app

RUN touch /var/log/ploverdb.log
RUN touch /var/log/gunicorn_error.log
RUN touch /var/log/gunicorn_access.log
RUN chown ploveruser /var/log/ploverdb.log
RUN chown ploveruser /var/log/gunicorn_error.log
RUN chown ploveruser /var/log/gunicorn_access.log

USER ploveruser

RUN python /app/app/build_indexes.py
