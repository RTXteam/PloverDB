FROM tiangolo/uwsgi-nginx-flask:python3.11

# Increase timeout (thanks https://github.com/tiangolo/uwsgi-nginx-flask-docker/issues/120#issuecomment-459857072)
RUN echo "uwsgi_read_timeout 600;" > /etc/nginx/conf.d/custom_timeout.conf

ENV UWSGI_CHEAPER 8
ENV UWSGI_PROCESSES 16

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

RUN apt-get update && apt-get install -y ca-certificates

RUN mkdir -p /home/nobody
ENV HOME=/home/nobody
COPY ./.git /home/nobody/.git
COPY ./app /app
RUN chown -R nobody /home/nobody

RUN touch /var/log/ploverdb.log
RUN chown nobody /var/log/ploverdb.log

RUN touch /var/log/uwsgi.log
RUN chown nobody /var/log/uwsgi.log

RUN python /app/app/build_indexes.py
