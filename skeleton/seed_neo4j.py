"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # TODO: Design your node labels and create metro station nodes.
        # Each station has: station_id, name, lines, and interchange info.
        # See metro_stations.json for the full data structure.
        print("  Creating Metro Station nodes...")
        for ms in metro_stations:
            session.run("""
                CREATE (n:MetroStation {
                    station_id: $station_id,
                    station_name: $station_name,
                    lines: $lines,
                    is_interchange_metro: $is_interchange_metro,
                    is_interchange_national_rail: $is_interchange_national_rail
                })
            """, station_id=ms['station_id'], station_name=ms['name'], lines=ms['lines'],
                 is_interchange_metro=ms.get('is_interchange_metro', False),
                 is_interchange_national_rail=ms.get('is_interchange_national_rail', False))

        # TODO: Design your node labels and create national rail station nodes.
        # See national_rail_stations.json for the full data structure.
        print("  Creating National Rail Station nodes...")
        for ns in rail_stations:
            session.run("""
                CREATE (n:NationalRailStation {
                    station_id: $station_id,
                    station_name: $station_name,
                    lines: $lines,
                    is_interchange_national_rail: $is_interchange_national_rail,
                    is_interchange_metro: $is_interchange_metro
                })
            """, station_id=ns['station_id'], station_name=ns['name'], lines=ns['lines'],
                 is_interchange_national_rail=ns.get('is_interchange_national_rail', False),
                 is_interchange_metro=ns.get('is_interchange_metro', False))

        # TODO: Design your relationship types and create metro links.
        # Each station lists its adjacent_stations with line and travel_time_min.
        # Consider what properties to store on the relationship.
        print("  Creating Metro links...")
        for ms in metro_stations:
            for adj in ms.get('adjacent_stations', []):
                session.run("""
                    MATCH (a:MetroStation {station_id: $source_id})
                    MATCH (b:MetroStation {station_id: $target_id})
                    MERGE (a)-[r:METRO_LINK {line_id: $line}]->(b)
                    SET r.travel_time_min = $time
                """, source_id=ms['station_id'], target_id=adj['station_id'], 
                     line=adj.get('line', adj.get('line_id')), time=adj['travel_time_min'])

        # TODO: Design your relationship types and create national rail links.
        print("  Creating National Rail links...")
        for ns in rail_stations:
            for adj in ns.get('adjacent_stations', []):
                session.run("""
                    MATCH (a:NationalRailStation {station_id: $source_id})
                    MATCH (b:NationalRailStation {station_id: $target_id})
                    MERGE (a)-[r:RAIL_LINK {line_id: $line}]->(b)
                    SET r.travel_time_min = $time
                """, source_id=ns['station_id'], target_id=adj['station_id'], 
                     line=adj.get('line', adj.get('line_id')), time=adj['travel_time_min'])

        # TODO: Create interchange relationships between metro and rail stations.
        # Interchange info is in the is_interchange_national_rail field
        # of metro_stations.json.
        print("  Creating Interchange links...")
        for ms in metro_stations:
            if ms.get('is_interchange_national_rail'):
                nr_id = ms.get('interchange_national_rail_station_id')
                if nr_id:
                    session.run("""
                        MATCH (m:MetroStation {station_id: $ms_id})
                        MATCH (r:NationalRailStation {station_id: $nr_id})
                        MERGE (m)-[:INTERCHANGE]->(r)
                        MERGE (r)-[:INTERCHANGE]->(m)
                    """, ms_id=ms['station_id'], nr_id=nr_id)

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
