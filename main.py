from flask import Flask, render_template
import docker
from datetime import datetime
import threading
import time
import re

app = Flask(__name__)

# Global variable to store discovered instances
discovered_instances = []

def get_glances_instances():
    """
    Scan Docker containers for Traefik router rules related to Glances
    """
    client = docker.from_env()
    instances = []
    
    try:
        containers = client.containers.list()
        print(f"{containers = }")
        for container in containers:
            labels = container.labels
            # Look for the specific Traefik router rule
            rule_key = 'traefik.http.routers.glances.rule'
            print(f"{labels = }")
            match = re.search(r'traefik\.http\.routers\..*.rule', labels)
            if rule_key in labels:
                instance = {
                    'container_id': container.short_id,
                    'name': container.name,
                    'rule': labels[rule_key],
                    'status': container.status,
                    'created': container.attrs['Created'],
                }
                instances.append(instance)
    except docker.errors.APIError as e:
        print(f"Error connecting to Docker: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    print(f"{instances = }")
    return instances


def background_scanner():
    """
    Background task to periodically scan for Glances instances
    """
    global discovered_instances
    while True:
        discovered_instances = get_glances_instances()
        time.sleep(30)  # Scan every 30 seconds


# Create templates directory and add HTML template
@app.route('/')
def home():
    return render_template('index.html', instances=discovered_instances)


if __name__ == '__main__':
    
    # Start background scanner thread
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=False)
