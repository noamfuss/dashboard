from flask import Flask, render_template
from waitress import serve
import requests
from datetime import datetime
import threading
import time
import logging
import os
from urllib.parse import urljoin

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global variable to store discovered routers
discovered_routers = []

def get_traefik_routers():
    """
    Get routers from Traefik API
    """
    traefik_api = os.environ.get('TRAEFIK_API')
    if not traefik_api:
        logger.error("TRAEFIK_API environment variable not set")
        return []
    
    try:
        # Get both HTTP and TCP routers
        http_url = urljoin(traefik_api, '/api/http/routers')
        tcp_url = urljoin(traefik_api, '/api/tcp/routers')
        
        routers = []
        
        # Fetch HTTP routers
        try:
            http_response = requests.get(http_url, timeout=5)
            if http_response.status_code == 200:
                for router in http_response.json():
                    # Ignore internal routers
                    if router.get('name', '').endswith('internal'):
                        # print(f"{router = }")
                        continue
                        
                    routers.append({
                        'name': router.get('name', 'unknown'),
                        'rule': router.get('rule', ''),
                        'service': router.get('service', ''),
                        'status': 'enabled' if router.get('status', 'disabled') == 'enabled' else 'disabled',
                        'entryPoints': router.get('entryPoints', []),
                        'tls': 'Yes' if router.get('tls', False) else 'No'
                    })
            # logger.info(f"Found {len(routers)} HTTP routers")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching HTTP routers: {e}")

        return routers

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return []

def background_scanner():
    """
    Background task to periodically scan for Traefik routers
    """
    global discovered_routers
    while True:
        discovered_routers = get_traefik_routers()
        time.sleep(30)  # Scan every 30 seconds


@app.route('/')
def home():
    return render_template('index.html', instances=discovered_routers)


@app.route('/health')
def health():
    """
    Health check endpoint that also verifies Traefik API connectivity
    """
    traefik_api = os.environ.get('TRAEFIK_API')
    if not traefik_api:
        return {"status": "unhealthy", "error": "TRAEFIK_API not configured"}, 503
    
    try:
        response = requests.get(urljoin(traefik_api, '/api/http/routers'), timeout=5)
        if response.status_code == 200:
            return {"status": "healthy", "traefik_connected": True}, 200
        return {"status": "unhealthy", "traefik_connected": False, "status_code": response.status_code}, 503
    except requests.exceptions.RequestException as e:
        return {"status": "unhealthy", "traefik_connected": False, "error": str(e)}, 503

if __name__ == '__main__':
    # Test Traefik API connection on startup
    if not os.environ.get('TRAEFIK_API'):
        logger.error("TRAEFIK_API environment variable must be set")
        logger.error("Example: http://traefik:8080")
    
    # Start background scanner thread
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()
    
    # Run Flask app
    port = int(os.environ.get('PORT', 5000))
    serve(app, host=os.getenv("HOST", '0.0.0.0'), port=port)
