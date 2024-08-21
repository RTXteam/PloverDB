# PloverDB

Plover is a prototype **read-only in-memory database service** that can answer **one-hop queries** on a given biomedical knowledge graph (supplied in JSON [Biolink](https://biolink.github.io/biolink-model/) format).

It accepts [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) query graphs. More specifically, it can answer these kinds of queries:

1. **Single-hop**: `(>=1 curies)--[>=0 predicates]--(>=0 categories, >=0 curies)`
2. **Edge-less**: Consist only of `QNode`s (all of which must have curies specified)

It can answer queries in either an undirected (default) or directed fashion.

It returns the IDs of the nodes and edges comprising the answer to the query in the following format:
```
{
  "nodes":{
    "n00":[
      "CHEMBL.COMPOUND:CHEMBL25"
    ],
    "n01":[
      "CHEMBL.COMPOUND:CHEMBL833"
    ]
  },
  "edges":{
    "e00":[
      4831296,
      7234219,
      7233074,
    ]
  }
}
```
Where `n00`, `n01`, and `e00` are the `key`s of the `QNode`s/`QEdge`s in the submitted query graph. 

In your JSON KG file, **required properties** for nodes/edges are:
* **Nodes**: `id` and some sort of `categories` property (specify its exact name in `kg_config.json`)
* **Edges**: `id`, `subject`, `object`, and some sort of `predicate` property (specify its exact name in `kg_config.json`)

All other node/edge properties will be ignored.

### Data model returned

#### Node properties
The properties of a node returned will be in a list with the following entries, in order:

- `name`
- `category`
  
#### Edge properties

The properties of an edge returned will be in a list with the following entries, in order:

- `subject`
- `object`
- `predicate`
- `primary_knowledge_source`
- `qualified_predicate`
- `object_direction`
- `object_aspect`

### How to run

1. Install Docker (if needed)
    * For Ubuntu 20.04, try `sudo apt-get install -y docker.io`
    * For Mac, `brew install --cask docker` worked for me with macOS Big Sur
1. Make sure port `9990` on your host machine is open if you're deploying the service somewhere (vs. just using it locally)
1. Clone this repo
1. `cd` into `PloverDB/`
1. Then run the following command (if you are not on Ubuntu, you should ommit the "sudo docker" parameter), subbing in whatever names you would like for 'myimage' and 'mycontainer':
    * `bash -x run.sh myimage mycontainer "sudo docker"`

This will build a Docker image and run a container off of it, publishing it at port 9990.

You should now be able to send it TRAPI query POST requests at the port you opened; the URL for this would look something like: `https://yourinstance.rtx.ai:9990/query/`. Or, if you just want to use it locally: `http://localhost:9990/query/`.

#### For ITRB

Assuming an Ubuntu instance with Docker installed and SSL certificates already handled, simply run (from the desired branch):
```
sudo docker build -t ploverimage .
sudo docker run -d --name plovercontainer -p 9990:443 ploverimage
```

### How to test
To verify that your new service is working, you can check a few endpoints (plug in your domain name in place of 'yourinstance.rtx.ai'):
   1. Navigate to https://yourinstance.rtx.ai:9990/code_version in your browser; it should display information about the build
   2. Naviagte to https://yourinstance.rtx.ai:9990/get_logs in your browser; it should display log messages
   3. Navigate to https://yourinstance.rtx.ai:9990/meta_knowledge_graph in your browser; it should display the meta knowledge graph
   4. Try sending a TRAPI query to https://yourinstance.rtx.ai:9990/query

### Debugging
To see the logs via the terminal (includes all components - Gunicorn, etc.), run:
 ```
 docker logs mycontainer
```
If you want to save the contents of the log to a file locally, run:
```
docker logs mycontainer >& logs/mylog.log
```

If you want to use cURL to debug PloverDB, make sure to specify the `-L` (i.e., `--location`) option for the `curl` command, since PloverDB seems to use redirection. Like this:
```
curl -L -X POST -d @test20.json -H 'Content-Type: application/json' -H 'accept: application/json' http://kg2cplover2.rtx.ai:9990/query
```

To have PloverDB return information about the code version for the `RTXteam/PloverDB`
project that was used for the running service, you can use the `code_version` API
function:

```
curl -L -X GET -H 'accept: application/json' http://kg2cplover2.rtx.ai:9990/code_version
```

### Credits

* Author: Amy Glen
* Inspiration/advice: Stephen Ramsey, Eric Deutsch, David Koslicki
