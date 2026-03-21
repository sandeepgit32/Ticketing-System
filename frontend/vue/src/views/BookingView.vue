<template>
  <div class="booking-container">
    <div class="booking-header">
      <button @click="$router.back()" class="back-button">
        ← Back to Events
      </button>
      <h1 class="booking-title">{{ eventName }}</h1>
    </div>

    <div class="booking-content">
      <!-- Seat Selection Step -->
      <div v-if="step === 'select'" class="step-content">
        <BaseCard title="Select Your Seats">
          <div class="seat-selection">
            <div class="seat-meta">
              <div><strong>Event:</strong> {{ eventName }}</div>
              <div v-if="bookingStore.currentEvent">Venue: {{ bookingStore.currentEvent.venue }}</div>
              <div v-if="bookingStore.currentEvent">Starts at: {{ bookingStore.currentEvent.start_time }}</div>
            </div>

            <div class="seat-map">
              <div class="stage">🎭 STAGE</div>
              <div class="rows">
                <div
                  v-for="row in bookingStore.currentEvent?.seat_arrangements || []"
                  :key="row.join('-')"
                  class="seat-row"
                >
                  <span class="row-label">{{ row[0].replace(/\d+$/, '') }}</span>
                  <div class="seats">
                    <div
                      v-for="seatId in row"
                      :key="seatId"
                      class="seat"
                      :class="getSeatStatus(seatId)"
                      @click="toggleSeat(seatId)"
                    >
                      {{ seatId }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="legend">
                <div class="legend-item">
                  <div class="seat available"></div>
                  <span>Available</span>
                </div>
                <div class="legend-item">
                  <div class="seat occupied"></div>
                  <span>Occupied</span>
                </div>
                <div class="legend-item">
                  <div class="seat selected"></div>
                  <span>Selected</span>
                </div>
              </div>
            </div>

            <div class="booking-summary">
              <h3>Booking Summary</h3>
              <div class="summary-row">
                <span>Selected Seats:</span>
                <strong>{{ selectedSeats.length }}</strong>
              </div>
              <div class="summary-row">
                <span>Seats:</span>
                <strong>{{ selectedSeats.join(', ') || 'None' }}</strong>
              </div>
              <div class="summary-row">
                <span>Total:</span>
                <strong>${{ totalPrice }}</strong>
              </div>
            </div>
          </div>

          <template #footer>
            <BaseButton
              variant="primary"
              block
              :loading="bookingStore.loading"
              @click="handleReserve"
            >
              Reserve Selected Seats
            </BaseButton>
          </template>
        </BaseCard>
      </div>

      <!-- Payment Step -->
      <div v-if="step === 'payment'" class="step-content">
        <BaseCard title="Complete Payment">
          <div class="payment-info">
            <div class="success-icon">✓</div>
            <h3>Seats Reserved Successfully!</h3>
            <p>Reservation ID: <strong>{{ reservationId }}</strong></p>

            <div class="reservation-details">
              <div class="detail-row">
                <span>Seats:</span>
                <strong>{{ reservedSeats }}</strong>
              </div>
              <div class="detail-row">
                <span>Total Amount:</span>
                <strong>${{ totalPrice }}</strong>
              </div>
            </div>

            <div class="payment-methods">
              <h4>Select Payment Method:</h4>
              <div class="payment-options">
                <label class="payment-option">
                  <input type="radio" v-model="paymentMethod" value="card" />
                  <span>💳 Credit/Debit Card</span>
                </label>
                <label class="payment-option">
                  <input type="radio" v-model="paymentMethod" value="paypal" />
                  <span>🅿️ PayPal</span>
                </label>
              </div>
            </div>

            <div v-if="paymentError" class="error-alert">
              {{ paymentError }}
            </div>
          </div>

          <template #footer>
            <div class="payment-actions">
              <BaseButton variant="secondary" @click="cancelReservation">
                Cancel
              </BaseButton>
              <BaseButton
                variant="success"
                :loading="processingPayment"
                @click="handlePayment"
              >
                Pay Now
              </BaseButton>
            </div>
          </template>
        </BaseCard>
      </div>

      <!-- Confirmation Step -->
      <div v-if="step === 'confirmed'" class="step-content">
        <BaseCard>
          <div class="confirmation">
            <div class="confirmation-icon">🎉</div>
            <h2>Booking Confirmed!</h2>
            <p>Your booking has been successfully confirmed.</p>

            <div class="confirmation-details">
              <div class="detail-row">
                <span>Booking ID:</span>
                <strong>{{ bookingId }}</strong>
              </div>
              <div class="detail-row">
                <span>Seats:</span>
                <strong>{{ reservedSeats }}</strong>
              </div>
              <div class="detail-row">
                <span>Amount Paid:</span>
                <strong>${{ totalPrice }}</strong>
              </div>
            </div>

            <p class="confirmation-note">
              A confirmation email has been sent to your registered email address.
            </p>
          </div>

          <template #footer>
            <div class="confirmation-actions">
              <BaseButton variant="secondary" @click="$router.push('/bookings')">
                View My Bookings
              </BaseButton>
              <BaseButton variant="primary" @click="$router.push('/events')">
                Book More Events
              </BaseButton>
            </div>
          </template>
        </BaseCard>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useBookingStore } from '../stores/booking'
import BaseCard from '../components/BaseCard.vue'
import BaseButton from '../components/BaseButton.vue'

const route = useRoute()
const router = useRouter()
const bookingStore = useBookingStore()

const step = ref('select') // 'select', 'payment', 'confirmed'
const selectedSeats = ref([])
const paymentMethod = ref('card')
const processingPayment = ref(false)
const paymentError = ref('')

const reservationId = ref('')
const bookingId = ref('')
const reservedSeats = ref('')

const eventId = computed(() => route.params.id)
const eventName = ref('')

const totalPrice = computed(() => {
  if (!bookingStore.currentEvent || !bookingStore.currentEvent.seat_price_map) return 0
  return selectedSeats.value.reduce((sum, seatId) => {
    const price = Number(bookingStore.currentEvent.seat_price_map[seatId] || 0)
    return sum + price
  }, 0)
})

const getSeatStatus = (seatId) => {
  if (!bookingStore.currentEvent) return 'occupied'

  const occupied = bookingStore.currentEvent.seat_availability_map?.[seatId] === 1
  if (occupied) return 'occupied'
  if (selectedSeats.value.includes(seatId)) return 'selected'
  return 'available'
}

const toggleSeat = (seatId) => {
  if (getSeatStatus(seatId) === 'occupied') return

  const index = selectedSeats.value.indexOf(seatId)
  if (index === -1) {
    selectedSeats.value.push(seatId)
  } else {
    selectedSeats.value.splice(index, 1)
  }
}

const handleReserve = async () => {
  if (!selectedSeats.value.length) {
    alert('Please select at least one seat to reserve.')
    return
  }

  try {
    const result = await bookingStore.reserveSeats(eventId.value, selectedSeats.value)
    reservationId.value = result.reservation_id
    reservedSeats.value = result.seats?.join(', ') || selectedSeats.value.join(', ')
    eventName.value = bookingStore.currentEvent?.name || eventName.value
    step.value = 'payment'
  } catch (error) {
    alert(bookingStore.error || 'Failed to reserve seats')
  }
}

const handlePayment = async () => {
  if (!reservationId.value) {
    paymentError.value = 'No active reservation to pay for.'
    return
  }

  processingPayment.value = true
  paymentError.value = ''

  try {
    const result = await bookingStore.capturePayment(reservationId.value, totalPrice.value, 'USD')

    bookingId.value = result.intent_id || reservationId.value
    step.value = 'confirmed'
  } catch (error) {
    paymentError.value = bookingStore.error || 'Payment failed. Please try again.'
  } finally {
    processingPayment.value = false
  }
}

const cancelReservation = () => {
  bookingStore.clearReservation()
  step.value = 'select'
  reservationId.value = ''
  selectedSeats.value = []
  paymentError.value = ''
}

onMounted(async () => {
  try {
    const eventData = await bookingStore.loadEvent(eventId.value)
    eventName.value = eventData?.name || ''
  } catch (error) {
    console.error('Failed to load event:', error)
  }
})


</script>

<style scoped>
.booking-container {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem;
}

.booking-header {
  margin-bottom: 2rem;
}

.back-button {
  background: none;
  border: none;
  color: #667eea;
  font-size: 1rem;
  cursor: pointer;
  padding: 0.5rem 0;
  margin-bottom: 1rem;
  display: inline-block;
}

.back-button:hover {
  text-decoration: underline;
}

.booking-title {
  font-size: 2rem;
  font-weight: 700;
  color: #111827;
  margin: 0;
}

.seat-selection {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.selection-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.control-group label {
  font-weight: 500;
  color: #374151;
}

.select-input {
  padding: 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 1rem;
  cursor: pointer;
}

.seat-map {
  background: #f9fafb;
  padding: 2rem;
  border-radius: 0.5rem;
}

.stage {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  text-align: center;
  padding: 1rem;
  border-radius: 0.5rem;
  font-weight: 600;
  margin-bottom: 2rem;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.seat-row {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.selected-row {
  background: rgba(102, 126, 234, 0.1);
  padding: 0.25rem;
  border-radius: 0.25rem;
}

.row-label {
  font-weight: 600;
  width: 30px;
  text-align: center;
}

.seats {
  display: flex;
  gap: 0.5rem;
  flex: 1;
}

.seat {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
}

.seat.available {
  background: #10b981;
  color: white;
}

.seat.available:hover {
  transform: scale(1.1);
}

.seat.occupied {
  background: #ef4444;
  color: white;
  cursor: not-allowed;
}

.seat.selected {
  background: #667eea;
  color: white;
  transform: scale(1.1);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
}

.legend {
  display: flex;
  justify-content: center;
  gap: 2rem;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.legend-item .seat {
  width: 30px;
  height: 30px;
}

.booking-summary {
  background: white;
  padding: 1.5rem;
  border-radius: 0.5rem;
  border: 2px solid #667eea;
}

.booking-summary h3 {
  margin: 0 0 1rem 0;
  color: #111827;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid #e5e7eb;
}

.summary-row.total {
  border-bottom: none;
  border-top: 2px solid #111827;
  margin-top: 0.5rem;
  padding-top: 1rem;
  font-size: 1.25rem;
}

.payment-info,
.confirmation {
  text-align: center;
  padding: 2rem 0;
}

.success-icon,
.confirmation-icon {
  width: 80px;
  height: 80px;
  background: #10b981;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 3rem;
  margin: 0 auto 1.5rem;
}

.confirmation-icon {
  font-size: 2.5rem;
}

.payment-info h3,
.confirmation h2 {
  color: #111827;
  margin: 0 0 0.5rem 0;
}

.payment-info p,
.confirmation p {
  color: #6b7280;
  margin: 0 0 1.5rem 0;
}

.reservation-details,
.confirmation-details {
  background: #f9fafb;
  padding: 1.5rem;
  border-radius: 0.5rem;
  margin: 1.5rem 0;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 0.75rem 0;
  border-bottom: 1px solid #e5e7eb;
}

.detail-row:last-child {
  border-bottom: none;
}

.payment-methods {
  margin: 2rem 0;
  text-align: left;
}

.payment-methods h4 {
  margin: 0 0 1rem 0;
  color: #111827;
}

.payment-options {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.payment-option {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border: 2px solid #e5e7eb;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
}

.payment-option:hover {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.05);
}

.payment-option input[type="radio"] {
  width: 20px;
  height: 20px;
  cursor: pointer;
}

.payment-option input[type="radio"]:checked ~ span {
  font-weight: 600;
  color: #667eea;
}

.error-alert {
  padding: 1rem;
  background: #fee2e2;
  border: 1px solid #fecaca;
  border-radius: 0.375rem;
  color: #dc2626;
  margin-top: 1rem;
}

.payment-actions,
.confirmation-actions {
  display: flex;
  gap: 1rem;
}

.payment-actions > *,
.confirmation-actions > * {
  flex: 1;
}

.confirmation-note {
  background: #e0e7ff;
  padding: 1rem;
  border-radius: 0.375rem;
  color: #4338ca;
  font-size: 0.875rem;
}
</style>
