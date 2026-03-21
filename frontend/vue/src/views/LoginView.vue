<template>
  <div class="auth-container">
    <BaseCard class="auth-card">
      <div class="auth-brand">
        <img class="auth-logo" src="/logo.png" alt="BookEventTicket logo" />
        <p class="auth-brand-name">BookEventTicket</p>
      </div>

      <div class="auth-header">
        <h1 class="auth-title">{{ isLogin ? 'Welcome Back' : 'Create Account' }}</h1>
        <p class="auth-subtitle">
          {{ isLogin ? 'Sign in to continue to your account' : 'Sign up to get started' }}
        </p>
      </div>

      <form @submit.prevent="handleSubmit" class="auth-form">
        <BaseInput
          v-if="!isLogin"
          v-model="formData.full_name"
          label="Full Name"
          placeholder="John Doe"
          required
          :error="errors.full_name"
        />

        <BaseInput
          v-model="formData.email"
          type="email"
          label="Email Address"
          placeholder="you@example.com"
          required
          :error="errors.email"
        />

        <BaseInput
          v-model="formData.password"
          type="password"
          label="Password"
          placeholder="••••••••"
          required
          :error="errors.password"
        />

        <div v-if="authStore.error" class="error-alert">
          {{ authStore.error }}
        </div>

        <BaseButton
          type="submit"
          variant="primary"
          block
          :loading="authStore.loading"
        >
          {{ isLogin ? 'Sign In' : 'Sign Up' }}
        </BaseButton>
      </form>

      <div class="auth-switch">
        {{ isLogin ? "Don't have an account?" : 'Already have an account?' }}
        <button @click="toggleMode" class="link-button">
          {{ isLogin ? 'Sign Up' : 'Sign In' }}
        </button>
      </div>
    </BaseCard>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import BaseCard from '../components/BaseCard.vue'
import BaseInput from '../components/BaseInput.vue'
import BaseButton from '../components/BaseButton.vue'

const router = useRouter()
const authStore = useAuthStore()

const isLogin = ref(true)
const formData = reactive({
  email: '',
  password: '',
  full_name: ''
})
const errors = reactive({
  email: '',
  password: '',
  full_name: ''
})

const toggleMode = () => {
  isLogin.value = !isLogin.value
  Object.keys(errors).forEach(key => errors[key] = '')
  authStore.error = null
}

const validateForm = () => {
  let isValid = true
  Object.keys(errors).forEach(key => errors[key] = '')

  if (!formData.email) {
    errors.email = 'Email is required'
    isValid = false
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
    errors.email = 'Invalid email format'
    isValid = false
  }

  if (!formData.password) {
    errors.password = 'Password is required'
    isValid = false
  } else if (formData.password.length < 6) {
    errors.password = 'Password must be at least 6 characters'
    isValid = false
  }

  if (!isLogin.value && !formData.full_name) {
    errors.full_name = 'Full name is required'
    isValid = false
  }

  return isValid
}

const handleSubmit = async () => {
  if (!validateForm()) return

  try {
    if (isLogin.value) {
      await authStore.login({
        email: formData.email,
        password: formData.password
      })
    } else {
      await authStore.register({
        email: formData.email,
        password: formData.password,
        full_name: formData.full_name
      })
    }
    router.push('/events')
  } catch (error) {
    console.error('Auth error:', error)
  }
}
</script>

<style scoped>
.auth-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 2rem;
}

.auth-card {
  width: 100%;
  max-width: 420px;
}

.auth-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.auth-logo {
  width: 6.25rem;
  height: 6.25rem;
  object-fit: contain;
}

.auth-brand-name {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #111827;
}

.auth-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-title {
  font-size: 2rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 0.5rem 0;
}

.auth-subtitle {
  color: #6b7280;
  margin: 0;
}

.auth-form {
  margin-bottom: 1.5rem;
}

.error-alert {
  padding: 0.75rem;
  background-color: #fee2e2;
  border: 1px solid #fecaca;
  border-radius: 0.375rem;
  color: #dc2626;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.auth-switch {
  text-align: center;
  color: #6b7280;
  font-size: 0.875rem;
}

.link-button {
  background: none;
  border: none;
  color: #667eea;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  margin-left: 0.25rem;
}

.link-button:hover {
  text-decoration: underline;
}
</style>
