# PloverDB

Plover is a fully **in-memory** Python-based platform for hosting/serving [Biolink](https://github.com/biolink/biolink-model)-compliant knowledge graphs as **[TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) web APIs**.
 
In answering queries, Plover abides by all **[Translator Knowledge Provider reasoning requirements](https://github.com/NCATSTranslator/TranslatorEngineering?tab=readme-ov-file#architecture-principles)**; it also can normalize the underlying graph and convert query node IDs to the proper equivalent identifiers for the given knowledge graph. 

Plover accepts [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) query graphs at its `/query` endpoint, which include:

1. **Single-hop** query graphs: `(>=1 ids)--[>=0 predicates]--(>=0 categories, >=0 ids)`
2. **Edge-less** query graphs: Consist only of query nodes (all of which must have ids specified)

The knowledge graph to be hosted needs to be in a [Biolink](https://github.com/biolink/biolink-model)-compliant, [KGX-style format](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) with separate nodes and edges files; both **TSV** and **JSON Lines** formats are supported. See [this section](#nodes-and-edges-files) for more info.

You must provide publicly accessible **URLs** from which the **nodes/edges files** can be downloaded in a **config JSON file** in `PloverDB/app/` (e.g., `config.json`), or you can provide your graph files locally (see [this section](#nodes-and-edges-files) for more info). The config file includes a number of settings that can be customized and also defines the way in which node/edge properties should be loaded into **[TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) Attributes**. See [this section](#config-file) for more info.

Note that a single Plover app can host/serve **multiple KPs** - each KP is exposed at its own endpoint (e.g., `/ctkp`, `/dakp`), and has its own Plover config file. See [this section](#how-to-deploy-a-new-kp-to-an-existing-plover) for more info.

## Typical EC2 instance type used for building & hosting PloverDB

The PloverDB software has been tested with the following EC2 configuration:

- **AMI:** Ubuntu Server 18.04.6 LTS (HVM), SSD Volume Type – `ami-01d4b5043e089efa9` (64-bit x86)  
- **Instance type:** `r5a.4xlarge` (16 vCPUs, 128 GiB RAM)  
- **Storage:** 300 GiB root EBS volume 
- **Security Group:** `plover-sg`, ingress TCP on ports  
  - `22`  (SSH)  
  - `80`  (HTTP)  
  - `443` (HTTPS)  
  - `8000` (alternate API/UI)  
  - `9990` (PloverDB API)  

### Host environment
- **Architecture:** x86_64 (AMD EPYC 7571)  
- **Kernel:** Linux 5.4.0-1103-aws  
- **Python (host):** CPython 3.6.9  
- **Docker (host):** 24.0.2  

### Docker container
- **Base image:** Debian 11.11  
- **Python (in-container):** CPython 3.11  
- **Exposed port:** `9990`  
- **Python dependencies:** pinned in [`requirements.txt`](https://github.com/RTXteam/PloverDB/blob/main/requirements.txt)

**Cost estimate (us-west-2 on-demand):**  
- `r5a.4xlarge` @ \$0.904/hr -> build (~1 hr) ≈ 1

## Table of Contents
1. [How to run](#how-to-run)
   1. [How to run Plover locally (dev)](#how-to-run-plover-locally-dev)
   1. [How to deploy Plover](#how-to-deploy-plover)
   1. [Memory and space requirements](#space-and-time-requirements)
1. [How to test](#how-to-test)
1. [Provided endpoints](#provided-endpoints)
1. [Input files](#input-files)
   1. [Nodes and edges files](#nodes-and-edges-files)
   1. [Config file](#config-file)
1. [Debugging](#debugging)


## How to run

**First**, you need to **install Docker** if you don't already have it.
* For Ubuntu 20.04, try `sudo apt-get install -y docker.io`
* For Mac, try `brew install --cask docker`

### How to run Plover locally (dev)

To run Plover locally for development (assuming you have installed Docker), simply:

1. Clone/fork this repo and navigate into it (`cd PloverDB/`)
1. Edit the config file at `/app/config.json` for your particular graph (more info in [this section](#input-files))
1. Run the following command:
    * `bash -x run.sh`

This will build a Plover Docker image and run a container off of it, publishing it at port 9990 (`http://localhost:9990`).

See [this section](#how-to-test) for details on using/testing your Plover.

### How to deploy Plover

_NOTE: For more deployment info specific to the RTX-KG2/ARAX team, see the [this page](https://github.com/RTXteam/PloverDB/wiki/Deployment-notes) in the Plover wiki._

Because Plover is Dockerized, it can be run on any machine with Docker installed. Our deployment instructions below assume you're using a **Linux** host machine.

The amount of memory and disk space your host instance will need depends on the size/contents of your graph. See [this section](#space-and-time-requirements) for more info on the memory/space requirements.

#### Steps to be done once, at initial setup for a new instance:

1. Make sure ports `9990`, `80`, and `443` on the host instance are open. If you're planning to use the rebuild functionality, also open port `8000`.
1. Install SSL certificates on the host instance and set them up for auto-renewal:
   1. `sudo snap install --classic certbot`
   1. `sudo ln -s /snap/bin/certbot /usr/bin/certbot`
   1. `sudo certbot certonly --standalone`
      1. Enter your instance's domain name (e.g., `multiomics.rtx.ai`) as the domain to be certified. You can optionally also list any `CNAME`s for the instance separated by commas (e.g., `multiomics.rtx.ai,ctkp.rtx.ai`).
   1. Verify the autorenewal setup by doing a dry run of certificate renewal:
      1. `sudo certbot renew --dry-run`
1. Fork the PloverDB repo (or create a new branch, if you have permissions)
1. Create a `domain_name.txt` file in `PloverDB/app/` like so:
   * `echo "multiomics.rtx.ai" > PloverDB/app/domain_name.txt`
   * (plug in your domain name in place of `multiomics.rtx.ai` - needs to be the same domain name entered in the step above when configuring certbot)

#### Steps to build Plover after initial setup is complete:

1. Edit the config file at `PloverDB/app/config.json` for your graph
   1. Most notably, you need to point to nodes/edges files for your graph in TSV or JSON Lines [KGX format](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md)
   1. We suggest also **changing the name of this file** for your KP (e.g., `config_mykp.json`); just ensure that the file name starts with `config` and ends with `.json`
   1. Push this change to your PloverDB fork/branch
   1. More info on the config file contents is provided in [this section](#config-file)
1. Run `bash -x PloverDB/run.sh`

After the build completes and the container finishes loading, your Plover will be accessible at something like https://multiomics.rtx.ai:9990 (plug in your own domain name).

See [this section](#how-to-test) for details on using/testing your Plover.

#### Automatic deployment methods

There are a couple options for automatic or semi-automatic deployment of your Plover service:

_If for an NCATS Translator ITRB deployment_, ask ITRB to set up continuous deployment for your fork/branch of the Plover repo, such that committing code to that branch (i.e., updating your config file(s))  will automatically trigger a rebuild of the ITRB application.

_Otherwise, for a self-hosted deployment_, you can use Plover's built-in remote deployment server. You can do this like so:
1. On the host instance:
    1. Add a `config_secrets.json` file in the root `PloverDB/` directory. Its contents should look something like this (where you plug in the usernames/API keys that should have deployment permissions):
       1. `{"api-keys": {"my-secret-api-key": "myusername"}}`
       2. Note that you can make the key and username whatever you would like.
    1. Start up a Python environment and do `pip install -r PloverDB/requirements.txt`
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

### Space and time requirements

The amount of memory and disk space your host instance will need to run Plover and Plover's build time depend on the size/contents of your graph(s).

Some example graphs and their time/space usage are provided in the below table.

| Plover deployment                                     | Number of KGs | KG size details                           | Memory consumption[a] | Disk space consumption | Instance type used                                    | Build time |
|-------------------------------------------------------|---------------|-------------------------------------------|------------------------|------------------------|-------------------------------------------------------|------------|
| [RTX-KG2 KP](https://kg2cploverdb.ci.transltr.io) | 1             | ~7 million nodes, ~30 million edges       | 90 GiB                | 25G                    | AWS EC2 `r5a.4xlarge` (128 GiB RAM), 100GB disk space | ~1 hour    |
| [Multiomics KPs](https://multiomics.rtx.ai:9990)      | 4             | Combined, ~100k nodes, ~500k edges        | 2.5 GiB               | 6G                     | AWS EC2 `t4g.xlarge` (16 GiB RAM), 20GB disk space    | ~5 minutes |



_[a]: These are approximate values when the service is at rest; this will increase somewhat under heavy usage, by up to ~10% based on our experience._



## How to test

To quickly verify that your Plover service is working, you can check a few endpoints. 

For all of these examples, the **base URL** for your service will be either:
1. http://localhost:9990 if you are running Plover locally, or 
2. something like https://multiomics.rtx.ai:9990 if you have deployed Plover somewhere (**plug in your domain name** in place of `multiomics.rtx.ai`)

Using the proper base URL, check the following endpoints (either by viewing them in your browser or accessing them programmatically):

| Endpoint            | Request Type | Description                                                                                        |
|---------------------|-------------|----------------------------------------------------------------------------------------------------|
| `/code_version`     | `GET`       | Displays version information for all KGs hosted on this Plover                                     |
| `/logs`             | `GET`       | Shows log messages from Plover and uWSGI                                                           |
| `/meta_knowledge_graph` | `GET`      | Displays the TRAPI meta KG for the default KG on this Plover                                       |
| `/sri_test_triples` | `GET`       | Displays test triples for the default KG on this Plover |

You should also be able to **send TRAPI query POST requests** to your Plover at the `/query` endpoint. As an example:
```
curl -X 'POST' 'https://multiomics.rtx.ai:9990/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'
```
Note that if you are hosting _multiple KPs_ on this Plover (say, two KPs, with `endpoint_name`s of `ctkp` and `dakp`), the URLs for their individual `/query` endpoints would look something like this:
```
https://multiomics.rtx.ai:9990/ctkp/query
https://multiomics.rtx.ai:9990/dakp/query
```
And similarly, other KP-specific endpoints for the `ctkp` KP in our example would look something like this:
```
https://multiomics.rtx.ai:9990/ctkp/meta_knowledge_graph
https://multiomics.rtx.ai:9990/ctkp/sri_test_triples
```

### Opentelemetry

Plover automatically logs Jaeger opentelemetry traces per [Translator's monitoring requirements](https://github.com/NCATSTranslator/TranslatorTechnicalDocumentation/blob/telemetry-FAQ/docs/deployment-guide/monitoring.md). To view tracings for an ITRB- deployed Plover application, go to https://translator-otel.ci.transltr.io/search (this is the CI otel link; swap `test` or `prod` for `ci` in that URL as appropriate) and select the proper service name from the dropdown menu. Each Plover instance corresponds to one opentelemetry 'service'; its service name will follow the pattern `{app_name}-plover`, where Plover derives the `app_name` using the local identifier from the default KP's infores curie (e.g., `rtx-kg2-plover` or `multiomics-plover`).

Plover determines what Jaeger host to use according to the contents of the user-created `PloverDB/app/domain_name.txt` file as follows:
* `jaeger.rtx.ai` if the Plover host domain name exists and does not contain `transltr.io`
* `jaeger-otel-agent.sri` otherwise



## Provided endpoints

Plover exposes all endpoints required by TRAPI, as well as a few others useful for debugging/specialized queries. All endpoints are documented in the below table.

NOTE: In the below table, `<kp_endpoint>` indicates a wildcard of sorts where you plug in the `endpoint_name` of the KP on that Plover instance that you want to query (where its `endpoint_name` is specified in its [config.json](#config-file) file). If you omit the `<kp_endpoint>`, the default KP on that Plover instance will be queried (useful if you are hosting only one KP on your Plover).

| Endpoint                                                        | Endpoint Type | Request Type | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
|-----------------------------------------------------------------|---------------|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1.`/query`, or <br/> 2.`/<kp_endpoint>/query`                   | [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI/tree/master) | POST | Runs a TRAPI query on 1) the default KP or 2) the specified KP. <br/><br/> **Example Queries:** <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'` <br/><br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'`                                                                             |
| 1.`/meta_knowledge_graph`, or <br/> 2.`/<kp_endpoint>/meta_knowledge_graph` | [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI/tree/master) | GET | Retrieves the TRAPI meta knowledge graph for 1) the default KP or 2) the specified KP. <br/><br/> **Example Queries:** <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/meta_knowledge_graph'` <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/dakp/meta_knowledge_graph'`                                                                                                                                                                                                                                                                                                                                                                                                        |
| 1.`/sri_test_triples`, or 2.`/<kp_endpoint>/sri_test_triples`  | Standard      | GET          | Returns test triples for the knowledge graph (one example triple for every meta-edge, in a structure defined by Translator, [here](https://github.com/TranslatorSRI/SRI_testing/blob/main/tests/onehop/README.md#kp-test-data-format)). <br/><br/> **Example Queries:** <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/sri_test_triples'` <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/dakp/sri_test_triples'`                                                                                                                                                                                                                                                               |
| 1.`/edges`, or 2.`/<kp_endpoint>/edges`                        | Custom        | POST         | Retrieves edges between specified node pairs. <br/><br/> **Example Queries:** <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_edges' -H 'Content-Type: application/json' -d '{"pairs":[["MONDO:0005159", "CHEBI:6427"], ["CHEBI:18332", "MONDO:0005420"]]}'` <br/><br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/get_edges' -H 'Content-Type: application/json' -d '{"pairs":[["MONDO:0005159", "CHEBI:6427"], ["CHEBI:18332", "MONDO:0005420"]]}'`                                                                                                                                                                                                                       |
| 1.`/neighbors`, or 2.`/<kp_endpoint>/neighbors`                  | Custom        | POST         | Retrieves neighbors for the specified nodes, with optional filtering by categories and predicates. <br/><br/> **Example Queries:** <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"]}'` <br/><br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"]}'` <br/><br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"],"categories":["biolink:Disease"],"predicates":["biolink:treats"]}'` |
| `/healthcheck`                                                  | Custom        | GET          | Simple health check endpoint to verify the server is running (returns an empty string). <br/><br/> **Example Queries:** <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/healthcheck'`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `/code_version`                                                 | Custom        | GET          | Retrieves the current code and knowledge graph versions running on the Plover instance. <br/><br/> **Example Queries:** <br/> https://multiomics.rtx.ai:9990/code_version <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/code_version'`                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `/logs`                                                         | Custom        | GET          | Retrieves recent log entries from both Plover and uWSGI logs (for all KPs hosted). <br/><br/> **Example Queries:** <br/> https://multiomics.rtx.ai:9990/get_logs <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/get_logs'` <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/get_logs?num_lines=20'`                                                                                                                                                                                                                                                                                                                                                                         |
| `/`                                                             | Custom        | GET          | Home page for the API, listing available KP endpoints and additional instance-level endpoints. <br/><br/> **Example Queries:** <br/> https://multiomics.rtx.ai:9990                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `/<kp_endpoint>`                                               | Custom        | GET          | Home page for the specified knowledge graph/KP endpoint. <br/><br/> **Example Queries:** <br/> https://multiomics.rtx.ai:9990/dakp <br/> https://multiomics.rtx.ai:9990/ctkp                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |








## Input files

The only input files Plover requires are the knowledge graph (in [Biolink KGX](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) flat-file format) and a config file, which are detailed in the below two sections.

### Nodes and edges files

Plover accepts knowledge graphs in [Biolink KGX](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) format; both [TSV](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md#kgx-format-as-tsv) and [JSON Lines](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md#kgx-format-as-json-lines) format are supported. Once your graph is in this format, you have two choices as for how to give Plover access to your graph:

1. **Publicly-accessible URL (recommended)**: Simply host your graph's nodes and edges files in any publicly accessible web location; this could be a public AWS S3 bucket, a location on an existing server, or really just anywhere the graph can be freely downloaded from. You then provide the URLs to your nodes and edges files in the `nodes_file` and `edges_file` slots in Plover's [config file](#config-file). 

2. **Local copy**: Put copies of your graph's nodes and edges files in the `PloverDB/app/` directory on your host machine, and then specify those files' names (not paths) in the `nodes_file` and `edges_file` slots in Plover's [config file](#config-file). This can be useful for dev work, but note that Plover's [remote deployment mechanism](#automatic-deployment-methods) is **not** compatible with this option.

The 'core' properties that Plover expects every node and edge to have are listed below; you may include any additional properties on nodes/edges as well, which Plover will load into TRAPI attributes.

* **Required node properties**: `id`, `category`* (`name` is encouraged, but not required)
  * NOTE: while you do **not** have to call the property "category" exactly, you do need to have _some_ property capturing a node's category(s); you need to tell Plover what this property is called using the `labels` slot in Plover's [config file](#config-file)
  * NOTE: the node category property may be a string or an _array_ of strings, and Plover does **not** require that categories are pre-expanded to their ancestor categories (Plover does this expansion itself)
* **Required edge properties**: `id`, `subject`, `object`, `predicate`

Some notes:
* **File names**: You may name your nodes/edges files whatever you like, though we suggest including some sort of graph version number in their names.
* **Array delimiter**: For array fields in TSV-formatted graphs, the default delimiter is a comma (`,`), but you can change this to whatever delimiter you'd like using the `array_delimiter` slot in Plover's config file (e.g., `"array_delimiter": "|",`).



### Config file

Each knowledge graph that Plover hosts/serves needs its own JSON config file, such as the one [here](https://github.com/RTXteam/PloverDB/blob/main/app/config.json) for the RTX-KG2 knowledge graph.

**We highly recommend copying an existing config file such as the KG2c [config.json](https://github.com/RTXteam/PloverDB/blob/dev/app/config.json), [config_ctkp.json](https://github.com/RTXteam/PloverDB/blob/multiomics/app/config_ctkp.json), or [config_dakp.json](https://github.com/RTXteam/PloverDB/blob/multiomics/app/config_dakp.json) and editing it for your needs, as opposed to creating one from scratch.** Note that Plover will serve a KP API for each `config*.json` file present in `PloverDB/app/`, so be sure to delete any such config files you don't want before running Plover.

Most importantly, you need to specify the URLs from which your Biolink [KGX-formatted](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) flat-file knowledge graph can be downloaded in the `nodes_file` and `edges_file` slots in your graph's config file. Definitions for all config slots are included below.

| JSON Slot                        | Data Type | Required?                | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
|----------------------------------|----------|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `nodes_file`                     | string (URL) | **Required**             | A publicly accessible URL from which a Biolink [KGX-compliant](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) TSV or JSON Lines file containing all the nodes in your graph can be downloaded. <br/> **Example:** `"https://example.com/nodes.jsonl"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `edges_file`                     | string (URL) | **Required**             | A publicly accessible URL from which a Biolink [KGX-compliant](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) TSV or JSON Lines file containing all the edges in your graph can be downloaded. <br/> **Example:** `"https://example.com/edges.jsonl"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `biolink_version`                | string   | **Required**             | The version of Biolink that your graph adheres to and that Plover should use when answering queries over your graph. <br/> **Example:** `"4.2.0"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `kp_infores_curie`               | string   | **Required**             | A unique identifier (compact URI) for your knowledge provider from the [Biolink Information Resource Registry](https://github.com/biolink/information-resource-registry/blob/main/infores_catalog.yaml). This curie will be included on edges in TRAPI responses. <br/> **Example:** `"infores:rtx-kg2"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `endpoint_name`                  | string   | **Required**             | The name of the sub-endpoint under which this graph's TRAPI API will be accessible. If only one KP is hosted, it will be the default, meaning this property is mostly important only if multiple KPs are being hosted. <br/> **Example:** `"ctkp"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `labels`                         | object   | **Required**                 | Specifies the node and edge properties that Plover should treat as node and edge types when answering queries. Defaults are `"category"` and `"predicate"`. <br/> **Example:** `{"edges": "predicate", "nodes": "all_categories"}`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `trapi_attribute_map`            | object | **Required**             | Plover converts all non-core node/edge properties into TRAPI node/edge [Attribute](https://github.com/NCATSTranslator/ReasonerAPI/blob/67fb2d0eff8f1c8bd464ed83a5bf34b7563a83d8/TranslatorReasonerAPI.yaml#L1051-L1136)s in TRAPI responses. This field allows you to specify what the contents of such node/edge Attributes should look like. Default TRAPI attribute templates for common node/edge properties are provided in `PloverDB/app/trapi_attribute_template.json`; you may override those defaults using this config field and/or add additional attribute templates not provided in the defaults. This field should contain an object whose top-level slots are node and/or edge property/column names in your input graph, and the values are objects specifying the `attribute_type_id`, `value_type_id`, `attribute_source`, `description`, and/or `value_url` that should be listed on the TRAPI Attribute (Plover automatically plugs in the `value` for the TRAPI Attribute based on the value provided in your graph files). Plover will replace any instances of `{kp_infores_curie}` in this template with the curie you provide in the `kp_infores_curie` config slot. It will also replace any instances of `{value}` with the property/column value provided in your input graph files. <br/> **Example:** `{"nctid":{"attribute_type_id":"biolink:supporting_study","value_url":"https://clinicaltrials.gov/study/{value}?tab=table"},"phase":{"attribute_type_id":"clinical_trial_phase","value_type_id":"biolink:ResearchPhaseEnum"}}` |
| `convert_input_ids`              | boolean  | **Strongly Recommended** | Specifies whether Plover should convert node identifiers used in queries to the equivalent version of those identifiers used in the graph. The source Plover uses for such equivalence mappings is either the graph itself (it looks for `equivalent_ids`, `equivalent_curies`, or `equivalent_identifiers` properties on nodes) or, if such a property is not present on nodes, the SRI [Node Normalizer](https://github.com/TranslatorSRI/NodeNormalization) API (via batch querying at build time). Default is `false`.  <br/> **Example:** `true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `normalize`                      | boolean  | Optional             | Specifies whether Plover should canonicalize the underlying graph. If `true`, Plover will canonicalize it at build time using the SRI [Node Normalizer](https://github.com/TranslatorSRI/NodeNormalization) API. Default is `false`. <br/> **Example:** `true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `drug_chemical_conflation`       | boolean  | Optional             | Specifies whether Plover should use the "drug_chemical_conflate" option when querying the SRI [Node Normalizer](https://github.com/TranslatorSRI/NodeNormalization) API. Default is `false`. <br/> **Example:** `true`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `num_edges_per_answer_cutoff`    | integer  | Optional             | The maximum number of edges Plover will return per query. No prioritization is applied when enforcing this limit. Default is 1,000,000. <br/> **Example:** `500000`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `biolink_helper_branch`          | string   | Optional             | The branch of the [RTX repo](https://github.com/RTXteam/RTX/tree/master/code/ARAX/BiolinkHelper) that Plover should download the BiolinkHelper module from. Default is `"master"`. <br/> **Example:** `"master"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `array_delimiter`                | string   | Optional             | The delimiter Plover should use when parsing array columns in the input graph TSVs (only relevant to TSV-formatted graphs). Default is a comma. <br/> **Example:** `"\|"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `remote_subclass_edges_file_url` | string (URL) | Optional             | A publicly accessible URL for an external file containing `biolink:subclass_of` edges if they are not already present in your graph. This file should be in JSON Lines [KGX format](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md). <br/> **Example:** `"https://example.com/subclass_edges.jsonl"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `subclass_sources`               | array of strings | Optional             | Specifies which knowledge sources Plover should use for `subclass_of` edges. Subclass edges with a `primary_knowledge_source` other than those in this list will be ignored. <br/> **Example:** `["infores:mondo", "infores:go"]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `ignore_edge_properties`         | array of strings | Optional             | Edge property names in the flat file graph that should be ignored (i.e., _not_ included as edge attributes in TRAPI responses). <br/> **Example:** `["publications", "provided_by"]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `ignore_node_properties`         | array of strings | Optional             | Node property names in the flat file graph that should be ignored (i.e., _not_ included as node attributes in TRAPI responses). <br/> **Example:** `["description", "publications"]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `zip`                            | object   | Optional             | Relevant only for TSV-formatted graphs. Provides a way to "zip" array columns in the edges TSV file to form nested attributes on edges in TRAPI responses. This should be an object whose top-level slots are the names of the properties that the zipped columns will be nested into. Each top-level slot then contains an object with two slots: `"properties"`, which is a list of the column names that should be zipped together, and `"leader"`, which is the name of the column specified in `"properties"` that should be treated as the parent property/unique identifier for the zipped objects. <br/> **Example:** `{"supporting_studies": {"properties": ["nctid", "phase", "tested", "primary_purpose"], "leader": "nctid"}}` (This will zip the `nctid`, `phase`, `tested`, and `primary_purpose` columns to form separate edge Attributes for each supporting study, where the parent Attribute is for the `nctid`, which has nested attributes for `phase`, `tested`, and `primary_purpose`.) In this example, the `trapi_attribute_map` config slot would then need to include top-level entries for `"nctid"`, `"phase"`, `"tested"`, and `"primary_purpose"`, that define what the contents of each of those Attributes/sub-Attributes should look like.                                                                                                                                                                                                                                                                                        |
| `other_array_properties`         | array of strings | Optional             | Relevant only for TSV-formatted graphs. List all columns whose values are arrays here except for any that you have already listed under the `zip` slot.  <br/> **Example:** `["source_record_urls"]`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `sources_template`               | object   | Optional             | This template specifes what the contents of TRAPI [RetrievalSource](https://github.com/NCATSTranslator/ReasonerAPI/blob/67fb2d0eff8f1c8bd464ed83a5bf34b7563a83d8/TranslatorReasonerAPI.yaml#L1557-L1613)s on edges in the TRAPI response should look like. If omitted, Plover will create RetrievalSources using the `primary_knowledge_source` listed on each edge, but this template allows you to specify primary (and other) knowledge sources that should be listed on edges of different types. This field is a JSON object where the top level slots are `"default"` plus any other Biolink predicates (e.g., `"biolink:treats"`) whose edge sources should be handled differently than the default. Plover will replace any instances of `{kp_infores_curie}` in this template with the curie you provide in the `kp_infores_curie` config slot. <br/> **Example:** `{"default":[{"resource_id":"{kp_infores_curie}","resource_role":"aggregator_knowledge_source","upstream_resource_ids":["infores:faers"]},{"resource_id":"infores:faers","resource_role":"primary_knowledge_source"}],"biolink:treats":[{"resource_id":"{kp_infores_curie}","resource_role":"primary_knowledge_source","upstream_resource_ids":["infores:dailymed"]},{"resource_id":"infores:dailymed","resource_role":"supporting_data_source"}]}`                                                                                                                                                                                                                                    |




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
