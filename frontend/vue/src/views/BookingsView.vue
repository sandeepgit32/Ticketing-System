<template>
  <div class="bookings-container">
    <div class="bookings-header">
      <h1 class="bookings-title">My Bookings</h1>
      <p class="bookings-subtitle">View and manage your ticket bookings</p>
    </div>

    <div v-if="bookingStore.loading" class="loading-state">
      <div class="spinner-large"></div>
      <p>Loading your bookings...</p>
    </div>

    <div v-else-if="bookingStore.bookings.length === 0" class="empty-state">
      <div class="empty-icon">🎫</div>
      <h3>No Bookings Yet</h3>
      <p>You haven't made any bookings yet.</p>
      <BaseButton variant="primary" @click="$router.push('/events')">
        Browse Events
      </BaseButton>
    </div>

    <div v-else class="bookings-list">
      <BaseCard
        v-for="booking in bookingStore.bookings"
        :key="booking.booking_id"
        class="booking-card"
      >
        <div class="booking-content">
          <div class="booking-header-section">
            <div class="booking-title-group">
              <h3 class="booking-event-name">{{ booking.event_name || booking.event_id || 'Event' }}</h3>
              <p class="booking-event-time">{{ formatDate(booking.event_start_time) }}</p>
            </div>
            <span class="booking-status" :class="`status-${booking.status}`">
              {{ formatStatus(booking.status) }}
            </span>
          </div>

          <div class="booking-details">
            <div class="detail-item">
              <span class="detail-label">Booking ID:</span>
              <span class="detail-value">{{ booking.booking_id }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Seats:</span>
              <span class="detail-value">{{ formatSeats(booking.seats) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Event Date & Time:</span>
              <span class="detail-value">{{ formatDate(booking.event_start_time) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Booking Date:</span>
              <span class="detail-value">{{ formatDate(booking.created_at) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">Total Amount:</span>
              <span class="detail-value amount">${{ booking.total_amount }}</span>
            </div>
          </div>
        </div>

        <template #footer>
          <div class="booking-actions">
            <BaseButton variant="secondary" size="sm" @click="viewDetails(booking)">
              View Details
            </BaseButton>
            <BaseButton
              v-if="booking.status === 'confirmed'"
              variant="primary"
              size="sm"
              @click="downloadTicket(booking)"
            >
              Download Ticket
            </BaseButton>
          </div>
        </template>
      </BaseCard>
    </div>

    <div v-if="hasMore" class="load-more">
      <BaseButton
        variant="secondary"
        :loading="bookingStore.loading"
        @click="loadMore"
      >
        Load More
      </BaseButton>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBookingStore } from '../stores/booking'
import BaseCard from '../components/BaseCard.vue'
import BaseButton from '../components/BaseButton.vue'

const router = useRouter()
const bookingStore = useBookingStore()

const limit = ref(10)
const offset = ref(0)
const hasMore = ref(false)

const formatStatus = (status) => {
  const statusMap = {
    confirmed: 'Confirmed',
    pending: 'Pending',
    cancelled: 'Cancelled',
    expired: 'Expired'
  }
  return statusMap[status] || status
}

const formatSeats = (seats) => {
  if (!Array.isArray(seats)) {
    return seats || 'N/A'
  }

  if (seats.length === 0) return 'None'

  if (typeof seats[0] === 'string') {
    return seats.join(', ')
  }

  return seats.map(s => {
    if (typeof s === 'string') return s
    if (s?.row && s?.seat) return `${s.row}${s.seat}`
    return JSON.stringify(s)
  }).join(', ')
}

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const viewDetails = (booking) => {
  // Navigate to booking details page or show modal
  alert(`Booking Details:\n\nID: ${booking.booking_id}\nEvent: ${booking.event_name || booking.event_id}\nStatus: ${booking.status}`)
}

const downloadTicket = (booking) => {
  // In production, this would download a PDF ticket
  alert(`Downloading ticket for booking: ${booking.booking_id}`)
}

const loadMore = async () => {
  offset.value += limit.value
  await loadBookings()
}

const loadBookings = async () => {
  try {
    const result = await bookingStore.loadUserBookings(limit.value, offset.value)
    if (result && typeof result.total === 'number') {
      hasMore.value = result.total > offset.value + limit.value
    } else {
      hasMore.value = false
    }
  } catch (error) {
    console.error('Failed to load bookings:', error)
  }
}

onMounted(async () => {
  await loadBookings()
})
</script>

<style scoped>
.bookings-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 2rem;
}

.bookings-header {
  text-align: center;
  margin-bottom: 3rem;
}

.bookings-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 0.5rem 0;
}

.bookings-subtitle {
  font-size: 1.125rem;
  color: #6b7280;
  margin: 0;
}

.loading-state {
  text-align: center;
  padding: 4rem 2rem;
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
  margin: 0 0 2rem 0;
}

.bookings-list {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.booking-card {
  transition: all 0.2s;
}

.booking-card:hover {
  transform: translateX(4px);
}

.booking-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.booking-header-section {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 1rem;
}

.booking-title-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
}

.booking-event-name {
  font-size: 1.25rem;
  font-weight: 600;
  color: #111827;
  margin: 0;
}

.booking-event-time {
  font-size: 0.95rem;
  color: #6b7280;
  margin: 0;
}

.booking-status {
  padding: 0.375rem 0.875rem;
  border-radius: 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  white-space: nowrap;
}

.status-confirmed {
  background: #d1fae5;
  color: #065f46;
}

.status-pending {
  background: #fef3c7;
  color: #92400e;
}

.status-cancelled {
  background: #fee2e2;
  color: #991b1b;
}

.status-expired {
  background: #f3f4f6;
  color: #6b7280;
}

.booking-details {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.detail-label {
  font-size: 0.875rem;
  color: #6b7280;
}

.detail-value {
  font-size: 1rem;
  color: #111827;
  font-weight: 500;
}

.detail-value.amount {
  font-size: 1.25rem;
  color: #667eea;
  font-weight: 700;
}

.booking-actions {
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
}

.load-more {
  text-align: center;
  margin-top: 2rem;
}
</style>
