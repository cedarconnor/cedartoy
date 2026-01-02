class WebSocketClient {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.handlers = {};
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }

    connect() {
        return new Promise((resolve, reject) => {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log('WebSocket connected to', this.url);
                this.reconnectAttempts = 0;
                resolve();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                reject(error);
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    const handler = this.handlers[data.type];
                    if (handler) {
                        handler(data);
                    } else {
                        console.log('Unhandled WebSocket message:', data);
                    }
                } catch (err) {
                    console.error('Error parsing WebSocket message:', err);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                // Auto-reconnect with backoff
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
                    console.log(`Reconnecting in ${delay}ms...`);
                    setTimeout(() => this.connect().catch(() => {}), delay);
                }
            };
        });
    }

    on(type, handler) {
        this.handlers[type] = handler;
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.error('WebSocket is not connected');
        }
    }

    close() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Create a global WebSocket client for render progress
export const wsClient = new WebSocketClient(`ws://${window.location.host}/ws/render`);
