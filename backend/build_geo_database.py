import requests
import sqlite3
import json
import os

def main():
    db_path = os.path.join(os.path.dirname(__file__), "local_railways.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY,
            lat REAL,
            lon REAL,
            tags TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ways (
            id INTEGER PRIMARY KEY,
            nodes TEXT,
            tags TEXT
        )
    """)
    
    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = """[out:json];(node(-6.5,106.7,-6.1,106.9)["railway"];way(-6.5,106.7,-6.1,106.9)["railway"];);out body;>;out skel qt;"""
    
    print("Mengunduh data dari OSM...")
    headers = {
        'User-Agent': 'NusaRail_GeoBuilder/1.0'
    }
    response = requests.post(overpass_url, data={'data': overpass_query}, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        for element in data.get('elements', []):
            if element['type'] == 'node':
                cursor.execute(
                    "INSERT OR REPLACE INTO nodes (id, lat, lon, tags) VALUES (?, ?, ?, ?)",
                    (element['id'], element.get('lat'), element.get('lon'), json.dumps(element.get('tags', {})))
                )
            elif element['type'] == 'way':
                cursor.execute(
                    "INSERT OR REPLACE INTO ways (id, nodes, tags) VALUES (?, ?, ?)",
                    (element['id'], json.dumps(element.get('nodes', [])), json.dumps(element.get('tags', {})))
                )
        
        conn.commit()
        conn.close()
        print("Database spasial berhasil dibuat!")
    else:
        print(f"Gagal mengunduh data. Status code: {response.status_code}")

if __name__ == "__main__":
    main()
