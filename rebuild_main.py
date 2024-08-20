"""
This is a server/app separate from the main Plover app that simply listens for a post request to trigger a rebuild
of the main Plover app. It requires authentication using an API key. A request to trigger a rebuild should look like:
curl -X 'POST' \
  'http://ctkp.rtx.ai:8000/rebuild' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer MY-API-KEY' \
  -d '{
   "branch": "ctkp",
   "port": "9990"
}'
"""
import json
import os
import time

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from starlette import status

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Thank you https://stackoverflow.com/a/67943917 for auth code
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Ensure the request is authenticated
def auth_request(token: str = Depends(oauth2_scheme)) -> bool:
    with open(f"{SCRIPT_DIR}/config_secrets.json", "r") as secrets_file:
        config_secrets = json.load(secrets_file)
    authenticated = token in config_secrets["api-keys"]
    return authenticated


app = FastAPI()


@app.get("/")
async def root():
    return ("This is the app for triggering rebuilds of Plover. Submit an "
            "authenticated request to the /rebuild endpoint.")


@app.post('/rebuild')
def rebuild_app(body: dict, authenticated: bool = Depends(auth_request)):
    if authenticated:
        branch_name = body.get("branch")
        if not branch_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="422 ERROR: Request is missing 'branch' parameter. You must specify the name of"
                                       " the branch in the PloverDB Github repo that you want to do this build from. "
                                       "e.g., 'ctkp'")
        else:
            start = time.time()
            host_port = body.get("port", "9990")
            docker_command = body.get("docker_command", "sudo docker")
            image_name = f"ploverimage{f'-{branch_name}' if branch_name else ''}"
            container_name = f"plovercontainer{f'-{branch_name}' if branch_name else ''}"
            skip_ssl = body.get("skip_ssl", False)
            os.system(f"bash -x {SCRIPT_DIR}/run.sh -b {branch_name} -i {image_name} -c {container_name} "
                      f"-p {host_port} -d '{docker_command}' -s {skip_ssl}")
            return {"message": f"Rebuild done; live at port {host_port}. Took {round((time.time() - start) / 60, 1)} minutes."}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="401 ERROR: Not authenticated")
