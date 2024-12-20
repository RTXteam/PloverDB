# PloverDB

Plover is an **in-memory** Python-based platform for hosting/serving Biolink-compliant knowledge graphs as **[TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) APIs**.

In answering queries, Plover abides by all **Translator Knowledge Provider reasoning requirements**; it also can normalize the underlying graph and convert query node IDs to the proper equivalent identifiers for the given knowledge graph. 

Plover accepts TRAPI query graphs at its `/query` endpoint, which include:

1. **Single-hop** query graphs: `(>=1 ids)--[>=0 predicates]--(>=0 categories, >=0 ids)`
2. **Edge-less** query graphs: Consist only of query nodes (all of which must have ids specified)

The knowledge graph to be hosted needs to be in a Biolink-compliant, KGX-style format with separate nodes and edges files; both **TSV** and **JSON Lines** formats are supported. See [this section](#nodes-and-edges-files) for more info.

You must provide **URLs** from which the **nodes/edges files** can be downloaded in a **config JSON file** in `PloverDB/app/` (e.g., `config_kg2c.json`). The config file includes a number of settings that can be customized and also defines the way in which node/edge properties should be loaded into **TRAPI attributes**. See [this section](#config-file) for more info.

Note that a single Plover app can host/serve **multiple KPs** - each KP is exposed at its own endpoint (e.g., `/ctkp`, `/dakp`). See [this section](#how-to-deploy-a-new-kp-to-an-existing-plover) for more info.



## Table of Contents
1. [How to run](#how-to-run)
   1. [How to run Plover locally (dev)](#how-to-run-plover-locally-dev)
   1. [How to deploy Plover](#how-to-deploy-plover)
1. [How to test](#how-to-test)
1. [Provided endpoints](#provided-endpoints)
1. [Input files](#input-files)
   1. [Nodes and edges files](#nodes-and-edges-files)
   1. [Config file](#config-file)
1. [Debugging](#debugging)



## How to run

**First**, you need to **install Docker** if you don't already have it.
* For Ubuntu 20.04, try `sudo apt-get install -y docker.io`
* For Mac, `brew install --cask docker` worked for me with macOS Big Sur

### How to run Plover locally (dev)

To run Plover locally for development:

1. Clone/fork this repo and navigate into it (`cd PloverDB/`)
1. Edit the config file at `/app/config_kg2c.json` for your particular graph (more info in [this section](#config-file))
1. Run the following command:
    * `bash -x run.sh -s true`

This will build a Plover Docker image and run a container off of it, publishing it at port 9990 (`http://localhost:9990`). The `-s true` parameter tells Plover to skip configuring SSL certificates.

Note that by default, this script will use the `sudo docker` command; use the optional `-d` parameter to specify a different docker command (e.g., `bash -x run.sh -s true -d docker` if the docker command you use on your machine is `docker` instead of `sudo docker`).

See [this section](how-to-test) for details on using/testing your Plover.

### How to deploy Plover

_NOTE: This section provides generalized info about deploying Plover; for deployment info specific to the RTX/ARAX/KG2 team, see the [this page](https://github.com/RTXteam/PloverDB/wiki/Deployment-how-tos) in the Plover wiki._

We deploy Plover on Ubuntu AWS EC2 machines; Ubuntu 22 and 18 have both been verified to work. The size/type of instance you'll need will depend on the size/contents of your graph (the RTX-KG2c knowledge graph has ~7 million nodes and ~30 million edges and requires a 128GiB RAM instance; we use an `r5a.4xlarge`).

#### Steps to be done once, at initial setup for a new instance:

1. Make sure ports `9990`, `80`, and `443` are open
1. Install SSL certificates and set them up for auto-renewal:
   1. `sudo snap install --classic certbot`
   1. `sudo ln -s /snap/bin/certbot /usr/bin/certbot`
   1. `sudo certbot certonly --standalone`
      1. Enter your instance's domain name (e.g., `multiomics.rtx.ai`) as the domain to be certified. You can optionally also list any `CNAME`s for the instance separated by commas (e.g., `multiomics.rtx.ai,ctkp.rtx.ai`).
   1. Verify the autorenewal setup by doing a dry run of certificate renewal:
      1. `sudo certbot renew --dry-run`
1. Clone/fork the PloverDB repo and `cd` into `PloverDB/`
1. Create a `domain_name.txt` file in `/app/` (plug in your domain name in place of `multiomics.rtx.ai` - needs to be the same domain name entered in the step above when configuring certbot):
   1. `echo "multiomics.rtx.ai" > /app/domain_name.txt`

#### Steps to build Plover once initial setup is complete:

1. `cd PloverDB/`
1. Edit the config file at `/app/config_kg2c.json` for your graph
   1. Most notably, you need to point to nodes/edges files for your graph in TSV or JSON Lines KGX format
   1. We suggest also changing the name of this file for your KP (e.g., `config_mykp.json`); the default template is for RTX-KG2c
   1. More info on the config file contents is provided in [this section](#config-file)
1. Run `bash -x run.sh`

After the build completes and the container finishes loading, your Plover will be accessible at something like https://multiomics.rtx.ai:9990 (plug in your own domain name).

See [this section](how-to-test) for details on using/testing your Plover.

#### Automatic deployment methods

There are a couple options for automatic or semi-automatic deployment of your Plover service:

**If for an ITRB deployment**, ask ITRB to set up continuous deployment for your fork/branch of the Plover repo, such that committing code to that branch (i.e., updating your config file(s))  will automatically trigger a rebuild of the ITRB application.

**If for a self-hosted deployment**, you can use Plover's built-in remote deployment server. You can do this like so:
1. On the host instance:
    1. Add a `config_secrets.json` file in the root `PloverDB/` directory. Its contents should look something like this (where you plug in the usernames/API keys that should have deployment permissions): `{"api-keys": {"my-secret-api-key": "myusername"}}`. Note that you can make the key and username whatever you would like.
    1. Start the rebuild server by running `fastapi run PloverDB/rebuild_main.py` (you may want to do this in a `screen` session or the like)
1. From any machine, you can then trigger a deployment/rebuild by submitting a request to the `/rebuild` endpoint like the following, adapted for your own instance name/username/API key/branch:
```
curl -X 'POST' \
   'http://multiomics.rtx.ai:8000/rebuild' \
   -H 'accept: application/json' \
   -H 'Content-Type: application/json' \
   -H 'Authorization: Bearer my-secret-api-key' \
   -d '{
   "branch": "mybranchname"
   }'
```
When processing such a request, the app pulls the latest code from whatever branch you specify and then does a fresh Docker rebuild of the main Plover service.

#### How to deploy a new KP to an existing Plover

If you want your Plover instance to serve **multiple knowledge graphs/KPs**, you can control those using Plover's config files. **Each KP should have its own config file in `PloverDB/app/`.** Plover will then automatically expose one KP service per such config file, at the `endpoint_name` specified in each config file.

So this means, if you have an existing Plover instance and you want to add an additional KP service to it, all you need to do is:

1. Add another config file for the new KP in `PloverDB/app/`
   1. We suggest creating a copy of an existing KP config file, editing it for the new KP, and renaming it to something like `config_mykp.json`
1. Rebuild/redeploy Plover

The new KP will then be available at the `endpoint_name` you specify in your new config file. For our example, that would be at `/mykp`, so to query that endpoint, we would send requests to `https://kg2cplover.rtx.ai:9990/mykp/query` (sub in your own domain name in place of 'kg2cplover.rtx.ai').

#### For ITRB

Instructions tailored for ITRB deployments:

Assuming an Ubuntu instance with Docker installed and SSL certificates already handled, simply run (from the desired branch):
```
sudo docker build -t ploverimage .
sudo docker run -d --name plovercontainer -p 9990:443 ploverimage
```



## How to test

To quickly verify that your Plover service is working, you can check a few endpoints (**plug in your domain name** in place of `kg2cplover.rtx.ai`):
   1. Navigate to https://kg2cplover.rtx.ai:9990/code_version in your browser; it should display information about the build
   2. Naviagte to https://kg2cplover.rtx.ai:9990/get_logs in your browser; it should display log messages from Plover and uwsgi
   3. Navigate to https://kg2cplover.rtx.ai:9990/meta_knowledge_graph in your browser; it should display the TRAPI meta knowledge graph for your graph
   4. Navigate to https://kg2cplover.rtx.ai:9990/sri_test_triples in your browser; it should display SRI test triples for your graph

You should be able to send your Plover TRAPI query POST requests at port 9990; the URL for this would look something like: `https://yourinstance.rtx.ai:9990/query`. Or, if you are just using Plover locally: `http://localhost:9990/query`. As an example:
```
curl -X 'POST' 'https://kg2cplover.rtx.ai:9990/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'
```
Note that if you are hosting multiple KPs on this Plover, the URLs for their individual `/query` endpoints would look something like this:
```
https://multiomics.rtx.ai:9990/ctkp/query
https://multiomics.rtx.ai:9990/dakp/query
```
And similarly, as an example, other KP-specific endpoints for the `ctkp` KP would look like so:
```
https://multiomics.rtx.ai:9990/ctkp/meta_knowledge_graph
https://multiomics.rtx.ai:9990/ctkp/sri_test_triples
```



## Provided endpoints

Plover exposes all endpoints required by TRAPI, as well as a few others useful for debugging/specialized queries:
* `/query` (`POST`)
   * Accepts TRAPI queries (see [TRAPI documentation](https://github.com/NCATSTranslator/ReasonerAPI/tree/master) for info on query format)
* `/meta_knowledge_graph` (`GET`)
   * Provides the underlying graph's meta knowledge graph, as defined by TRAPI
* `/sri_test_triples` (`GET`)
   * Provides example triples - one for each meta edge in the meta knowledge graph
   * Used for testing by the Translator SRI team (and others)
* `/get_neighbors` (`POST`)
   * Returns neighbors of the input node(s), with optional category/predicate constraints
   * Example query: `{"node_ids": ["CHEMBL.COMPOUND:CHEMBL112"], "categories": ["biolink:Protein"], "predicates": ["biolink:interacts_with]}`
* `/get_edges` (`POST`)
   * Returns any edges in the underlying graph between specified pairs of nodes
   * Example query: `{"pairs": [["CHEMBL.COMPOUND:CHEMBL112", "NCBIGene:1555"], ["CHEMBL.COMPOUND:CHEMBL112", "UNII:FYS6T7F842"]]}`
* `/get_logs` (`GET`)
   * Used for debugging; returns last `N` lines of the uwsgi and Plover logs
   * You can control `N` with the `num_lines` paramater: `/get_logs?num_lines=500`
* `/code_version` (`GET`)
   * Used for debugging; shows the version of code running on the Plover instance as well as the knowledge graph version(s)
* `/healthcheck` (`GET`)
   * Simple endpoint that can be used to check whether Plover is up and running (returns an empty string)



## Input files

The only input files Plover requires are the knowledge graph (represented in KGX-style nodes/edges files) and a config file, which are detailed in the below two sections.

### Nodes and edges files

TODO

### Config file

TOOD: Note that one can have nodes/edges files present only locally - put them in /app and just list their names (instead of URLs) in the nodes/edges slots. 



## Debugging

_NOTE: Swap in your domain name in place of 'kg2cplover.rtx.ai' in the below examples._

### How to check version

If you want to see the **code version** for the `RTXteam/PloverDB`
project that was used for the running service, as well as the **versions of the knowledge graph(s)** it ingested, 
go to https://kg2cplover.rtx.ai:9990/code_version in your browser. 

Or, to access it programatically:
```
curl -L -X GET -H 'accept: application/json' https://kg2cplover.rtx.ai:9990/code_version
```

### How to view logs

To view logs in your **browser**, go to https://kg2cplover.rtx.ai:9990/get_logs. This will show information from 
the Plover and uwsgi logs. By default, the last 100 lines in each log are displayed; you can change this using 
the `num_lines` parameter - e.g., https://kg2cplover.rtx.ai:9990/get_logs?num_lines=500.

To see the logs via the **terminal** (includes all components - uwsgi, etc.), run:
 ```
 docker logs plovercontainer
```
If you want to **save** the contents of the log to a file locally, run:
```
docker logs plovercontainer >& logs/mylog.log
```
To print out the **full log files** on the terminal (useful if the container is running but the Plover service/endpoints are not working), run:
```
docker exec plovercontainer cat /var/log/ploverdb.log
docker exec plovercontainer cat /var/log/uwsgi.log
```

If you want to use **cURL** to debug PloverDB, make sure to specify the `-L` (i.e., `--location`) option for the 
`curl` command, since PloverDB seems to use redirection. Like this:
```
curl -L -X POST -d @test20.json -H 'Content-Type: application/json' -H 'accept: application/json' https://kg2cplover.rtx.ai:9990/query
```


## Credits

* Author: Amy Glen
* Inspiration/advice: Stephen Ramsey, Eric Deutsch, David Koslicki
