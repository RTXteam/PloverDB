# PloverDB

Plover is a prototype **in-memory database service** that can answer **one-hop queries** on a given biomedical knowledge graph (supplied in JSON [Biolink](https://biolink.github.io/biolink-model/) format).

It accepts [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) query graphs. More specifically, it can answer these kinds of queries:

1. **Single-hop**: `(>=1 curies)--[>=0 predicates]--(>=0 categories, >=0 curies)`
2. **Edge-less**: Consist only of `QNode`s (all of which must have curies specified)

It currently only answers queries in an **undirected** fashion, but is poised to be able to do directed queries as well.

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

1. Install Docker (if needed)
    * For Ubuntu 18, instructions are [here](https://github.com/RTXteam/RTX/blob/master/code/kg2/install-docker-ubuntu18.sh)
    * For Mac, `brew install --cask docker` worked for me with macOS Big Sur
1. Clone this repo
1. Put your JSON KG file into `PloverDB/app/`
1. Update `PloverDB/app/kg_config.json` with your JSON KG file name and the names of the properties you want it to use as 'labels' for nodes/edges (e.g., `"predicate"` and `"expanded_categories"`)
1. If you're deploying it somewhere (not just using locally), make sure port `9990` (or one of your choosing) is open
1. `cd` into `PloverDB/`
1. Then build your Docker image and run a container based on it:
    * `docker build -t yourimage .`
    * `docker run -d --name yourcontainer -p 9990:80 yourimage`

*Note: You may need to add `sudo` in front of all docker commands, depending on your user.*

It should take a few minutes (appx. 10 minutes for [KG2c](https://github.com/RTXteam/RTX/tree/master/code/kg2/canonicalized)) to load the data and build indexes. You can do `docker logs yourcontainer` to check on its progress.

Once it's finished loading, you should be able to send it POST requests at the port you opened; the URL for this would look something like: `http://yourec2instance.rtx.ai:9990/query/`. Or, if you just want to use it locally: `http://localhost:9990/query/`.

### Credits

* Author: Amy Glen
* Inspiration/advice: Stephen Ramsey, Eric Deutsch, David Koslicki