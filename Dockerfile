FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10

ARG nodes_url
ARG edges_url
ARG biolink_version

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

RUN mkdir -p /home/nobody
ENV HOME=/home/nobody
COPY ./.git /home/nobody/.git
COPY ./app /app
RUN chown -R nobody /home/nobody

RUN touch /var/log/ploverdb.log
RUN chown nobody /var/log/ploverdb.log

RUN python /app/app/build_indexes.py -n ${nodes_url} -e ${edges_url} -b ${biolink_version}
