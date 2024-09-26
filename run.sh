#!/bin/bash
# Usage: bash -x run.sh [-b branch name to build from] [-i image name] [-c container name]
#                       [-d docker command i.e., "docker" or "sudo docker"] [-p host port to run on]
#                       [-s true, if want to skip ssl cert configuration, otherwise omit this parameter]
# Example1: bash -x run.sh -b ctkp
# Example2: bash -x run.sh -i myimage -c mycontainer -d docker -s true -p 9990

set -e  # Stop on error

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Specify default values for optional parameters
docker_command="sudo docker"
skip_ssl=false
branch=""
host_port="9990"
image_name=ploverimage
container_name=plovercontainer

# Override defaults with values from any optional parameters provided
while getopts "i:c:d:b:s:p:" flag; do
case "$flag" in
    i) image_name=$OPTARG;;
    c) container_name=$OPTARG;;
    d) docker_command=$OPTARG;;
    b) branch=$OPTARG;;
    s) skip_ssl=$OPTARG;;
    p) host_port=$OPTARG;;
esac
done

# Check out the requested branch, if one was given
cd ${SCRIPT_DIR}
if [ ${branch} ]
then
  git fetch
  git checkout ${branch}
  git pull origin ${branch}
fi

# Build the docker image
${docker_command} build -t ${image_name} .

# Stop/remove conflicting containers (with same name or running at our port); thanks https://stackoverflow.com/a/56953427
set +e  # Don't stop on error
${docker_command} stop ${container_name}
${docker_command} rm ${container_name}
for container_id in $(${docker_command} ps -q)
do
  if [[ $(${docker_command} port "${container_id}") == *"${host_port}"* ]]
  then
    echo "Stopping container ${container_id} that was running at port ${host_port}"
    ${docker_command} stop "${container_id}"
    ${docker_command} rm "${container_id}"
  fi
done
set -e  # Stop on error

# Run the docker container
if [ ${skip_ssl} == "true" ]
then
  # Skip configuring SSL certs if those aren't wanted
  ${docker_command} run -d --name ${container_name} -p ${host_port}:80 ${image_name}
else
  domain_name=$(head -n 1 ${SCRIPT_DIR}/domain_name.txt)
  # Ensure our SSL cert is current and load it into the container (on run)
  sudo certbot renew
  cert_file_path=/etc/letsencrypt/live/${domain_name}/fullchain.pem
  key_file_path=/etc/letsencrypt/live/${domain_name}/privkey.pem
  cp ${SCRIPT_DIR}/app/nginx_ssl_template.conf ${SCRIPT_DIR}/app/nginx.conf
  # Plug the proper domain name into the nginx config file
  sed -i -e 's/{{domain_name}}/${domain_name/g' ${SCRIPT_DIR}/app/nginx.conf
  ${docker_command} run -v ${cert_file_path}:${cert_file_path} -v ${key_file_path}:${key_file_path} -d --name ${container_name} -p ${host_port}:443 ${image_name}
fi

# Clean up unused/stopped docker items
${docker_command} container prune --force
${docker_command} image prune --force --all
${docker_command} builder prune --force --all
