#!/bin/bash
# Usage: bash -x run.sh [-n public web url to nodes file] [-e public web url to edges file] [-i image name] [-c container name] [-d docker command e.g., "docker" or "sudo docker"]
# Example1: bash -x run.sh -n https://db.systemsbiology.net/gestalt/KG/clinical_trials_kg_nodes_v2.2.9.tsv -e https://db.systemsbiology.net/gestalt/KG/clinical_trials_kg_edges_v2.2.9.tsv
# Example2: bash -x run.sh -i myimage -c mycontainer -d docker
# If URLS to remote nodes/edges files are not provided, nodes/edges files must be present locally in PloverDB/app/

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Specify default image name, container name, and docker command to use (can be overridden by flag params)
image_name=ploverimage
container_name=plovercontainer
docker_command="sudo docker"

while getopts "n:e:i:c:d:b:" flag; do
case "$flag" in
    n) nodes_file_url=$OPTARG;;
    e) edges_file_url=$OPTARG;;
    b) biolink_version=$OPTARG;;
    i) image_name=$OPTARG;;
    c) container_name=$OPTARG;;
    d) docker_command=$OPTARG;;
esac
done

set +e  # Don't stop on error
${docker_command} stop ${container_name}
${docker_command} rm ${container_name}
${docker_command} image rm ${image_name}
set -e  # Stop on error

cd ${SCRIPT_DIR}
${docker_command} build --build-arg nodes_url=${nodes_file_url} --build-arg edges_url=${edges_file_url} --build-arg biolink_version=${biolink_version} -t ${image_name} .

# Run the docker container; NOTE: the '--preload' flag makes Gunicorn workers *share* (vs. copy) the central index (yay)
if [ ${docker_command} == "docker" ]  # TODO: this is hacky, use a dedicated 'test' build flag or something..
then
  # Skip configuring SSL cert if this is a test build
  ${docker_command} run -d --name ${container_name} -p 9990:80 -e GUNICORN_CMD_ARGS="--preload" ${image_name}
else
  # Ensure our SSL cert is current and load it into the container (on run)
  sudo certbot renew
  cert_file_path=/etc/letsencrypt/live/ctkp.rtx.ai/fullchain.pem
  key_file_path=/etc/letsencrypt/live/ctkp.rtx.ai/privkey.pem
  ${docker_command} run -v ${cert_file_path}:${cert_file_path} -v ${key_file_path}:${key_file_path} -d --name ${container_name} -p 9990:443 -e GUNICORN_CMD_ARGS="--preload --keyfile=${key_file_path} --certfile=${cert_file_path}" -e PORT=443 ${image_name}
fi
