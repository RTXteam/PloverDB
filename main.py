#!/usr/bin/env python3

def build_indexes():
    node_lookup_map = dict()

    # Then build the edge based indexes
    main_index = dict()
    edge_lookup_map = dict()

    return main_index, node_lookup_map, edge_lookup_map


def answer_query(json_file_name, main_index, node_lookup_map, edge_lookup_map):
    # For each input curie, see if it's in the main index (i.e., it has any edges)

    # If it is, see if it has any of the input predicates

    # For each of those predicates it has, grab all the forwards/backwards connections of the proper type

    # Once we have all dicts of output node IDs/edge IDs collected, form actual results for them

    return []


def main():
    # Create our indexes
    main_index, node_lookup_map, edge_lookup_map = build_indexes()

    # Wait for and run queries (have menu option for now? queries could be in JSON files to start)
    answer_query("test_query.json", main_index, node_lookup_map, edge_lookup_map)


if __name__ == "__main__":
    main()
