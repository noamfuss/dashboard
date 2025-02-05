from flask import Flask, render_template
import docker
from datetime import datetime
import threading
import time
import re
from waitress import serve
from os import getenv

app = Flask(__name__)

# Global variable to store discovered instances
discovered_instances = []

def get_traefik_routers():
    """
    Scan Docker containers for any Traefik router rules
    """
    client = docker.from_env()
    instances = []
    
    try:
        containers = client.containers.list()
        for container in containers:
            labels = container.labels
            
            # Find all Traefik router rules using regex pattern
            router_pattern = re.compile(r'traefik\.http\.routers\.(.+)\.rule')
            
            for label, value in labels.items():
                match = router_pattern.match(label)
                if match:
                    router_name = match.group(1)
                    instance = {
                        'container_id': container.short_id,
                        'name': container.name,
                        'router_name': router_name,
                        'rule': value,
                        'status': container.status,
                        'created': container.attrs['Created'],
                    }
                    instances.append(instance)
    
    except docker.errors.APIError as e:
        print(f"Error connecting to Docker: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        
    return instances

def background_scanner():
    """
    Background task to periodically scan for Traefik routers
    """
    global discovered_instances
    while True:
        discovered_instances = get_traefik_routers()
        time.sleep(30)  # Scan every 30 seconds

@app.route('/')
def home():
    return render_template('index.html', instances=discovered_instances)

if __name__ == '__main__':
    # Start background scanner thread
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()
    
    # Run Flask app
    serve(app, host=getenv("HOST", '0.0.0.0'), port=getenv("PORT", 5000))

