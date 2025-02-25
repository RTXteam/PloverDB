# PloverDB

Plover is an **in-memory** Python-based platform for hosting/serving Biolink-compliant knowledge graphs as **[TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) APIs**.

In answering queries, Plover abides by all **Translator Knowledge Provider reasoning requirements**; it also can normalize the underlying graph and convert query node IDs to the proper equivalent identifiers for the given knowledge graph. 

Plover accepts TRAPI query graphs at its `/query` endpoint, which include:

1. **Single-hop** query graphs: `(>=1 ids)--[>=0 predicates]--(>=0 categories, >=0 ids)`
2. **Edge-less** query graphs: Consist only of query nodes (all of which must have ids specified)

The knowledge graph to be hosted needs to be in a Biolink-compliant, KGX-style format with separate nodes and edges files; both **TSV** and **JSON Lines** formats are supported. See [this section](#nodes-and-edges-files) for more info.

You must provide **URLs** from which the **nodes/edges files** can be downloaded in a **config JSON file** in `PloverDB/app/` (e.g., `config.json`). The config file includes a number of settings that can be customized and also defines the way in which node/edge properties should be loaded into **TRAPI attributes**. See [this section](#config-file) for more info.

Note that a single Plover app can host/serve **multiple KPs** - each KP is exposed at its own endpoint (e.g., `/ctkp`, `/dakp`). See [this section](#how-to-deploy-a-new-kp-to-an-existing-plover) for more info.



## Table of Contents
1. [How to run](#how-to-run)
   1. [How to run Plover locally (dev)](#how-to-run-plover-locally-dev)
   1. [How to deploy Plover](#how-to-deploy-plover)
   1. [Memory and space requirements](#memory-and-space-requirements)
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

To run Plover locally for development:

1. Clone/fork this repo and navigate into it (`cd PloverDB/`)
1. Edit the config file at `/app/config.json` for your particular graph (more info in [this section](#config-file))
1. Run the following command:
    * `bash -x run.sh`

This will build a Plover Docker image and run a container off of it, publishing it at port 9990 (`http://localhost:9990`).

See [this section](#how-to-test) for details on using/testing your Plover.

### How to deploy Plover

_NOTE: For more deployment info specific to the RTX-KG2/ARAX team, see the [this page](https://github.com/RTXteam/PloverDB/wiki/Deployment-how-tos) in the Plover wiki._

Because Plover is Dockerized, it can be run on any machine with Docker installed.

The amount of memory and disk space your host instance will need depends on the size/contents of your graph. See [this section](#memory-and-space-requirements) for more info on the memory/space requirements.

#### Steps to be done once, at initial setup for a new instance: {#initial-setup}

1. Make sure ports `9990`, `80`, and `443` on the host instance are open
1. Install SSL certificates on the host instance and set them up for auto-renewal:
   1. `sudo snap install --classic certbot`
   1. `sudo ln -s /snap/bin/certbot /usr/bin/certbot`
   1. `sudo certbot certonly --standalone`
      1. Enter your instance's domain name (e.g., `multiomics.rtx.ai`) as the domain to be certified. You can optionally also list any `CNAME`s for the instance separated by commas (e.g., `multiomics.rtx.ai,ctkp.rtx.ai`).
   1. Verify the autorenewal setup by doing a dry run of certificate renewal:
      1. `sudo certbot renew --dry-run`
1. Fork the PloverDB repo
1. Create a `domain_name.txt` file in `PloverDB/app/` like so:
   * `echo "multiomics.rtx.ai" > PloverDB/app/domain_name.txt`
   * (plug in your domain name in place of `multiomics.rtx.ai` - needs to be the same domain name entered in the step above when configuring certbot)

#### Steps to build Plover once initial setup is complete:

1. Edit the config file at `PloverDB/app/config.json` for your graph
   1. Most notably, you need to point to nodes/edges files for your graph in TSV or JSON Lines KGX format
   1. We suggest also **changing the name of this file** for your KP (e.g., `config_mykp.json`); just ensure that the file name starts with `config` and ends with `.json`
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

### Memory and space requirements

The amount of memory and disk space your host instance will need to run Plover depends on the size/contents of your graph(s).

Memory/space consumption examples:
Memory/space consumption examples:

| Plover deployment                                     | Number of KGs | KG size details                           | Memory consumption[a] | Disk space consumption | Instance type used                                    |
|-------------------------------------------------------|---------------|-------------------------------------------|------------------------|------------------------|-------------------------------------------------------|
| [RTX-KG2 KP](https://kg2cploverdb.ci.transltr.io) | 1             | ~7 million nodes, ~30 million edges       | 90 GiB                | 25G                    | AWS EC2 `r5a.4xlarge` (128 GiB RAM), 100GB disk space |
| [Multiomics KPs](https://multiomics.rtx.ai:9990)      | 4             | Combined, ~100k nodes, ~500k edges        | 2.5 GiB               | 6G                     | AWS EC2 `t4g.xlarge` (16 GiB RAM), 20GB disk space    |


_[a]: These are approximate values when the service is at rest; this will increase somewhat under heavy usage, by up to ~10% based on our experience._



## How to test

To quickly verify that your Plover service is working, you can check a few endpoints. 

For all of these examples, the **base URL** for your service will be either:
1. http://localhost:9990 if you are running Plover locally, or 
2. something like https://multiomics.rtx.ai:9990 if you have deployed Plover somewhere (**plug in your domain name** in place of `multiomics.rtx.ai`)

Using the proper base URL, check the following endpoints (either by viewing them in your browser or accessing them programmatically):

| Endpoint                | Request Type | Description                                                    |
|-------------------------|-------------|----------------------------------------------------------------|
| `/code_version`         | `GET`       | Displays version information for all KGs hosted on this Plover |
| `/get_logs`             | `GET`       | Shows log messages from Plover and uWSGI                       |
| `/meta_knowledge_graph` | `GET`      | Displays the TRAPI meta KG for the default KG on this Plover   |
| `/sri_test_triples`     | `GET`       | Displays test triples for the default KG on this Plover        |

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



## Provided endpoints

Plover exposes all endpoints required by TRAPI, as well as a few others useful for debugging/specialized queries. All endpoints are documented in the below table.

NOTE: In the below table, `<kp_endpoint_name>` indicates a wildcard of sorts where you plug in the `endpoint_name` of the KP on that Plover instance that you want to query (where its `endpoint_name` is specified in its [config.json](#config-file) file). If you omit the `<kp_endpoint_name>`, the default KP on that Plover instance will be queried (useful if you are hosting only one KP on your Plover).

| Endpoint                                                                         | Endpoint Type | Request Type | Description                                                                                        | Example Queries                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
|----------------------------------------------------------------------------------|---------------|--------------|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1.`/query`, or <br/> 2.`/<kp_endpoint_name>/query`                               | [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI/tree/master)         | POST         | Runs a TRAPI query on 1) the default KP or 2) the specified KP.                                    | `curl -X 'POST' 'https://multiomics.rtx.ai:9990/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'` <br/> <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/query' -H 'Content-Type: application/json' -d '{"message":{"query_graph":{"edges":{"e00":{"subject":"n00","object":"n01"}},"nodes":{"n00":{"ids":["CHEMBL.COMPOUND:CHEMBL112"]},"n01":{}}}}}'`                                            |
| 1.`/meta_knowledge_graph`, or <br/> 2.`/<kp_endpoint_name>/meta_knowledge_graph` | [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI/tree/master)         | GET          | Retrieves the TRAPI meta knowledge graph for 1) the default KP or 2) the specified KP.             | `curl -X 'GET' 'https://multiomics.rtx.ai:9990/meta_knowledge_graph'` <br/> <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/dakp/meta_knowledge_graph'`                                                                                                                                                                                                                                                                                                                                                                                              |
| 1.`/sri_test_triples`, or 2.`/<kp_endpoint_name>/sri_test_triples`               | Standard      | GET          | Returns test triples for the knowledge graph (one example triple for every meta-edge).             | `curl -X 'GET' 'https://multiomics.rtx.ai:9990/sri_test_triples'` <br/> <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/dakp/sri_test_triples'`                                                                                                                                                                                                                                                                                                                                                                                                      |
| 1.`/get_edges`, or 2.`/<kp_endpoint_name>/get_edges`                             | Custom        | POST         | Retrieves edges between specified node pairs.                                                      | `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_edges' -H 'Content-Type: application/json' -d '{"pairs":[["MONDO:0005159", "CHEBI:6427"], ["CHEBI:18332", "MONDO:0005420"]]}'` <br/> <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/get_edges' -H 'Content-Type: application/json' -d '{"pairs":[["MONDO:0005159", "CHEBI:6427"], ["CHEBI:18332", "MONDO:0005420"]]}'`                                                                                                                                                                    |
| 1.`/get_neighbors`, or 2.`/<kp_endpoint_name>/get_neighbors`                                   | Custom        | POST         | Retrieves neighbors for the specified nodes, with optional filtering by categories and predicates. | `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"]}'` <br/> <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/dakp/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"]}'` <br/> <br/> `curl -X 'POST' 'https://multiomics.rtx.ai:9990/get_neighbors' -H 'Content-Type: application/json' -d '{"node_ids":["CHEMBL.COMPOUND:CHEMBL112"],"categories":["biolink:Disease"],"predicates":["biolink:treats"]}'` |
| `/healthcheck`                                                                   | Custom        | GET          | Simple health check endpoint to verify the server is running (returns an empty string).            | `curl -X 'GET' 'https://multiomics.rtx.ai:9990/healthcheck'`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `/code_version`                                                                  | Custom        | GET          | Retrieves the current code and knowledge graph versions running on the Plover instance.            | https://multiomics.rtx.ai:9990/code_version <br/> <br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/code_version'`                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `/get_logs`                                                                      | Custom        | GET          | Retrieves recent log entries from both Plover and uWSGI logs (for all KPs hosted).                 | https://multiomics.rtx.ai:9990/get_logs <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/get_logs'` <br/><br/> `curl -X 'GET' 'https://multiomics.rtx.ai:9990/get_logs?num_lines=20'`                                                                                                                                                                                                                                                                                                                                                            |
| `/`                                                                              | Custom        | GET          | Home page for the API, listing available KP endpoints and additional instance-level endpoints.     | https://multiomics.rtx.ai:9990                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `/<kp_endpoint_name>`                                                            | Custom        | GET          | Home page for the specified knowledge graph/KP endpoint.                                           | https://multiomics.rtx.ai:9990/dakp <br/> <br/> https://multiomics.rtx.ai:9990/ctkp                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |







## Input files

The only input files Plover requires are the knowledge graph (in [Biolink KGX](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) flat-file format) and a config file, which are detailed in the below two sections.

### Nodes and edges files

Plover accepts knowledge graphs in [Biolink KGX](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md) format; both [TSV](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md#kgx-format-as-tsv) and [JSON Lines](https://github.com/biolink/kgx/blob/master/specification/kgx-format.md#kgx-format-as-json-lines) format are supported. Once your graph is in this format, you have two choices as for how to give Plover access to your graph:

1. **Publicly-accessible URL (recommended)**: Simply host your graph's nodes and edges files in any publicly accessible web location; this could be a public AWS S3 bucket, a location on an existing server, or really just anywhere the graph can be freely downloaded from. You then provide the URLs to your nodes and edges files in the `nodes_file` and `edges_file` slots in Plover's [config file](#config-file). 

2. **Local copy**: Put copies of your graph's nodes and edges files in the `PloverDB/app/` directory on your host machine, and then specify those files' names (not paths) in the `nodes_file` and `edges_file` slots in Plover's [config file](#config-file). This can be useful for dev work, but note that Plover's [remote deployment mechanism](#automatic-deployment-methods) is **not** compatible with this option.

The 'core' properties that Plover expects every node and edge to have are listed below; you may include any additional properties on nodes/edges as well, which Plover will load into TRAPI attributes.

* Core node properties: `id`, `category` (`name` is encouraged, but not required)
* Core edge properties: `subject`, `object`, `predicate`, `primary_knowledge_source`

Some notes:
* **File names**: You may name your nodes/edges files whatever you like, though we suggest including some sort of graph version number in their names.
* **Array delimiter**: For array fields (only applicable to TSV-formatted graphs), the default delimiter is a comma (`,`), but you can change this to whatever delimiter you'd like using the `array_delimiter` slot in Plover's config file (e.g., `"array_delimiter": "|",`).



### Config file

Each knowledge graph that Plover hosts/serves needs its own JSON config file, such as the one [here](https://github.com/RTXteam/PloverDB/blob/main/app/config.json) for the RTX-KG2 knowledge graph.

Most importantly, you need to specify the URLs from which your Biolink KGX-formatted flat-file knowledge graph can be downloaded in the `nodes_file` and `edges_file` slots. Definitions for all config slots are included below.

* `nodes_file`: A publicly accessible URL from which a Biolink KGX-compliant TSV or JSON Lines file containing all the nodes in your graph can be downloaded.
* `edges_file`: A publicly accessible URL from which a Biolink KGX-compliant TSV or JSON Lines file containing all the edges in your graph can be downloaded.
* `biolink_version`: The version of Biolink that your graph adheres to and that Plover should use when answering queries over your graph.
* `kp_infores_curie`: A unique identifier (compact URI) for your knowledge provider from the [Biolink Information Resource Registry](https://github.com/biolink/information-resource-registry/blob/main/infores_catalog.yaml) (e.g., `"infores:rtx-kg2"`). This curie will be included on edges in TRAPI responses.
* `endpoint_name`: Whatever you want to name the sub-endpoint that this KP will be accessible at (e.g., "kg2c" or "ctkp"); this is mostly relevant only if this Plover is hosting _more than one_ KP, as otherwise the one KP being hosted will be the default KP, and thus will be query-able at mydomain.com/query instead of mydomain.com/mykp/query.
* `labels`: Specifies the names of the node and edge properties that you want Plover to treat as node and edge types when answering queries over the KP; this will typically be "predicate" for edges and "category" or "categories" for nodes (accepts either string or array values for node labels)
* `remote_subclass_edges_file_url`: An optional property where you can specify the URL for an external file to use as a source of `subclass_of` edges, if your graph doesn't contain `subclass_of` edges itself; this file should essentially be a Biolink KGX edges file containing only `subclass_of` edges
* `subclass_sources`: Allows you to specify which knowledge sources you want Plover to use for `subclass_of` edges (Plover will basically ignore all subclass_of edges that are _not_ from one of the knowledge sources listed here); this should be an array of infores curies.
* `num_edges_per_answer_cutoff`: An integer representing the maximum number of edges you want Plover to ever return for a query; suggested value is something like 1,000,000. Note that when Plover imposes this cutoff, it does not do any prioritization/ranking when deciding which edges to keep - the decision is arbitrary.
* `normalize`: A boolean value that tells Plover whether you want it to 'canonicalize' or 'synonymize' your graph; if set to true, Plover will use the SRI Node Normalizer (queried via its API) at build time to canonicalize your graph. 
* `convert_input_ids`: A boolean value that tells Plover whether you want it to convert the identifiers used in incoming queries into their equivalent identifiers that your graph uses for those nodes; suggested to set to true.
* `drug_chemical_conflation`: A boolean value that controls whether Plover should use the "drug_chemical_conflate" option when querying the SRI Node Normalizer API (which allows drugs and chemicals to be conflated)
* `biolink_helper_branch`: The branch in the RTX repo that the BiolinkHelper should be downloaded from; should almost always be `"master"`.
* `ignore_edge_properties`: An optional array of edge property names in your flat file graph that you want Plover to ignore (meaning, they should not appear in TRAPI responses)
* `ignore_node_properties`: An optional array of node property names in your flat file graph that you want Plover to ignore (meaning, they should not appear in TRAPI responses)
* `zip`: Relevant only to graphs that are provided in TSV format; this slot provides a way to 'zip' columns in your TSV to form nested attributes in TRAPI responses. TODO 
* `other_array_properties`: TODO 
* `trapi_attribute_map`: TODO

TOOD: Note that one can have nodes/edges files present only locally - put them in /app and just list their names (instead of URLs) in the nodes/edges slots. 

TODO: explain how sources are construted?



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
