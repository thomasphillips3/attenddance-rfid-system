// AttenDANCE Service Worker
const CACHE_NAME = 'attenddance-v1.0.0';
const STATIC_CACHE_URLS = [
    '/',
    '/dashboard',
    '/students',
    '/classes',
    '/attendance',
    '/auth/login',
    '/static/manifest.json',
    // External CDN resources
    'https://cdn.tailwindcss.com',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
    'https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js'
];

// Install event - cache static resources
self.addEventListener('install', event => {
    console.log('Service Worker: Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Service Worker: Caching static resources');
                return cache.addAll(STATIC_CACHE_URLS);
            })
            .catch(err => {
                console.error('Service Worker: Error caching static resources', err);
            })
    );
    // Force the waiting service worker to become the active service worker
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    console.log('Service Worker: Activating...');
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Service Worker: Deleting old cache', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    // Take control of all clients immediately
    self.clients.claim();
});

// Fetch event - serve cached content when offline
self.addEventListener('fetch', event => {
    const { request } = event;
    const { url, method } = request;

    // Only handle GET requests
    if (method !== 'GET') {
        return;
    }

    // Skip cross-origin requests
    if (!url.startsWith(self.location.origin) && !isCDNRequest(url)) {
        return;
    }

    event.respondWith(
        caches.match(request)
            .then(cachedResponse => {
                // Return cached version if available
                if (cachedResponse) {
                    console.log('Service Worker: Serving from cache', url);
                    return cachedResponse;
                }

                // For API requests, try network first
                if (isAPIRequest(url)) {
                    return fetchAndCache(request);
                }

                // For other requests, try network with fallback
                return fetch(request)
                    .then(response => {
                        // Cache successful responses
                        if (response.status === 200) {
                            const responseClone = response.clone();
                            caches.open(CACHE_NAME)
                                .then(cache => cache.put(request, responseClone));
                        }
                        return response;
                    })
                    .catch(() => {
                        // Return offline page for navigation requests
                        if (request.mode === 'navigate') {
                            return caches.match('/offline.html') || 
                                   caches.match('/') ||
                                   new Response('Offline - AttenDANCE', {
                                       status: 200,
                                       headers: { 'Content-Type': 'text/html' }
                                   });
                        }
                        
                        // Return a basic offline response for other requests
                        return new Response('Offline', {
                            status: 503,
                            statusText: 'Service Unavailable'
                        });
                    });
            })
    );
});

// Helper function to check if request is to API
function isAPIRequest(url) {
    return url.includes('/api/');
}

// Helper function to check if request is to CDN
function isCDNRequest(url) {
    return url.includes('cdn.tailwindcss.com') ||
           url.includes('cdnjs.cloudflare.com') ||
           url.includes('unpkg.com');
}

// Helper function to fetch and cache API responses
function fetchAndCache(request) {
    return fetch(request)
        .then(response => {
            // Only cache successful responses
            if (response.status === 200) {
                const responseClone = response.clone();
                caches.open(CACHE_NAME)
                    .then(cache => {
                        // Cache API responses for shorter time
                        cache.put(request, responseClone);
                    });
            }
            return response;
        })
        .catch(error => {
            console.log('Service Worker: Network request failed, serving from cache', error);
            // Try to serve from cache
            return caches.match(request)
                .then(cachedResponse => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // Return a generic error response
                    return new Response(
                        JSON.stringify({
                            error: 'Network unavailable',
                            message: 'Please check your internet connection'
                        }),
                        {
                            status: 503,
                            headers: { 'Content-Type': 'application/json' }
                        }
                    );
                });
        });
}

// Background sync for attendance data (when available)
self.addEventListener('sync', event => {
    console.log('Service Worker: Background sync', event.tag);
    
    if (event.tag === 'attendance-sync') {
        event.waitUntil(
            syncAttendanceData()
        );
    }
});

// Function to sync attendance data when back online
async function syncAttendanceData() {
    try {
        // Get pending attendance data from IndexedDB or cache
        const pendingData = await getPendingAttendanceData();
        
        if (pendingData.length > 0) {
            console.log('Service Worker: Syncing pending attendance data');
            
            for (const attendance of pendingData) {
                try {
                    await fetch('/api/attendance/checkin', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(attendance)
                    });
                    
                    // Remove from pending list on successful sync
                    await removePendingAttendanceData(attendance.id);
                } catch (error) {
                    console.error('Service Worker: Failed to sync attendance:', error);
                }
            }
        }
    } catch (error) {
        console.error('Service Worker: Error during background sync:', error);
    }
}

// Mock functions for pending data management
// In a real implementation, these would use IndexedDB
async function getPendingAttendanceData() {
    // Return empty array for now
    return [];
}

async function removePendingAttendanceData(id) {
    // Remove from IndexedDB
    console.log('Service Worker: Removing synced data', id);
}

// Push notification handling (for future use)
self.addEventListener('push', event => {
    if (!event.data) return;

    const data = event.data.json();
    const options = {
        body: data.body || 'New notification from AttenDANCE',
        icon: '/static/icons/icon-192x192.png',
        badge: '/static/icons/icon-96x96.png',
        data: data.data || {},
        actions: [
            {
                action: 'view',
                title: 'View',
                icon: '/static/icons/icon-96x96.png'
            },
            {
                action: 'dismiss',
                title: 'Dismiss'
            }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'AttenDANCE', options)
    );
});

// Notification click handling
self.addEventListener('notificationclick', event => {
    event.notification.close();

    if (event.action === 'view') {
        // Open the app
        event.waitUntil(
            clients.openWindow('/')
        );
    }
});

// Message handling from main thread
self.addEventListener('message', event => {
    console.log('Service Worker: Received message', event.data);
    
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
    
    if (event.data && event.data.type === 'CACHE_URLS') {
        event.waitUntil(
            caches.open(CACHE_NAME)
                .then(cache => cache.addAll(event.data.urls))
        );
    }
});

console.log('Service Worker: Script loaded'); 