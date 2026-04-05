// ALAUTO Smart Fan — Service Worker
// Offline support এর জন্য

const CACHE_NAME = 'alauto-v1';
const ASSETS = [
  '/smart_fan_app.html',
  '/manifest.json'
];

// Install — files cache করো
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('ALAUTO: Cache করা হচ্ছে...');
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate — পুরনো cache মুছো
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — cache থেকে দাও, না পেলে network থেকে নাও
self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(cached => {
      return cached || fetch(e.request).catch(() => caches.match('/smart_fan_app.html'));
    })
  );
});
