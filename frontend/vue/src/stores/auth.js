import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authAPI } from '../services/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('access_token'))
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const loading = ref(false)
  const error = ref(null)

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'Admin')

  const storeUser = (userData) => {
    user.value = userData
    localStorage.setItem('user', JSON.stringify(user.value))
  }

  const login = async (credentials) => {
    loading.value = true
    error.value = null
    try {
      const response = await authAPI.login(credentials)
      const { access_token } = response.data
      token.value = access_token
      localStorage.setItem('access_token', access_token)

      const verifyResponse = await authAPI.verify()
      storeUser({
        email: verifyResponse.data?.email || credentials.email,
        full_name: verifyResponse.data?.full_name || '',
        role: verifyResponse.data?.role || 'User'
      })
      
      return true
    } catch (err) {
      error.value = err.response?.data?.detail || 'Login failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  const register = async (userData) => {
    loading.value = true
    error.value = null
    try {
      await authAPI.register(userData)
      // Auto login after registration
      return await login({ email: userData.email, password: userData.password })
    } catch (err) {
      error.value = err.response?.data?.detail || 'Registration failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  const logout = () => {
    token.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
  }

  const verifyToken = async () => {
    if (!token.value) return false
    try {
      const response = await authAPI.verify()
      storeUser({
        email: response.data?.email || user.value?.email || '',
        full_name: response.data?.full_name || user.value?.full_name || '',
        role: response.data?.role || user.value?.role || 'User'
      })
      return true
    } catch (err) {
      logout()
      return false
    }
  }

  return {
    token,
    user,
    loading,
    error,
    isAuthenticated,
    isAdmin,
    login,
    register,
    logout,
    verifyToken
  }
})
