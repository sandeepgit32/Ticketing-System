import axios from 'axios'

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid
      localStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth API
export const authAPI = {
  register: (userData) => apiClient.post('/auth/register', userData),
  login: (credentials) => apiClient.post('/auth/login', credentials),
  verify: () => apiClient.post('/auth/verify')
}

// Booking API
export const bookingAPI = {
  listEvents: () => apiClient.get('/booking/events'),
  getEvent: (eventId) => apiClient.get(`/booking/events/${eventId}`),
  createEvent: (eventData) => apiClient.post('/booking/events', eventData),
  closeEvent: (eventId) => apiClient.get(`/booking/events/${eventId}/close`),
  listVenues: () => apiClient.get('/booking/venues'),
  reserve: (data) => apiClient.post('/booking/bookings/reserve', data),
  capturePayment: (data) => apiClient.post('/booking/payments/capture', data)
}

// Booking Status API
export const statusAPI = {
  getBooking: (bookingId) => apiClient.get(`/status/bookings/${bookingId}`),
  getUserBookings: (params) => apiClient.get('/status/user/bookings', { params })
}

export default apiClient
