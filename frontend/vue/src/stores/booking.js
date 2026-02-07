import { defineStore } from 'pinia'
import { ref } from 'vue'
import { bookingAPI, statusAPI } from '../services/api'

export const useBookingStore = defineStore('booking', () => {
  const currentEvent = ref(null)
  const reservation = ref(null)
  const bookings = ref([])
  const loading = ref(false)
  const error = ref(null)

  const loadEvent = async (eventId) => {
    loading.value = true
    error.value = null
    try {
      const response = await bookingAPI.getEvent(eventId)
      currentEvent.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || 'Failed to load event'
      throw err
    } finally {
      loading.value = false
    }
  }

  const reserveSeats = async (eventId, numSeats, preferredRows = []) => {
    loading.value = true
    error.value = null
    try {
      const response = await bookingAPI.reserve({
        event_id: eventId,
        num_seats: numSeats,
        preferred_rows: preferredRows
      })
      reservation.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || 'Failed to reserve seats'
      throw err
    } finally {
      loading.value = false
    }
  }

  const capturePayment = async (reservationId, paymentMethod = 'card') => {
    loading.value = true
    error.value = null
    try {
      const response = await bookingAPI.capturePayment({
        reservation_id: reservationId,
        payment_method: paymentMethod
      })
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || 'Payment failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  const loadUserBookings = async (limit = 50, offset = 0) => {
    loading.value = true
    error.value = null
    try {
      const response = await statusAPI.getUserBookings({ limit, offset })
      bookings.value = response.data.bookings || []
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || 'Failed to load bookings'
      throw err
    } finally {
      loading.value = false
    }
  }

  const getReservationStatus = async (reservationId) => {
    try {
      const response = await statusAPI.getReservation(reservationId)
      return response.data
    } catch (err) {
      throw err
    }
  }

  const clearReservation = () => {
    reservation.value = null
  }

  return {
    currentEvent,
    reservation,
    bookings,
    loading,
    error,
    loadEvent,
    reserveSeats,
    capturePayment,
    loadUserBookings,
    getReservationStatus,
    clearReservation
  }
})
