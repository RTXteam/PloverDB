FROM tiangolo/uwsgi-nginx-flask:python3.8

# Increase timeout (thanks https://github.com/tiangolo/uwsgi-nginx-flask-docker/issues/120#issuecomment-459857072)
RUN echo "uwsgi_read_timeout 120;" > /etc/nginx/conf.d/custom_timeout.conf

COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

COPY ./app /app
COPY test/kg2c-test.json /app/kg2c-test.json

RUN python /app/app/build_indexes.py
