#!/bin/bash
# Usage: bash -x run.sh [-b branch name to build from] [-i image name] [-c container name]
#                       [-d docker command i.e., "docker" or "sudo docker"] [-p host port to run on]
#                       [-C to use docker cache (faster, but may miss code changes)]
# Example1: bash -x run.sh -b ctkp
# Example2: bash -x run.sh -i myimage -c mycontainer -d docker -p 9990
# Example3: bash -x run.sh -C  # Use Docker cache (faster, may miss code changes)
#
# NOTE: SSL/HTTPS is now handled outside the container (e.g., by a reverse proxy on the host
#       or by a Kubernetes ingress controller). The container only serves HTTP on port 80.

set -e  # Stop on error

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Specify default values for optional parameters
branch=""
host_port="9991"  # Internal port; nginx handles external 9990 with SSL
image_name=ploverimage
container_name=plovercontainer
no_cache="--no-cache"  # Default to fresh builds; use -C flag to enable cache
# Auto-detect if "docker" can run without sudo
if docker info &>/dev/null; then
  docker_command="docker"
else
  docker_command="sudo docker"
fi

# Override defaults with values from any optional parameters provided
while getopts "i:c:d:b:p:C" flag; do
case "$flag" in
    i) image_name=$OPTARG;;
    c) container_name=$OPTARG;;
    d) docker_command=$OPTARG;;
    b) branch=$OPTARG;;
    p) host_port=$OPTARG;;
    C) no_cache="";;  # Use cache (faster, but may miss code changes)
esac
done

# Check out the requested branch, if one was given
cd ${SCRIPT_DIR}
if [ ${branch} ]; then
  git fetch
  git checkout ${branch}
  git pull origin ${branch}
fi

# Build the docker image
${docker_command} build ${no_cache} -t ${image_name} .

# Stop/remove conflicting containers (with same name or running at our port); thanks https://stackoverflow.com/a/56953427
set +e  # Don't stop on error
${docker_command} stop ${container_name}
${docker_command} rm ${container_name}
for container_id in $(${docker_command} ps -q); do
  if [[ $(${docker_command} port "${container_id}") == *"${host_port}"* ]]; then
    echo "Stopping container ${container_id} that was running at port ${host_port}"
    ${docker_command} stop "${container_id}"
    ${docker_command} rm "${container_id}"
  fi
done
set -e  # Stop on error

# Run the docker container (HTTP only - SSL handled externally if needed)
# Map 9991 -> 80 (Main App) AND 8000 -> 8000 (Rebuild Server)
${docker_command} run -d --name ${container_name} -p ${host_port}:80 -p 8000:8000 ${image_name}

# Clean up unused/stopped docker items
${docker_command} container prune --force
${docker_command} image prune --force --all
${docker_command} builder prune --force --all