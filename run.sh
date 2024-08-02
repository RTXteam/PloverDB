#!/bin/bash
# Usage: bash -x run.sh [image name] [container name] [docker command e.g., "docker" or "sudo docker"]

image_name="${1:-ploverimage}"
container_name="${2:-plovercontainer}"
docker_command="${3:-sudo docker}"

set +e  # Don't stop on error
${docker_command} stop ${container_name}
${docker_command} rm ${container_name}
${docker_command} image rm ${image_name}
set -e  # Stop on error

${docker_command} build -t ${image_name} .

# Run the docker container; NOTE: the '--preload' flag makes Gunicorn workers *share* (vs. copy) the central index (yay)
if [ ${image_name} == "myimage" ]
then
  # Skip configuring SSL cert if this is a test build  (TODO: use a dedicated 'test' build flag..)
  ${docker_command} run -d --name ${container_name} -p 9990:80 -e GUNICORN_CMD_ARGS="--preload" ${image_name}
else
  # Ensure our SSL cert is current and load it into the container (on run)
  sudo certbot renew
  cert_file_path=/etc/letsencrypt/live/ctkp.rtx.ai/fullchain.pem
  key_file_path=/etc/letsencrypt/live/ctkp.rtx.ai/privkey.pem
  ${docker_command} run -v ${cert_file_path}:${cert_file_path} -v ${key_file_path}:${key_file_path} -d --name ${container_name} -p 9990:443 -e GUNICORN_CMD_ARGS="--preload --keyfile=${key_file_path} --certfile=${cert_file_path}" -e PORT=443 ${image_name}
fi
