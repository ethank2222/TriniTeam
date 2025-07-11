// Enhanced Multi-Agent System Service Worker
// Provides offline functionality and performance optimizations

const CACHE_NAME = "multi-agent-system-v1.0.0";
const API_CACHE_NAME = "multi-agent-api-v1.0.0";
const STATIC_CACHE_NAME = "multi-agent-static-v1.0.0";

// Files to cache for offline functionality
const STATIC_FILES = [
    "/",
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/manifest.json",
    "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap",
    "https://fonts.googleapis.com/css2?family=Fira+Code:wght@300;400;500;600&display=swap",
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js",
];

// API endpoints to cache
const API_ENDPOINTS = [
    "/api/agents",
    "/api/metrics",
    "/api/messages",
    "/api/config",
];

// Cache strategies
const CACHE_STRATEGIES = {
    CACHE_FIRST: "cache-first",
    NETWORK_FIRST: "network-first",
    STALE_WHILE_REVALIDATE: "stale-while-revalidate",
    NETWORK_ONLY: "network-only",
    CACHE_ONLY: "cache-only",
};

// Service Worker Installation
self.addEventListener("install", (event) => {
    console.log("🔧 Service Worker: Installing...");

    event.waitUntil(
        Promise.all([
            // Cache static files
            caches.open(STATIC_CACHE_NAME).then((cache) => {
                console.log("📦 Service Worker: Caching static files");
                return cache.addAll(STATIC_FILES);
            }),

            // Cache API responses
            caches.open(API_CACHE_NAME).then((cache) => {
                console.log("📡 Service Worker: Preparing API cache");
                return Promise.all(
                    API_ENDPOINTS.map((endpoint) => {
                        return fetch(endpoint)
                            .then((response) => {
                                if (response.ok) {
                                    return cache.put(
                                        endpoint,
                                        response.clone()
                                    );
                                }
                            })
                            .catch(() => {
                                console.log(
                                    `⚠️ Service Worker: Could not cache ${endpoint}`
                                );
                            });
                    })
                );
            }),
        ]).then(() => {
            console.log("✅ Service Worker: Installation complete");
            self.skipWaiting();
        })
    );
});

// Service Worker Activation
self.addEventListener("activate", (event) => {
    console.log("🚀 Service Worker: Activating...");

    event.waitUntil(
        caches
            .keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        // Delete old caches
                        if (
                            cacheName !== CACHE_NAME &&
                            cacheName !== API_CACHE_NAME &&
                            cacheName !== STATIC_CACHE_NAME
                        ) {
                            console.log(
                                `🗑️ Service Worker: Deleting old cache: ${cacheName}`
                            );
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
            .then(() => {
                console.log("✅ Service Worker: Activation complete");
                self.clients.claim();
            })
    );
});

// Fetch Event Handler
self.addEventListener("fetch", (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Handle different types of requests
    if (request.method === "GET") {
        if (url.pathname.startsWith("/api/")) {
            // API requests - use network-first strategy
            event.respondWith(handleAPIRequest(request));
        } else if (
            url.pathname.startsWith("/static/") ||
            url.hostname !== location.hostname
        ) {
            // Static files and CDN resources - use cache-first strategy
            event.respondWith(handleStaticRequest(request));
        } else {
            // HTML pages - use stale-while-revalidate strategy
            event.respondWith(handlePageRequest(request));
        }
    } else {
        // POST, PUT, DELETE requests - always use network
        event.respondWith(handleNetworkOnlyRequest(request));
    }
});

// API Request Handler - Network First with Fallback
async function handleAPIRequest(request) {
    const cache = await caches.open(API_CACHE_NAME);

    try {
        // Try network first
        const networkResponse = await fetch(request.clone());

        if (networkResponse.ok) {
            // Cache successful responses
            cache.put(request, networkResponse.clone());
            return networkResponse;
        }

        // If network fails, try cache
        const cachedResponse = await cache.match(request);
        if (cachedResponse) {
            console.log("📡 Service Worker: Serving API from cache");
            return cachedResponse;
        }

        // If no cache, return network response (even if not ok)
        return networkResponse;
    } catch (error) {
        console.error(
            "🚨 Service Worker: Network error for API request",
            error
        );

        // Network failed, try cache
        const cachedResponse = await cache.match(request);
        if (cachedResponse) {
            console.log(
                "📡 Service Worker: Serving API from cache (network failed)"
            );
            return cachedResponse;
        }

        // Return offline response
        return new Response(
            JSON.stringify({
                error: "Offline",
                message:
                    "Unable to connect to server. Please check your internet connection.",
            }),
            {
                status: 503,
                headers: { "Content-Type": "application/json" },
            }
        );
    }
}

// Static Request Handler - Cache First
async function handleStaticRequest(request) {
    const cache = await caches.open(STATIC_CACHE_NAME);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
        console.log("📦 Service Worker: Serving static from cache");
        return cachedResponse;
    }

    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.error(
            "🚨 Service Worker: Failed to fetch static resource",
            error
        );
        return new Response("Resource not available offline", { status: 503 });
    }
}

// Page Request Handler - Stale While Revalidate
async function handlePageRequest(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);

    const networkResponsePromise = fetch(request)
        .then((response) => {
            if (response.ok) {
                cache.put(request, response.clone());
            }
            return response;
        })
        .catch((error) => {
            console.error(
                "🚨 Service Worker: Network error for page request",
                error
            );
            return null;
        });

    // Return cached version immediately if available
    if (cachedResponse) {
        console.log("📄 Service Worker: Serving page from cache");

        // Update cache in background
        networkResponsePromise.then((response) => {
            if (response) {
                console.log("🔄 Service Worker: Updated cache in background");
            }
        });

        return cachedResponse;
    }

    // No cache available, wait for network
    const networkResponse = await networkResponsePromise;
    if (networkResponse) {
        return networkResponse;
    }

    // Network failed and no cache, return offline page
    return new Response(
        `<!DOCTYPE html>
        <html>
        <head>
            <title>Multi-Agent System - Offline</title>
            <style>
                body {
                    font-family: 'Inter', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
                }
                .offline-container {
                    text-align: center;
                    padding: 2rem;
                    background: white;
                    border-radius: 1rem;
                    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
                }
                .offline-icon {
                    font-size: 4rem;
                    margin-bottom: 1rem;
                    color: #ef4444;
                }
                h1 { color: #1f2937; margin-bottom: 1rem; }
                p { color: #6b7280; margin-bottom: 1.5rem; }
                .retry-btn {
                    background: #0ea5e9;
                    color: white;
                    border: none;
                    padding: 0.75rem 1.5rem;
                    border-radius: 0.5rem;
                    cursor: pointer;
                    font-size: 1rem;
                    transition: background 0.3s;
                }
                .retry-btn:hover {
                    background: #0284c7;
                }
            </style>
        </head>
        <body>
            <div class="offline-container">
                <div class="offline-icon">📡</div>
                <h1>You're Offline</h1>
                <p>The Multi-Agent System is currently unavailable. Please check your internet connection.</p>
                <button class="retry-btn" onclick="window.location.reload()">Retry Connection</button>
            </div>
        </body>
        </html>`,
        {
            status: 503,
            headers: { "Content-Type": "text/html" },
        }
    );
}

// Network Only Handler
async function handleNetworkOnlyRequest(request) {
    try {
        return await fetch(request);
    } catch (error) {
        console.error("🚨 Service Worker: Network-only request failed", error);
        return new Response(
            JSON.stringify({
                error: "Network Error",
                message: "Unable to complete request. Please try again.",
            }),
            {
                status: 503,
                headers: { "Content-Type": "application/json" },
            }
        );
    }
}

// Background Sync for offline actions
self.addEventListener("sync", (event) => {
    if (event.tag === "background-sync") {
        console.log("🔄 Service Worker: Background sync triggered");
        event.waitUntil(syncOfflineActions());
    }
});

// Sync offline actions when back online
async function syncOfflineActions() {
    try {
        // Get stored offline actions
        const offlineActions = await getOfflineActions();

        for (const action of offlineActions) {
            try {
                await fetch(action.url, {
                    method: action.method,
                    headers: action.headers,
                    body: action.body,
                });

                // Remove successful action
                await removeOfflineAction(action.id);
            } catch (error) {
                console.error(
                    "🚨 Service Worker: Failed to sync action",
                    error
                );
            }
        }

        console.log("✅ Service Worker: Background sync completed");
    } catch (error) {
        console.error("🚨 Service Worker: Background sync failed", error);
    }
}

// Store offline actions
async function storeOfflineAction(action) {
    const db = await openDB();
    const tx = db.transaction(["offlineActions"], "readwrite");
    const store = tx.objectStore("offlineActions");
    await store.add(action);
}

// Get offline actions
async function getOfflineActions() {
    const db = await openDB();
    const tx = db.transaction(["offlineActions"], "readonly");
    const store = tx.objectStore("offlineActions");
    return await store.getAll();
}

// Remove offline action
async function removeOfflineAction(id) {
    const db = await openDB();
    const tx = db.transaction(["offlineActions"], "readwrite");
    const store = tx.objectStore("offlineActions");
    await store.delete(id);
}

// Open IndexedDB
async function openDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open("MultiAgentSystemDB", 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains("offlineActions")) {
                const store = db.createObjectStore("offlineActions", {
                    keyPath: "id",
                });
                store.createIndex("timestamp", "timestamp");
            }
        };
    });
}

// Push notification handling
self.addEventListener("push", (event) => {
    console.log("📱 Service Worker: Push notification received");

    const options = {
        body: "Multi-Agent System notification",
        vibrate: [100, 50, 100],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: 1,
        },
        actions: [
            {
                action: "explore",
                title: "Open App",
            },
            {
                action: "close",
                title: "Close",
            },
        ],
    };

    if (event.data) {
        const data = event.data.json();
        options.body = data.body || options.body;
        options.title = data.title || "Multi-Agent System";
    }

    event.waitUntil(self.registration.showNotification(options.title, options));
});

// Notification click handling
self.addEventListener("notificationclick", (event) => {
    console.log("📱 Service Worker: Notification clicked");

    event.notification.close();

    if (event.action === "explore") {
        event.waitUntil(clients.openWindow("/"));
    } else if (event.action === "close") {
        // Just close the notification
        return;
    } else {
        // Default action - open app
        event.waitUntil(clients.openWindow("/"));
    }
});

// Performance monitoring
self.addEventListener("message", (event) => {
    if (event.data && event.data.type === "PERFORMANCE_MEASURE") {
        console.log("📊 Service Worker: Performance measure", event.data.data);

        // Store performance data
        storePerformanceData(event.data.data);
    }
});

// Store performance data
async function storePerformanceData(data) {
    try {
        const db = await openDB();
        const tx = db.transaction(["performance"], "readwrite");
        const store = tx.objectStore("performance");
        await store.add({
            ...data,
            timestamp: Date.now(),
        });
    } catch (error) {
        console.error(
            "🚨 Service Worker: Failed to store performance data",
            error
        );
    }
}

// Cleanup old data
setInterval(async () => {
    try {
        const db = await openDB();
        const tx = db.transaction(["performance"], "readwrite");
        const store = tx.objectStore("performance");

        // Remove data older than 7 days
        const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
        const index = store.index("timestamp");
        const range = IDBKeyRange.upperBound(cutoff);

        const request = index.openCursor(range);
        request.onsuccess = (event) => {
            const cursor = event.target.result;
            if (cursor) {
                cursor.delete();
                cursor.continue();
            }
        };
    } catch (error) {
        console.error("🚨 Service Worker: Failed to cleanup old data", error);
    }
}, 24 * 60 * 60 * 1000); // Run daily

console.log("🎯 Service Worker: Loaded and ready");
