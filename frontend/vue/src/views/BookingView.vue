<template>
  <div class="booking-container">
    <div class="booking-header">
      <div class="booking-header-top">
        <button @click="$router.back()" class="back-button">
          ← Back to Events
        </button>
        <BaseButton
          v-if="canCloseEvent"
          variant="danger"
          @click="openCloseModal"
        >
          Close Event
        </BaseButton>
      </div>
      <h1 class="booking-title">{{ eventName }}</h1>
      <p v-if="closeError" class="close-error">{{ closeError }}</p>
    </div>

    <transition name="modal-fade">
      <div
        v-if="showCloseModal"
        class="modal-backdrop"
        @click.self="showCloseModal = false"
      >
        <section class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="close-event-title">
          <div class="confirm-modal-icon">⚠️</div>
          <h2 id="close-event-title" class="confirm-modal-title">Close this event?</h2>
          <p class="confirm-modal-text">
            This will permanently close {{ eventName || 'this event' }} and remove it from the events list for all users.
          </p>
          <p v-if="isBeforeStartTime" class="confirm-modal-warning">
            Warning: this event has not started yet. Closing it now will hide it from all users immediately.
          </p>

          <div class="confirm-modal-actions">
            <BaseButton variant="secondary" @click="showCloseModal = false">
              Cancel
            </BaseButton>
            <BaseButton
              variant="danger"
              :loading="isClosingEvent"
              @click="handleCloseEvent"
            >
              Close Event
            </BaseButton>
          </div>
        </section>
      </div>
    </transition>

    <div class="booking-content">
      <div v-if="step === 'select'" class="step-content">
        <BaseCard title="Select Your Seats">
          <div class="seat-selection">
            <div class="seat-meta">
              <h2 class="event-title">{{ eventName || 'Untitled Event' }}</h2>
              <p class="event-details">{{ bookingStore.currentEvent?.venue || 'Unknown Venue' }}</p>
              <p class="event-details" v-if="bookingStore.currentEvent?.start_time">
                {{ formatEventDateTime(bookingStore.currentEvent.start_time) }}
              </p>
            </div>

            <div class="seat-map" :class="{ 'seat-map-disabled': authStore.isAdmin }">
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

            <div v-if="!authStore.isAdmin" class="booking-summary">
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
                <strong>₹{{ totalPrice }}</strong>
              </div>
            </div>
          </div>

          <template #footer>
            <BaseButton
              v-if="!authStore.isAdmin"
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
                <strong>₹{{ totalPrice }}</strong>
              </div>
            </div>
            <div v-if="paymentError" class="error-alert">
              {{ paymentError }}
            </div>
          </div>

          <template #footer>
            <div class="payment-actions">
              <BaseButton variant="ghost" @click="step = 'select'">Cancel</BaseButton>
              <BaseButton
                variant="primary"
                :loading="processingPayment"
                @click="handlePayment"
              >
                Pay ₹{{ totalPrice }} Now
              </BaseButton>
            </div>
          </template>
        </BaseCard>
      </div>

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
                <strong>₹{{ totalPrice }}</strong>
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
import { useAuthStore } from '../stores/auth'
import { bookingAPI } from '../services/api'
import BaseCard from '../components/BaseCard.vue'
import BaseButton from '../components/BaseButton.vue'

const route = useRoute()
const router = useRouter()
const bookingStore = useBookingStore()
const authStore = useAuthStore()

const step = ref('select') // 'select', 'payment', 'confirmed'
const selectedSeats = ref([])
const processingPayment = ref(false)
const paymentError = ref('')
const closeError = ref('')
const isClosingEvent = ref(false)
const showCloseModal = ref(false)

const reservationId = ref('')
const bookingId = ref('')
const reservedSeats = ref('')

const eventId = computed(() => route.params.id)
const eventName = ref('')
const canCloseEvent = computed(() => authStore.isAdmin && Number(bookingStore.currentEvent?.closed || 0) !== 1)
const canBookSeats = computed(() => !authStore.isAdmin)
const isBeforeStartTime = computed(() => {
  const startTime = bookingStore.currentEvent?.start_time
  if (!startTime) return false
  const start = new Date(startTime)
  if (Number.isNaN(start.getTime())) return false
  return new Date() <= start
})

const totalPrice = computed(() => {
  if (!bookingStore.currentEvent || !bookingStore.currentEvent.seat_price_map) return 0
  return selectedSeats.value.reduce((sum, seatId) => {
    const price = Number(bookingStore.currentEvent.seat_price_map[seatId] || 0)
    return sum + price
  }, 0)
})

const formatEventDateTime = (dateString) => {
  if (!dateString) return ''

  const d = new Date(dateString)
  return d.toLocaleString('en-IN', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getSeatStatus = (seatId) => {
  if (!bookingStore.currentEvent) return 'occupied'

  const occupied = bookingStore.currentEvent.seat_availability_map?.[seatId] === 1
  if (occupied) return 'occupied'
  if (selectedSeats.value.includes(seatId)) return 'selected'
  return 'available'
}

const toggleSeat = (seatId) => {
  if (!canBookSeats.value) return
  if (getSeatStatus(seatId) === 'occupied') return

  const index = selectedSeats.value.indexOf(seatId)
  if (index === -1) {
    selectedSeats.value.push(seatId)
  } else {
    selectedSeats.value.splice(index, 1)
  }
}

const handleReserve = async () => {
  if (!canBookSeats.value) {
    alert('Seat booking is not available for admin users.')
    return
  }

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
    // Step 1 — create Razorpay order via booking service
    const intent = await bookingStore.capturePayment(reservationId.value, totalPrice.value)
    if (!intent.razorpay_order_id || !intent.key_id) {
      throw new Error('Payment provider did not return order details.')
    }

    // Step 2 — load Razorpay Checkout JS (once)
    await loadRazorpayScript()

    // Step 3 — open Razorpay Checkout; confirmation is handled in the callback
    await openRazorpayCheckout(intent)
  } catch (err) {
    paymentError.value = bookingStore.error || err.message || 'Payment failed. Please try again.'
    processingPayment.value = false
  }
}

function loadRazorpayScript() {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) { resolve(); return }
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = resolve
    script.onerror = () => reject(new Error('Failed to load Razorpay Checkout script.'))
    document.head.appendChild(script)
  })
}

function openRazorpayCheckout(intent) {
  return new Promise((resolve, reject) => {
    const options = {
      key: intent.key_id,
      amount: Math.round(intent.amount * 100), // paise
      currency: 'INR',
      name: 'BookEventTicket',
      description: 'Event ticket booking',
      order_id: intent.razorpay_order_id,
      handler: async (response) => {
        try {
          await bookingStore.confirmPayment({
            intent_id: intent.intent_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id,
            razorpay_signature: response.razorpay_signature
          })
          bookingId.value = intent.intent_id
          step.value = 'confirmed'
          resolve()
        } catch (err) {
          paymentError.value = bookingStore.error || 'Payment confirmation failed.'
          reject(err)
        } finally {
          processingPayment.value = false
        }
      },
      theme: { color: '#3399cc' }
    }

    const rzp = new window.Razorpay(options)
    rzp.on('payment.failed', (response) => {
      paymentError.value = response.error?.description || 'Payment failed.'
      processingPayment.value = false
      reject(new Error(paymentError.value))
    })
    rzp.open()
  })
}

const cancelReservation = () => {
  bookingStore.clearReservation()
  step.value = 'select'
  reservationId.value = ''
  selectedSeats.value = []
  paymentError.value = ''
}

const openCloseModal = () => {
  closeError.value = ''
  showCloseModal.value = true
}

const handleCloseEvent = async () => {
  isClosingEvent.value = true
  closeError.value = ''

  try {
    await bookingAPI.closeEvent(eventId.value)
    showCloseModal.value = false
    router.replace('/events')
  } catch (error) {
    closeError.value = error.response?.data?.detail || 'Failed to close the event.'
  } finally {
    isClosingEvent.value = false
  }
}

onMounted(async () => {
  try {
    const eventData = await bookingStore.loadEvent(eventId.value)
    eventName.value = eventData?.name || ''
    if (Number(eventData?.closed || 0) === 1) {
      router.replace('/events')
    }
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

.booking-header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
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

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  z-index: 200;
}

.confirm-modal {
  width: min(100%, 28rem);
  background: #ffffff;
  border-radius: 1rem;
  padding: 1.75rem;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
  text-align: center;
}

.confirm-modal-icon {
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 9999px;
  margin: 0 auto 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fef3c7;
  font-size: 1.5rem;
}

.confirm-modal-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 0.75rem;
}

.confirm-modal-text {
  color: #4b5563;
  line-height: 1.6;
  margin: 0;
}

.confirm-modal-warning {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #f59e0b;
  line-height: 1.5;
}

.confirm-modal-actions {
  display: flex;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.close-error {
  margin-top: 0.75rem;
  color: #b91c1c;
  font-size: 0.95rem;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
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

.seat-map-disabled {
  opacity: 0.92;
}

.seat-map-disabled .seat {
  cursor: default;
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

.restricted-state {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e3a8a;
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
}

.restricted-state p + p {
  margin-top: 0.5rem;
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
