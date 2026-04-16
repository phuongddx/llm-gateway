.PHONY: install start stop health dev clean

# Default: install deps + start server
all: install start

# Install Python dependencies
install:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

# Start server in background on port 8000
start:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example — edit with your API keys"; fi
	@if lsof -ti:8000 > /dev/null 2>&1; then echo "Server already running on :8000"; else \
		nohup .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 & \
		sleep 1; \
		make health; fi

# Start with auto-reload (development)
dev:
	@if [ ! -f .env ]; then cp .env.example .env; fi
	.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Stop server
stop:
	@if lsof -ti:8000 > /dev/null 2>&1; then kill $$(lsof -ti:8000); echo "Server stopped"; else echo "No server running"; fi

# Health check
health:
	@curl -sf http://localhost:8000/health && echo "" || echo "Server not responding"

# Test chat endpoint (requires APP_API_KEY set in .env)
test:
	@curl -s -N -X POST http://localhost:8000/v1/chat/completions \
		-H "Authorization: Bearer $$(grep APP_API_KEY .env | cut -d= -f2)" \
		-H "Content-Type: application/json" \
		-d '{"messages":[{"role":"user","content":"Say hello in 3 words"}],"system_prompt":"You are a helpful assistant","stream":true}'

# Clean Python artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf *.egg-info dist build
