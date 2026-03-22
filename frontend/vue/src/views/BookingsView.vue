<template>
  <div class="bookings-container">
    <div class="bookings-header">
      <h1 class="bookings-title">My Bookings</h1>
      <p class="bookings-subtitle">View and manage your ticket bookings</p>
    </div>

    <div v-if="bookingStore.loading" class="loading-state">
      <img class="loading-logo" src="/logo.png" alt="BookEventTicket logo" />
      <div class="spinner-large"></div>
      <p>Loading your bookings...</p>
    </div>

    <div v-else-if="bookingStore.bookings.length === 0" class="empty-state">
      <img class="empty-logo" src="/logo.png" alt="BookEventTicket logo" />
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
              :loading="isDownloadingTicket && downloadingBookingId === booking.booking_id"
            >
              Download Ticket
            </BaseButton>
          </div>
        </template>
      </BaseCard>
    </div>

    <transition name="ticket-fade">
      <div
        v-if="ticketModalOpen && selectedBooking"
        class="ticket-modal-backdrop"
        @click.self="closeTicketModal"
      >
        <section class="ticket-modal" role="dialog" aria-modal="true" aria-label="Booking ticket details">
          <button class="ticket-close" type="button" aria-label="Close ticket details" @click="closeTicketModal">
            ×
          </button>

          <div class="ticket-header">
            <img class="ticket-logo" src="/logo.png" alt="BookEventTicket logo" />
            <div>
              <p class="ticket-eyebrow">Digital Ticket</p>
              <h2 class="ticket-title">{{ selectedBooking.event_name || selectedBooking.event_id || 'Event Ticket' }}</h2>
              <p class="ticket-subtitle">{{ formatDate(selectedBooking.event_start_time) }}</p>
            </div>
            <span class="ticket-status" :class="`status-${selectedBooking.status}`">
              {{ formatStatus(selectedBooking.status) }}
            </span>
          </div>

          <div class="ticket-visual">
            <div class="ticket-main">
              <div class="ticket-badge-row">
                <span class="ticket-badge">Admit One</span>
                <span class="ticket-code">{{ selectedBooking.booking_id }}</span>
              </div>

              <div class="ticket-event-block">
                <h3>{{ selectedBooking.event_name || selectedBooking.event_id || 'Event' }}</h3>
                <p>{{ formatDate(selectedBooking.event_start_time) }}</p>
              </div>

              <div class="ticket-details-grid">
                <div class="ticket-detail">
                  <span>Seats</span>
                  <strong>{{ formatSeats(selectedBooking.seats) }}</strong>
                </div>
                <div class="ticket-detail">
                  <span>Total</span>
                  <strong>{{ formatCurrency(selectedBooking.total_amount) }}</strong>
                </div>
                <div class="ticket-detail">
                  <span>Booked On</span>
                  <strong>{{ formatDate(selectedBooking.created_at) }}</strong>
                </div>
                <div class="ticket-detail">
                  <span>Payment</span>
                  <strong>{{ formatTicketStatus(selectedBooking.payment_status || selectedBooking.status) }}</strong>
                </div>
              </div>
            </div>

            <div class="ticket-stub">
              <div class="ticket-qr">
                <span></span>
                <span></span>
                <span></span>
                <span></span>
              </div>
              <div class="ticket-stub-text">
                <p>Ticket ID</p>
                <strong>{{ selectedBooking.booking_id }}</strong>
                <p class="ticket-stub-note">Present this ticket at entry.</p>
              </div>
            </div>
          </div>

          <div class="ticket-footer">
            <div class="ticket-meta">
              <span>User</span>
              <strong>{{ selectedBooking.user_email }}</strong>
            </div>
            <div class="ticket-actions ticket-modal-actions">
              <BaseButton variant="secondary" @click="closeTicketModal">
                Close
              </BaseButton>
              <BaseButton
                v-if="selectedBooking.status === 'confirmed'"
                variant="primary"
                :loading="isDownloadingTicket && downloadingBookingId === selectedBooking.booking_id"
                @click="downloadTicket(selectedBooking)"
              >
                Download Ticket
              </BaseButton>
            </div>
          </div>
        </section>
      </div>
    </transition>

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
const ticketModalOpen = ref(false)
const selectedBooking = ref(null)
const isDownloadingTicket = ref(false)
const downloadingBookingId = ref(null)

const formatStatus = (status) => {
  const statusMap = {
    confirmed: 'Confirmed',
    pending: 'Pending',
    cancelled: 'Cancelled',
    expired: 'Expired',
    paid: 'Paid',
    failed: 'Failed',
    refunded: 'Refunded'
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

const formatCurrency = (amount) => {
  if (amount === null || amount === undefined || amount === '') return 'N/A'

  const value = Number(amount)
  if (Number.isNaN(value)) return String(amount)

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2
  }).format(value)
}

const formatTicketStatus = (status) => {
  const map = {
    confirmed: 'Confirmed',
    pending: 'Pending',
    cancelled: 'Cancelled',
    expired: 'Expired',
    paid: 'Paid',
    failed: 'Failed',
    refunded: 'Refunded'
  }

  return map[status] || formatStatus(status)
}

const slugify = (value) => {
  return String(value || 'ticket')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

const openTicketModal = (booking) => {
  selectedBooking.value = booking
  ticketModalOpen.value = true
}

const closeTicketModal = () => {
  ticketModalOpen.value = false
}

const viewDetails = (booking) => {
  openTicketModal(booking)
}

const getPdfFilename = (booking) => {
  const eventSlug = slugify(booking.event_name || booking.event_id || 'ticket')
  const bookingSlug = String(booking.booking_id || 'booking').slice(0, 8)
  return `${eventSlug}-${bookingSlug}.pdf`
}

const saveBlobToFile = async (blob, filename) => {
  if (window.showSaveFilePicker) {
    const fileHandle = await window.showSaveFilePicker({
      suggestedName: filename,
      types: [
        {
          description: 'PDF Document',
          accept: {
            'application/pdf': ['.pdf']
          }
        }
      ]
    })

    const writable = await fileHandle.createWritable()
    await writable.write(blob)
    await writable.close()
    return
  }

  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(url)
}

const loadImageDataUrl = async (imageUrl) => {
  const response = await fetch(imageUrl)
  const blob = await response.blob()

  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}

const generateTicketPdf = async (booking) => {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({
    orientation: 'landscape',
    unit: 'mm',
    format: [210, 100]
  })

  const statusPalette = {
    confirmed: { fill: [209, 250, 229], text: [6, 95, 70] },
    pending: { fill: [254, 243, 199], text: [146, 64, 14] },
    cancelled: { fill: [254, 226, 226], text: [153, 27, 27] },
    expired: { fill: [243, 244, 246], text: [75, 85, 99] }
  }
  const palette = statusPalette[booking.status] || statusPalette.pending
  const logoDataUrl = await loadImageDataUrl('/logo.png')

  doc.setFillColor(246, 248, 255)
  doc.roundedRect(6, 6, 198, 88, 6, 6, 'F')

  doc.setFillColor(102, 126, 234)
  doc.roundedRect(6, 6, 50, 88, 6, 6, 'F')

  doc.setFillColor(255, 255, 255)
  doc.roundedRect(10, 10, 190, 80, 4, 4, 'F')

  doc.setFillColor(118, 75, 162)
  doc.roundedRect(10, 10, 50, 80, 4, 4, 'F')

  doc.addImage(logoDataUrl, 'PNG', 18, 14, 24, 24)

  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.text('BOOKEVENTTICKET', 35, 42, { align: 'center', maxWidth: 38 })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text('Admit One', 18, 52)
  doc.text('Present this ticket at the venue entrance.', 18, 60, { maxWidth: 34 })

  doc.setFillColor(255, 255, 255)
  doc.roundedRect(18, 70, 34, 18, 4, 4, 'S')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.text('BOOKING ID', 21, 78)
  doc.setFontSize(8)
  doc.text(String(booking.booking_id || 'N/A').slice(0, 16), 21, 84, { maxWidth: 28 })

  doc.setTextColor(33, 37, 41)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  const titleLines = doc.splitTextToSize(booking.event_name || booking.event_id || 'Event', 96)
  doc.text(titleLines, 68, 22)

  doc.setFont('helvetica', 'normal')
  doc.setTextColor(75, 85, 99)
  doc.setFontSize(10)
  doc.text(formatDate(booking.event_start_time), 68, 36)

  doc.setFillColor(palette.fill[0], palette.fill[1], palette.fill[2])
  doc.roundedRect(160, 12, 28, 10, 4, 4, 'F')
  doc.setTextColor(palette.text[0], palette.text[1], palette.text[2])
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text(formatTicketStatus(booking.status), 175, 18, { align: 'center' })

  doc.setDrawColor(226, 232, 240)
  doc.line(66, 42, 194, 42)

  const detailX = 68
  const detailY = 50
  const detailWidth = 34
  const detailHeight = 18
  const details = [
    { label: 'SEATS', value: formatSeats(booking.seats) },
    { label: 'TOTAL', value: formatCurrency(booking.total_amount) },
    { label: 'BOOKED', value: formatDate(booking.created_at) },
    { label: 'PAYMENT', value: formatTicketStatus(booking.payment_status || booking.status) }
  ]

  details.forEach((item, index) => {
    const x = detailX + (index % 2) * (detailWidth + 4)
    const y = detailY + Math.floor(index / 2) * (detailHeight + 5)
    doc.setFillColor(249, 250, 251)
    doc.roundedRect(x, y, detailWidth, detailHeight, 3, 3, 'F')
    doc.setTextColor(107, 114, 128)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.text(item.label, x + 3, y + 6)
    doc.setTextColor(17, 24, 39)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.text(doc.splitTextToSize(item.value, detailWidth - 6), x + 3, y + 11)
  })

  doc.setTextColor(107, 114, 128)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text(`Passenger: ${booking.user_email || 'N/A'}`, 68, 87)
  doc.text(`Ticket generated on ${new Date().toLocaleString()}`, 134, 87, { align: 'left' })

  return doc.output('blob')
}

const downloadTicket = async (booking) => {
  try {
    isDownloadingTicket.value = true
    downloadingBookingId.value = booking.booking_id
    const pdfBlob = await generateTicketPdf(booking)
    await saveBlobToFile(pdfBlob, getPdfFilename(booking))
  } catch (error) {
    console.error('Failed to download ticket:', error)
    window.alert('Unable to download the ticket right now. Please try again.')
  } finally {
    isDownloadingTicket.value = false
    downloadingBookingId.value = null
  }
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

.empty-state {
  text-align: center;
  padding: 4rem 2rem;
}

.empty-logo {
  width: 5.75rem;
  height: 5.75rem;
  object-fit: contain;
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

.ticket-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(10px);
  display: grid;
  place-items: center;
  padding: 1.25rem;
  z-index: 50;
}

.ticket-modal {
  position: relative;
  width: min(100%, 860px);
  background: linear-gradient(135deg, #ffffff 0%, #f8faff 100%);
  border-radius: 1.5rem;
  box-shadow: 0 30px 80px rgba(15, 23, 42, 0.35);
  overflow: hidden;
  padding: 1.5rem;
}

.ticket-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 2.25rem;
  height: 2.25rem;
  border: none;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.08);
  color: #111827;
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
}

.ticket-close:hover {
  background: rgba(15, 23, 42, 0.14);
}

.ticket-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
  padding-right: 2.5rem;
}

.ticket-logo {
  width: 15rem;
  height: 6rem;
  object-fit: contain;
  flex: 0 0 auto;
}

.ticket-eyebrow {
  margin: 0 0 0.35rem;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 0.75rem;
  font-weight: 700;
  color: #667eea;
}

.ticket-title {
  margin: 0;
  font-size: clamp(1.5rem, 2.6vw, 2.4rem);
  color: #0f172a;
}

.ticket-subtitle {
  margin: 0.45rem 0 0;
  color: #64748b;
}

.ticket-status {
  padding: 0.55rem 1rem;
  border-radius: 999px;
  font-weight: 700;
  white-space: nowrap;
}

.ticket-visual {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  min-height: 320px;
  border-radius: 1.25rem;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.ticket-main {
  position: relative;
  padding: 1.5rem;
  background:
    radial-gradient(circle at top right, rgba(118, 75, 162, 0.08), transparent 34%),
    linear-gradient(180deg, #ffffff 0%, #f8faff 100%);
}

.ticket-main::after {
  content: '';
  position: absolute;
  right: -1px;
  top: 0;
  width: 18px;
  height: 100%;
  background:
    linear-gradient(90deg, transparent 0, transparent 6px, rgba(148, 163, 184, 0.18) 6px, rgba(148, 163, 184, 0.18) 12px, transparent 12px);
  opacity: 0.8;
}

.ticket-badge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.ticket-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.45rem 0.8rem;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ticket-code {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 600;
  word-break: break-all;
}

.ticket-event-block {
  padding: 1rem 1rem 1.1rem;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 1rem;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
}

.ticket-event-block h3 {
  margin: 0;
  font-size: 1.5rem;
  color: #0f172a;
}

.ticket-event-block p {
  margin: 0.55rem 0 0;
  color: #475569;
}

.ticket-details-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
  margin-top: 1rem;
}

.ticket-detail {
  padding: 0.85rem 0.95rem;
  border-radius: 0.9rem;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.ticket-detail span {
  display: block;
  color: #64748b;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.35rem;
}

.ticket-detail strong {
  color: #0f172a;
  font-size: 0.98rem;
  line-height: 1.35;
}

.ticket-stub {
  padding: 1.5rem 1.25rem;
  background: linear-gradient(180deg, #764ba2 0%, #667eea 100%);
  color: white;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 1rem;
}

.ticket-qr {
  width: 120px;
  height: 120px;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.16);
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.ticket-qr span {
  border-radius: 0.6rem;
  background: rgba(255, 255, 255, 0.9);
}

.ticket-stub-text p {
  margin: 0;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8rem;
}

.ticket-stub-text strong {
  display: block;
  margin: 0.35rem 0 0.45rem;
  font-size: 1rem;
  word-break: break-all;
}

.ticket-stub-note {
  line-height: 1.5;
}

.ticket-footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1.25rem;
}

.ticket-meta span {
  display: block;
  color: #64748b;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.3rem;
}

.ticket-meta strong {
  color: #0f172a;
  font-size: 0.95rem;
}

.ticket-modal-actions {
  margin-left: auto;
}

.ticket-actions {
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
}

.ticket-fade-enter-active,
.ticket-fade-leave-active {
  transition: opacity 0.2s ease;
}

.ticket-fade-enter-from,
.ticket-fade-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .ticket-modal {
    padding: 1.15rem;
  }

  .ticket-header,
  .ticket-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .ticket-visual {
    grid-template-columns: 1fr;
  }

  .ticket-main::after {
    display: none;
  }

  .ticket-stub {
    flex-direction: row;
    align-items: center;
  }

  .ticket-actions,
  .ticket-modal-actions {
    width: 100%;
    margin-left: 0;
  }

  .ticket-actions :deep(.btn) {
    flex: 1;
  }
}
</style>
