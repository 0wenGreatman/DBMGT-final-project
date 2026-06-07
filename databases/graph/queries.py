"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    # Determine the allowed relationship types based on the requested network.
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        # In 'auto' mode, infer the network from the station ID prefixes.
        if origin_id.startswith("MS") and destination_id.startswith("MS"):
            rel_types = "METRO_LINK"
        elif origin_id.startswith("NR") and destination_id.startswith("NR"):
            rel_types = "RAIL_LINK"
        else:
            # Fallback to allow both if IDs are mixed or format is unknown.
            rel_types = "METRO_LINK|RAIL_LINK"

    # Cypher query utilizing APOC Dijkstra algorithm for the shortest path
    # weighted by the 'travel_time_min' property on relationships.
    query = """
        MATCH (start {station_id: $origin_id})
        MATCH (end {station_id: $destination_id})
        CALL apoc.algo.dijkstra(start, end, $rel_types, 'travel_time_min') YIELD path, weight
        RETURN nodes(path) AS stations,
               relationships(path) AS links,
               weight AS total_time_min
    """
    
    try:
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(query, origin_id=origin_id, destination_id=destination_id, rel_types=rel_types)
                record = result.single()
                
                if not record:
                    print(f"[Info] query_shortest_route: No route found from '{origin_id}' to '{destination_id}'.")
                    return {
                        "found": False,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "total_time_min": 0,
                        "path": [],
                        "legs": []
                    }
                
                path_nodes = []
                # Extract station details into a list of dictionaries
                for node in record["stations"]:
                    path_nodes.append({
                        "station_id": node.get("station_id"),
                        "name": node.get("station_name"),
                        "lines": node.get("lines")
                    })
                
                legs = []
                # Extract leg details for each relationship in the path
                for rel in record["links"]:
                    legs.append({
                        "line": rel.get("line_id"),
                        "travel_time_min": rel.get("travel_time_min"),
                        "type": rel.type
                    })
                    
                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_time_min": record["total_time_min"],
                    "path": path_nodes,
                    "legs": legs
                }
    except Exception as e:
        # Provide a fallback error handler to prevent the app from crashing on DB failure
        print(f"[Error] query_shortest_route failed for {origin_id} -> {destination_id}: {e}")
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "total_time_min": 0,
            "path": [],
            "legs": []
        }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    # 1. Determine relationship types to traverse based on the network parameter.
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        # Infer network bounds based on station ID prefixes for 'auto' mode.
        if origin_id.startswith("MS") and destination_id.startswith("MS"):
            rel_types = "METRO_LINK"
        elif origin_id.startswith("NR") and destination_id.startswith("NR"):
            rel_types = "RAIL_LINK"
        else:
            rel_types = "METRO_LINK|RAIL_LINK|INTERCHANGE"

    # Define the weight property dynamically based on the requested fare class.
    # Note: If these properties are not seeded on the graph edges, APOC Dijkstra
    # will naturally fall back to weight 1.0 (minimizing hops), which works well
    # since fares scale linearly with the number of stops.
    weight_prop = "fare_first" if fare_class.lower() == "first" else "fare_standard"

    # 2. Cypher query utilizing APOC Dijkstra algorithm for the cheapest path.
    query = """
        MATCH (start {station_id: $origin_id})
        MATCH (end {station_id: $destination_id})
        CALL apoc.algo.dijkstra(start, end, $rel_types, $weight_prop) YIELD path, weight
        RETURN nodes(path) AS stations,
               relationships(path) AS links
    """

    try:
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(
                    query, 
                    origin_id=origin_id, 
                    destination_id=destination_id, 
                    rel_types=rel_types,
                    weight_prop=weight_prop
                )
                record = result.single()

                if not record:
                    print(f"[Info] query_cheapest_route: No route found from '{origin_id}' to '{destination_id}'.")
                    return {
                        "found": False,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "total_fare_usd": 0.0,
                        "stations": [],
                        "legs": []
                    }

                # Extract station details into a list of dictionaries.
                stations = []
                for node in record["stations"]:
                    stations.append({
                        "station_id": node.get("station_id"),
                        "name": node.get("station_name"),
                        "lines": node.get("lines")
                    })

                # Extract legs and keep track of hops per network to calculate the exact fare.
                legs = []
                metro_hops = 0
                rail_hops = 0

                for rel in record["links"]:
                    rel_type = rel.type
                    legs.append({
                        "line": rel.get("line_id", "Interchange"),
                        "travel_time_min": rel.get("travel_time_min", 5.0), # Default 5 mins for interchange
                        "type": rel_type
                    })
                    
                    if rel_type == "METRO_LINK":
                        metro_hops += 1
                    elif rel_type == "RAIL_LINK":
                        rail_hops += 1

                # 3. Calculate exact total estimated fare based on the mock data rules.
                # Metro formula: $0.80 base + $0.30 per stop
                # Rail Standard formula: $2.50 base + $1.50 per stop
                # Rail First Class formula: $4.00 base + $2.50 per stop
                total_fare = 0.0
                if metro_hops > 0:
                    total_fare += 0.80 + (metro_hops * 0.30)
                if rail_hops > 0:
                    if fare_class.lower() == "first":
                        total_fare += 4.00 + (rail_hops * 2.50)
                    else:
                        total_fare += 2.50 + (rail_hops * 1.50)

                return {
                    "found": True,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_fare_usd": round(total_fare, 2),
                    "stations": stations,
                    "legs": legs
                }
    except Exception as e:
        # Provide a fallback error handler to prevent the application from crashing
        # in case of a database connectivity issue or syntax error.
        print(f"[Error] query_cheapest_route failed for {origin_id} -> {destination_id}: {e}")
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "total_fare_usd": 0.0,
            "stations": [],
            "legs": []
        }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    # Cypher query utilizing APOC Dijkstra algorithm to find the shortest path
    # weighted by the 'travel_time_min' property, defaulting to 5 mins for INTERCHANGE links.
    query = """
        MATCH (start {station_id: $origin_id})
        MATCH (end {station_id: $destination_id})
        CALL apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE', 'travel_time_min', 5.0) YIELD path, weight
        RETURN nodes(path) AS stations,
               relationships(path) AS links,
               weight AS total_time_min
    """
    try:
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(query, origin_id=origin_id, destination_id=destination_id)
                record = result.single()

                if not record:
                    print(f"[Info] query_interchange_path: No path found from '{origin_id}' to '{destination_id}'.")
                    return {
                        "found": False,
                        "stations": [],
                        "interchange_points": [],
                        "total_time_min": 0
                    }

                stations = []
                interchange_points = []
                
                # Extract station details into a list of dictionaries
                for node in record["stations"]:
                    stations.append({
                        "station_id": node.get("station_id"),
                        "name": node.get("station_name"),
                        "lines": node.get("lines")
                    })
                    
                # Identify interchange points by inspecting relationships for type 'INTERCHANGE'
                for rel in record["links"]:
                    if rel.type == "INTERCHANGE":
                        # Add the start and end node names of the interchange relationship
                        for node in rel.nodes:
                            node_name = node.get("station_name")
                            if node_name not in interchange_points:
                                interchange_points.append(node_name)

                return {
                    "found": True,
                    "stations": stations,
                    "interchange_points": interchange_points,
                    "total_time_min": record["total_time_min"]
                }
    except Exception as e:
        # Provide a fallback error handler to ensure the app doesn't crash on DB failure
        print(f"[Error] query_interchange_path failed for {origin_id} -> {destination_id}: {e}")
        return {
            "found": False,
            "stations": [],
            "interchange_points": [],
            "total_time_min": 0
        }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    # MATCH: Finds paths 'p' starting from the delayed station and traversing outwards by 1 to 'hops' relationships.
    # WHERE: Filters out the starting station itself so it doesn't appear in the results.
    # WITH: Groups by 'affected' station and finds the shortest path length (min(length(p))) to avoid duplicates.
    query = f"""
        MATCH p = (start {{station_id: $delayed_station_id}})-[*1..{hops}]-(affected)
        WHERE affected.station_id <> $delayed_station_id
        WITH affected, min(length(p)) AS hops_away
        RETURN affected.station_id AS station_id,
               affected.station_name AS name,
               hops_away,
               affected.lines AS lines_affected
        ORDER BY hops_away, station_id
    """
    try:
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(query, delayed_station_id=delayed_station_id)
                
                affected_stations = []
                # Iterate through the returned records and map them to a list of dictionaries
                for record in result:
                    affected_stations.append({
                        "station_id": record.get("station_id"),
                        "name": record.get("name"),
                        "hops_away": record.get("hops_away"),
                        "lines_affected": record.get("lines_affected")
                    })
                
                # Check if the result list is empty and log an informational message
                if not affected_stations:
                    print(f"[Info] query_delay_ripple: No data found for station '{delayed_station_id}' within {hops} hops.")
                    
                return affected_stations
    except Exception as e:
        # Catch any connection or query execution errors to prevent the app from crashing
        print(f"[Error] query_delay_ripple failed for station '{delayed_station_id}': {e}")
        return []


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    query = """
        MATCH (a {station_id: $station_id})-[r]->(b)
        RETURN b.station_id AS target_id,
               b.station_name AS target_name,
               type(r) AS connection_type,
               r.line_id AS line,
               r.travel_time_min AS travel_time_min
    """
    try:
        with _driver() as driver:
            with driver.session() as session:
                result = session.run(query, station_id=station_id)
                
                connections = []
                # Iterate through the returned records and extract connection details into a dictionary
                for record in result:
                    connections.append({
                        "target_id": record.get("target_id"),
                        "target_name": record.get("target_name"),
                        "connection_type": record.get("connection_type"),
                        "line": record.get("line"),
                        "travel_time_min": record.get("travel_time_min")
                    })
                
                # Log an informational message if no connections were found for the given station
                if not connections:
                    print(f"[Info] query_station_connections: No connections found for station '{station_id}'.")
                    
                return connections
    except Exception as e:
        # Catch and log any exceptions (e.g., database connection issues) to avoid unhandled crashes
        print(f"[Error] query_station_connections failed for station '{station_id}': {e}")
        return []
