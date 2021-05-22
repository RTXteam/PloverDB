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

### How to run

#### To host the latest 'production' [KG2c](https://github.com/RTXteam/RTX/tree/master/code/kg2/canonicalized):

1. Install Docker (if needed)
    * For Ubuntu 18, instructions are [here](https://github.com/RTXteam/RTX/blob/master/code/kg2/install-docker-ubuntu18.sh)
    * For Mac, `brew install --cask docker` worked for me with macOS Big Sur
1. Clone this repo
1. Make sure port `9990` (or one of your choosing) on your host machine is open if you're deploying the service somewhere (vs. just using it locally)
1. `cd` into `PloverDB/`
1. Build your Docker image, passing in your AWS keypair that has been granted access to the proper S3 bucket (by the KG2c team):
    * `docker build -t yourimage --build-arg aws_access_key=XXXX --build-arg aws_secret_key=YYYY .`
1. Run a container off your new image:
    * `docker run -d --name yourcontainer -p 9990:80 yourimage`

*Note: You may need to add `sudo` in front of all docker commands, depending on your user.*

Building the image should take 20-30 minutes. Upon starting the container, it will be a few minutes (appx. 5 minutes) until the app is fully loaded and ready for use; you can do `docker logs yourcontainer` to check on its progress.

Once it's finished loading, you should be able to send it POST requests at the port you opened; the URL for this would look something like: `http://yourinstance.rtx.ai:9990/query/`. Or, if you just want to use it locally: `http://localhost:9990/query/`.

#### To host your own KG:

If you want to host your own KG instead of the latest 'production' KG2c, follow the same steps as above except also do the following between steps 3 and 4:

1. Put your JSON KG file into `PloverDB/app/`
1. Update `PloverDB/app/kg_config.json`:
    1. Set `download_latest_kg2c` to `false`
    1. Specify your JSON kg file name under `local_kg_file_name` (e.g., `"my_kg.json"`)
    1. Specify the 'labels' to use for nodes/edges (e.g., `"predicate"` and `"expanded_categories"`)

And for step 5, the build command is instead simply `docker build -t yourimage .`.

### How to test
To verify that your new service is working, you can run the pytest suite against it:
1. If you haven't already done so on the machine you'll be sending the tests from:
    1. Clone this repo and `cd` into it
    1. Run `pip install -r requirements.txt`
1. `cd PloverDB/test/`
1. `pytest -v test.py --endpoint [your_endpoint_url]`
    * Example endpoint URL: `http://kg2cplover.rtx.ai:9990`
    * If no endpoint is specified, the tests will use: `http://localhost:9990`

(Note that these tests are written for KG2c, so may not pass if you've hosted a knowledge graph other than KG2c.)

### Credits

* Author: Amy Glen
* Inspiration/advice: Stephen Ramsey, Eric Deutsch, David Koslicki