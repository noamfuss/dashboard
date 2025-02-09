FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY . .
RUN go mod init traefik-monitor && \
    go mod tidy && \
    go build -o /traefik-monitor

FROM alpine:latest
WORKDIR /app
COPY --from=builder /traefik-monitor /app/
COPY templates /app/templates
EXPOSE 80
CMD ["/app/traefik-monitor"]
