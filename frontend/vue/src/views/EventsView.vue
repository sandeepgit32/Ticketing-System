<template>
  <div class="events-container">
    <div class="events-header">
      <h1 class="events-title">Available Events</h1>
      <p class="events-subtitle">Select an event to book your seats</p>

      <div v-if="canManageEvents" class="add-event-actions">
        <BaseButton variant="success" @click="toggleAddEventForm">
          {{ showAddEventForm ? 'Close Form' : 'Add New Event' }}
        </BaseButton>
      </div>
    </div>

    <div v-if="canManageEvents && showAddEventForm" class="add-event-form">
      <BaseCard title="Create New Event">
        <div class="form-row">
          <label for="event-name">Name</label>
          <input id="event-name" v-model="newEvent.name" type="text" placeholder="Event name" />
        </div>

        <div class="form-row">
          <label for="event-venue">Venue</label>
          <select id="event-venue" v-model="newEvent.venue">
            <option value="" disabled>Select venue</option>
            <option v-for="venue in venues" :key="venue.name" :value="venue.name">{{ venue.name }}</option>
          </select>
          <small v-if="!venues.length" class="hint">No venues loaded; type a valid venue name</small>
        </div>

        <div class="form-row">
          <label for="event-start">Start time</label>
          <input id="event-start" v-model="newEvent.start_time" type="datetime-local" />
        </div>

        <div class="form-status">
          <p v-if="createError" class="error-state">{{ createError }}</p>
          <p v-if="createSuccess" class="success-state">{{ createSuccess }}</p>
        </div>

        <template #footer>
          <div class="form-actions">
            <BaseButton variant="secondary" @click="toggleAddEventForm">Cancel</BaseButton>
            <BaseButton :loading="creatingEvent" variant="primary" @click="createEvent">Create Event</BaseButton>
          </div>
        </template>
      </BaseCard>
    </div>

    <div v-if="isLoading" class="loading-state">
      <img class="loading-logo" src="/logo.png" alt="BookEventTicket logo" />
      <div class="spinner-large"></div>
      <p>Loading events...</p>
    </div>
    <div v-if="errorMessage" class="error-state">{{ errorMessage }}</div>

    <div class="events-grid" v-else>
      <BaseCard
        v-for="event in events"
        :key="event.event_id"
        hover
        class="event-card"
        @click="selectEvent(event)"
      >        <div class="event-image">
          <div class="event-badge">{{ event.num_seats_available }} seats left</div>
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
              <span v-if="event.list_of_prices && event.list_of_prices.length">
                From ₹{{ event.list_of_prices[0] }}
              </span>
              <span v-else>N/A</span>
            </div>
          </div>
        </div>
        <template #footer>
          <BaseButton variant="primary" block @click.stop="selectEvent(event)">
            Book Now
          </BaseButton>
        </template>
      </BaseCard>
    </div>

    <div v-if="!isLoading && events.length === 0" class="empty-state">
      <div class="empty-icon">🎫</div>
      <h3>No Events Available</h3>
      <p>Check back later for upcoming events</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { bookingAPI } from '../services/api'
import { useAuthStore } from '../stores/auth'
import BaseCard from '../components/BaseCard.vue'
import BaseButton from '../components/BaseButton.vue'

const router = useRouter()
const authStore = useAuthStore()

const events = ref([])
const venues = ref([])
const errorMessage = ref('')
const isLoading = ref(false)

const showAddEventForm = ref(false)
const creatingEvent = ref(false)
const createError = ref('')
const createSuccess = ref('')
const newEvent = ref({ name: '', venue: '', start_time: '' })
const canManageEvents = computed(() => authStore.isAdmin)

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

const loadEvents = async () => {
  isLoading.value = true
  try {
    const response = await bookingAPI.listEvents()
    events.value = response.data?.events || []
    errorMessage.value = ''
  } catch (error) {
    console.error('Failed to load events from API.', error)
    errorMessage.value = 'Unable to load events. Please try again later.'
    events.value = []
  } finally {
    isLoading.value = false
  }
}

const loadVenues = async () => {
  try {
    const response = await bookingAPI.listVenues()
    venues.value = response.data?.venues || []
  } catch (error) {
    console.warn('Failed to load venues list.', error)
    venues.value = []
  }
}

const resetNewEvent = () => {
  newEvent.value = { name: '', venue: '', start_time: '' }
  createError.value = ''
  createSuccess.value = ''
}

const toggleAddEventForm = () => {
  if (!canManageEvents.value) return
  showAddEventForm.value = !showAddEventForm.value
  if (!showAddEventForm.value) {
    resetNewEvent()
  }
}

const createEvent = async () => {
  createError.value = ''
  createSuccess.value = ''

  if (!newEvent.value.name || !newEvent.value.venue || !newEvent.value.start_time) {
    createError.value = 'Please fill in all fields.'
    return
  }

  creatingEvent.value = true

  try {
    const payload = {
      name: newEvent.value.name,
      venue: newEvent.value.venue,
      start_time: newEvent.value.start_time
    }

    await bookingAPI.createEvent(payload)
    createSuccess.value = 'Event created successfully.'
    resetNewEvent()
    showAddEventForm.value = false
    await loadEvents()
  } catch (error) {
    console.error('Failed to create event.', error)
    createError.value = error.response?.data?.detail || 'Unable to create event. Please try again.'
  } finally {
    creatingEvent.value = false
  }
}

const selectEvent = (event) => {
  router.push(`/events/${event.event_id}`)
}

onMounted(async () => {
  if (authStore.isAuthenticated && !authStore.user?.role) {
    await authStore.verifyToken()
  }
  await Promise.all([loadEvents(), loadVenues()])
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

.loading-state {
  text-align: center;
  padding: 4rem 2rem;
}

.loading-logo {
  width: 5.75rem;
  height: 5.75rem;
  object-fit: contain;
  margin: 0 auto 1rem;
  display: block;
}

.spinner-large {
  width: 50px;
  height: 50px;
  border: 5px solid rgba(102, 126, 234, 0.3);
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-state p {
  color: #6b7280;
  font-size: 1.125rem;
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

.add-event-actions {
  margin-top: 1rem;
  text-align: center;
}

.add-event-form {
  margin-bottom: 2rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.form-row input,
.form-row select {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 1rem;
}

.form-status {
  margin-bottom: 1rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.success-state {
  color: #166534;
}

.error-state {
  color: #b91c1c;
}</style>
