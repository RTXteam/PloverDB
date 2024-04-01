FROM tiangolo/uwsgi-nginx-flask:python3.8

# Increase timeout (thanks https://github.com/tiangolo/uwsgi-nginx-flask-docker/issues/120#issuecomment-459857072)
RUN echo "uwsgi_read_timeout 600;" > /etc/nginx/conf.d/custom_timeout.conf


COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

RUN apt-get update && apt-get install -y ca-certificates

RUN mkdir -p /home/nobody
ENV HOME=/home/nobody
COPY ./.git /home/nobody/.git
COPY ./app /app
RUN chown -R nobody /home/nobody
COPY test/kg2c-test.json /app/kg2c-test.json

RUN touch /var/log/ploverdb.log
RUN chown nobody /var/log/ploverdb.log

RUN touch /var/log/uwsgi.log
RUN chown nobody /var/log/uwsgi.log

RUN python /app/app/build_indexes.py
