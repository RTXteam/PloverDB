"""
This is a server/app separate from the main Plover app that simply listens for a post request to trigger a rebuild
of the main Plover app. It requires authentication using an API key. A request to trigger a rebuild should look like:
curl -X 'POST' \
  'https://ctkp.rtx.ai:8000/rebuild' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer MY-API-KEY' \
  -d '{
   "nodes_file_url":"https://db.systemsbiology.net/gestalt/KG/clinical_trials_kg_nodes_v2.2.9.tsv",
   "edges_file_url":"https://db.systemsbiology.net/gestalt/KG/clinical_trials_kg_edges_v2.2.9.tsv",
   "biolink_version":"4.2.1"
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
        # Do the rebuild
        print(f"Rebuild triggered. {body}")
        branch_name = body.get("branch")
        if not branch_name:
            raise ValueError("Must provide branch name!!")  # TODO: return an http error here..
        else:
            start = time.time()
            os.system(f"bash -x {SCRIPT_DIR}/run.sh -b {branch_name}")
            return {"message": f"Rebuild done. Took {round(time.time() - start)} seconds."}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
