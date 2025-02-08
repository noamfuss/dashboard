# dashboard
A simple link dashboard for Traefik reverse proxied containers

This simple Flask application provides a dashboard for easily accessing your Traefik-proxied containers. 
While Traefik's built-in dashboard is powerful, it lacks a direct way to open links to your services. 
This application aims to solve this by creating a simple link page, automatically populated with links based on Traefik's routers, using its API.

To run it, adjust `docker-compose.yaml` to match your setup, and run:
```
docker compose up -d
```
