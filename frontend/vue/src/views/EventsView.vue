<template>
  <div class="events-container">
    <div class="events-header">
      <h1 class="events-title">Available Events</h1>
      <p class="events-subtitle">Select an event to book your seats</p>
    </div>

    <div class="events-grid">
      <BaseCard
        v-for="event in events"
        :key="event.event_id"
        hover
        class="event-card"
        @click="selectEvent(event)"
      >        <div class="event-image">
          <div class="event-badge">{{ event.available_seats || 'N/A' }} seats left</div>
        </div>
        <div class="event-content">
          <h3 class="event-name">{{ event.name }}</h3>
          <div class="event-details">
            <div class="event-detail">
              <span class="detail-icon">📅</span>
              <span>{{ formatDate(event.date) }}</span>
            </div>
            <div class="event-detail">
              <span class="detail-icon">📍</span>
              <span>{{ event.venue }}</span>
            </div>
            <div class="event-detail">
              <span class="detail-icon">💰</span>
              <span>${{ event.price || 'N/A' }}</span>
            </div>
        </div>
        <template #footer>
          <BaseButton variant="primary" block @click.stop="selectEvent(event)">
            Book Now
          </BaseButton>
        </template>
      </BaseCard>
    </div>

    <div v-if="events.length === 0" class="empty-state">
      <div class="empty-icon">🎫</div>
      <h3>No Events Available</h3>
      <p>Check back later for upcoming events</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { bookingAPI } from '../services/api'
import BaseCard from '../components/BaseCard.vue'
import BaseButton from '../components/BaseButton.vue'

const router = useRouter()

const events = ref([
  {
    event_id: 'event123',
    name: 'Summer Music Festival 2026',
    date: '2026-07-15T19:00:00',
    venue: 'Central Stadium',
    price: 75,
    available_seats: 450,
    total_seats: 500
  },
  {
    event_id: 'event456',
    name: 'Tech Conference 2026',
    date: '2026-08-20T09:00:00',
    venue: 'Convention Center',
    price: 299,
    available_seats: 120,
    total_seats: 200
  },
  {
    event_id: 'event789',
    name: 'Comedy Night Special',
    date: '2026-09-10T20:00:00',
    venue: 'Downtown Theater',
    price: 45,
    available_seats: 85,
    total_seats: 100
  }
])

const formatDate = (dateString) => {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const selectEvent = (event) => {
  router.push(`/events/${event.event_id}`)
}

onMounted(async () => {
  try {
    const response = await bookingAPI.listEvents()
    events.value = response.data?.events || []
  } catch (error) {
    console.error('Failed to load events from API, falling back to local data.', error)
    events.value = [
      {
        event_id: 'event123',
        name: 'Summer Music Festival 2026',
        date: '2026-07-15',
        venue: 'Central Stadium',
        price: 75,
        available_seats: 450,
        total_seats: 500
      },
      {
        event_id: 'event456',
        name: 'Tech Conference 2026',
        date: '2026-08-20',
        venue: 'Convention Center',
        price: 299,
        available_seats: 120,
        total_seats: 200
      },
      {
        event_id: 'event789',
        name: 'Comedy Night Special',
        date: '2026-09-10',
        venue: 'Downtown Theater',
        price: 45,
        available_seats: 85,
        total_seats: 100
      }
    ]
  }
})
</script>

<style scoped>
.events-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.events-header {
  text-align: center;
  margin-bottom: 3rem;
}

.events-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 0.5rem 0;
}

.events-subtitle {
  font-size: 1.125rem;
  color: #6b7280;
  margin: 0;
}

.events-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 2rem;
  margin-bottom: 2rem;
}

.event-card {
  cursor: pointer;
}

.event-image {
  height: 180px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.event-image::before {
  content: '🎫';
  font-size: 4rem;
  opacity: 0.3;
}

.event-badge {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: white;
  color: #667eea;
  padding: 0.5rem 1rem;
  border-radius: 2rem;
  font-size: 0.875rem;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.event-content {
  padding: 0;
}

.event-name {
  font-size: 1.25rem;
  font-weight: 600;
  color: #111827;
  margin: 0 0 1rem 0;
}

.event-details {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.event-detail {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #6b7280;
  font-size: 0.875rem;
}

.detail-icon {
  font-size: 1.125rem;
}

.empty-state {
  text-align: center;
  padding: 4rem 2rem;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state h3 {
  font-size: 1.5rem;
  color: #111827;
  margin: 0 0 0.5rem 0;
}

.empty-state p {
  color: #6b7280;
  margin: 0;
}
</style>
