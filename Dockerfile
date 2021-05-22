FROM tiangolo/uwsgi-nginx-flask:python3.8

ARG aws_access_key
ARG aws_secret_key

# Increase timeout (thanks https://github.com/tiangolo/uwsgi-nginx-flask-docker/issues/120#issuecomment-459857072)
RUN echo "uwsgi_read_timeout 120;" > /etc/nginx/conf.d/custom_timeout.conf

COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

COPY .aws /root/.aws
RUN apt-get update
RUN apt-get install -y awscli
RUN aws configure set default.region us-west-2

COPY ./app /app

RUN python /app/app/build_indexes.py
