package main

import (
	"encoding/json"
	"fmt"
	"regexp"
	"html/template"
	"log"
	"net/http"
	"os"
	"sync"
	"time"
)

// Router represents a Traefik router
type Router struct {
	Name        string   `json:"name"`
	Rule        string   `json:"rule"`
	Service     string   `json:"service"`
	Status      string   `json:"status"`
	EntryPoints []string `json:"entryPoints"`
	// TLS         bool     `json:"tls"`
}

func extractURL(rule string) string {
    re := regexp.MustCompile(`Host\(` + "`" + `([^` + "`" + `]+)` + "`" + `\)`) 
    matches := re.FindStringSubmatch(rule)
    if len(matches) > 1 {
        return fmt.Sprintf("https://%s", matches[1])
    }
    return "#"
}

// PageData represents the data passed to the template
type PageData struct {
	Instances []RouterInfo
}

// RouterInfo is the processed router information for display
type RouterInfo struct {
	Name        string
	Rule        string
	Service     string
	Status      string
	EntryPoints []string
	// TLS         string
	URL         string

}

var (
	discoveredRouters []RouterInfo
	routersMutex     sync.RWMutex
)

func getTraefikRouters() ([]RouterInfo, error) {
	traefikAPI := os.Getenv("TRAEFIK_API")
	if traefikAPI == "" {
		return nil, fmt.Errorf("TRAEFIK_API environment variable not set")
	}

	httpURL := fmt.Sprintf("%s/api/http/routers", traefikAPI)
	client := &http.Client{Timeout: 5 * time.Second}

	resp, err := client.Get(httpURL)
	if err != nil {
		return nil, fmt.Errorf("error fetching HTTP routers: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var routers []Router
	if err := json.NewDecoder(resp.Body).Decode(&routers); err != nil {
		return nil, fmt.Errorf("error decoding response: %v", err)
	}

	var processedRouters []RouterInfo
	for _, router := range routers {
		// Skip internal routers
		if len(router.Name) > 8 && router.Name[len(router.Name)-8:] == "internal" {
			continue
		}

		status := "enabled"
		if router.Status == "disabled" {
			status = "disabled"
		}

		// tls := "No"
		// if router.TLS {
			// tls = "Yes"
		// }

		processedRouters = append(processedRouters, RouterInfo{
			Name:        router.Name,
			Rule:        router.Rule,
			Service:     router.Service,
			Status:      status,
			URL:         extractURL(router.Rule),
			// EntryPoints: router.EntryPoints,
			// TLS:        tls,
		})
	}

	return processedRouters, nil
}

func backgroundScanner() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		routers, err := getTraefikRouters()
		if err != nil {
			log.Printf("Error getting routers: %v", err)
		} else {
			routersMutex.Lock()
			discoveredRouters = routers
			routersMutex.Unlock()
		}
		<-ticker.C
	}
}

func homeHandler(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}

	tmpl, err := template.ParseFiles("templates/index.html")
	if err != nil {
		log.Printf("Error parsing template: %v", err)
		http.Error(w, "Internal Server Error", http.StatusInternalServerError)
		return
	}

	routersMutex.RLock()
	data := PageData{Instances: discoveredRouters}
	routersMutex.RUnlock()

	if err := tmpl.Execute(w, data); err != nil {
		log.Printf("Error executing template: %v", err)
		http.Error(w, "Internal Server Error", http.StatusInternalServerError)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	traefikAPI := os.Getenv("TRAEFIK_API")
	if traefikAPI == "" {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "unhealthy",
			"error":  "TRAEFIK_API not configured",
		})
		return
	}

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(fmt.Sprintf("%s/api/http/routers", traefikAPI))
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":            "unhealthy",
			"traefik_connected": false,
			"error":            err.Error(),
		})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":            "healthy",
			"traefik_connected": true,
		})
		return
	}

	w.WriteHeader(http.StatusServiceUnavailable)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":            "unhealthy",
		"traefik_connected": false,
		"status_code":       resp.StatusCode,
	})
}

func main() {
	// Check for TRAEFIK_API environment variable
	if os.Getenv("TRAEFIK_API") == "" {
		log.Println("TRAEFIK_API environment variable must be set")
		log.Println("Example: http://traefik:8080")
	}

	// Start background scanner
	go backgroundScanner()

	// Set up routes
	http.HandleFunc("/", homeHandler)
	http.HandleFunc("/health", healthHandler)

	// Get port from environment or use default
	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}

	host := os.Getenv("HOST")
	if host == "" {
		host = "0.0.0.0"
	}

	addr := fmt.Sprintf("%s:%s", host, port)
	log.Printf("Starting server on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("Error starting server: %v", err)
	}
}
