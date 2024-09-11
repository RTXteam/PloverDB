# PloverDB

Plover is an **in-memory** Python-based platform for hosting/serving Biolink-compliant knowledge graphs as **[TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) APIs**.

In answering queries, Plover abides by all Translator **Knowledge Provider reasoning requirements**; it also can normalize the underlying graph and convert query node IDs to the proper equivalent identifiers for the given knowledge graph. 

More specifically, Plover can answer these kinds of queries:

1. **Single-hop**: `(>=1 curies)--[>=0 predicates]--(>=0 categories, >=0 curies)`
2. **Edge-less**: Consist only of `QNode`s (all of which must have curies specified)

The knowledge graph to be hosted needs to be in a Biolink-compliant format with separate nodes and edges files; both **TSV** and **JSON Lines** formats are supported. 

You must provide **URLs** from which the **nodes/edges files** can be downloaded in a **config JSON file** in `PloverDB/app/` (e.g., `config_kg2c.json`). The config file includes a number of settings that can be customized and also defines the way in which node/edge properties should be loaded into **TRAPI attributes**.

#### Nodes and edges files

TODO

#### Config file

TODO

#### Multiple KPs

TODO

### How to run

Install Docker.
    * For Ubuntu 20.04, try `sudo apt-get install -y docker.io`
    * For Mac, `brew install --cask docker` worked for me with macOS Big Sur

#### How to run a dev Plover

TODO

1. Clone this repo and `cd` into `PloverDB/`
1. Edit `PloverDB/config.json` for your particular graph
1. Run the following command:
    * `bash -x run.sh -s true`

This will build a Plover Docker image and run a container off of it, publishing it at port 9990. The `-s true` parameter tells Plover to skip configuring SSL certificates.

Note that by default, this script will use the `sudo docker` command; use the optional `-d` parameter to specify a different docker command (e.g., `bash -x run.sh -s true -d docker`).

#### How to deploy Plover on a new instance

TODO

Use Ubuntu..

1. Make sure port `9990` on your host machine is open
1. Fork the Plover repo
1. Edit the config file at `PloverDB/app/config_kg2c.json` to work for your KP
   1. Most notably, you need to point to nodes/edges files for your graph in TSV or JSON Lines Biolink-style format
   2. We suggest also changing the name of this file to something like `config_mykp.json`; the default template is for RTX-KG2c
   1. More info on the config file contents is here (TODO)
1. Run `bash -x PloverDB/run.sh`


#### How to deploy a new KP to an existing Plover

TODO

#### For ITRB

Instructions tailored for ITRB deployments:

Assuming an Ubuntu instance with Docker installed and SSL certificates already handled, simply run (from the desired branch):
```
sudo docker build -t ploverimage .
sudo docker run -d --name plovercontainer -p 9990:443 ploverimage
```

### Provided endpoints

TODO

### How to test

You should now be able to send your Plover TRAPI query POST requests at port 9990; the URL for this would look something like: `https://yourinstance.rtx.ai:9990/query`. Or, if you are just using Plover locally: `http://localhost:9990/query`.

To verify that your new service is working, you can check a few endpoints (**plug in your domain name** in place of 'kg2cplover.rtx.ai'):
   1. Navigate to https://kg2cplover.rtx.ai:9990/code_version in your browser; it should display information about the build
   2. Naviagte to https://kg2cplover.rtx.ai:9990/get_logs in your browser; it should display log messages
   3. Navigate to https://kg2cplover.rtx.ai:9990/meta_knowledge_graph in your browser; it should display the meta knowledge graph
   4. Navigate to https://kg2cplover.rtx.ai:9990/sri_test_triples in your browser; it should display the SRI test triples
   5. Try sending a TRAPI query to https://kg2cplover.rtx.ai:9990/query

### Debugging
To view logs in your **browser**, go to https://kg2cplover.rtx.ai:9990/get_logs. This will show information from 
the Plover and Gunicorn logs. By default, the last 100 lines in each log are displayed; you can change this using 
the `num_lines` parameter - e.g., https://kg2cplover.rtx.ai:9990/get_logs?num_lines=500.

To see the logs via the **terminal** (includes all components - Gunicorn, etc.), run:
 ```
 docker logs plovercontainer
```
If you want to **save** the contents of the log to a file locally, run:
```
docker logs plovercontainer >& logs/mylog.log
```

If you want to use **cURL** to debug PloverDB, make sure to specify the `-L` (i.e., `--location`) option for the 
`curl` command, since PloverDB seems to use redirection. Like this:
```
curl -L -X POST -d @test20.json -H 'Content-Type: application/json' -H 'accept: application/json' https://kg2cplover.rtx.ai:9990/query
```

If you want to see the **code version** for the `RTXteam/PloverDB`
project that was used for the running service, as well as the **versions of the knowledge graphs** it ingested, 
you can use the `code_version` API endpoint (https://kg2cplover.rtx.ai:9990/code_version):
```
curl -L -X GET -H 'accept: application/json' https://kg2cplover.rtx.ai:9990/code_version
```

### Credits

* Author: Amy Glen
* Inspiration/advice: Stephen Ramsey, Eric Deutsch, David Koslicki
