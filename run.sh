#!/bin/bash
# Usage: bash -x run.sh [container name] [image name] [docker command e.g., "sudo docker"]

image_name="${1:-myimage}"
container_name="${2:-mycontainer}"
docker_command="${3:-docker}"

${docker_command} stop ${container_name}
${docker_command} rm ${container_name}
${docker_command} image rm ${image_name}
${docker_command} build -t ${image_name} .
${docker_command} run -d --name ${container_name} -p 9990:80 ${image_name}
