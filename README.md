# PloverDB

This is a prototype **in-memory database service** that can answer **one-hop queries** on a given biomedical knowledge graph (supplied in JSON [Biolink](https://biolink.github.io/biolink-model/) format). It's currently tailored to work with [KG2c](https://github.com/RTXteam/RTX/tree/master/code/kg2/canonicalized).

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

### Deployment

1. Install Docker (if needed)
    * For Ubuntu 18, instructions are [here](https://github.com/RTXteam/RTX/blob/master/code/kg2/install-docker-ubuntu18.sh)
    * For Mac, `brew install --cask docker` worked for me with macOS Big Sur
1. Clone this repo and `cd` into it
1. Make sure port `9090` (or one of your choosing) is open
1. Then build your Docker image and run a container based on it:
    * `docker build -t yourimage .`
    * `docker run -d --name yourcontainer -p 9090:80 yourimage`

*Note: You may need to add `sudo` in front of all docker commands, depending on your user.*

It should take appx. 10 minutes to load the data and build indexes. You can do `docker logs yourcontainer` to check on its progress.

Once it's finished loading, you should be able to send it requests at the port you opened; the URL for this would look something like: `http://yourec2instance.rtx.ai:9090/query/`. Or, if you just want to use it locally: `http://localhost:9090/query/`.