<template>
  <div id="app">
    <nav v-if="authStore.isAuthenticated" class="navbar">
      <div class="nav-content">
        <div class="nav-brand">
          <router-link to="/events" class="brand-link">
            🎫 Ticketing System
          </router-link>
        </div>

        <div class="nav-menu">
          <router-link to="/events" class="nav-link">Events</router-link>
          <router-link to="/bookings" class="nav-link">My Bookings</router-link>
        </div>

        <div class="nav-user">
          <span v-if="authStore.user?.role" class="user-role">{{ authStore.user.role }}</span>
          <span class="user-email">{{ authStore.user?.email }}</span>
          <button @click="handleLogout" class="logout-button">Logout</button>
        </div>
      </div>
    </nav>

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

onMounted(async () => {
  if (authStore.isAuthenticated) {
    await authStore.verifyToken()
  }
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: #f3f4f6;
  color: #111827;
}

#app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.navbar {
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 100;
}

.nav-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2rem;
}

.nav-brand {
  font-size: 1.25rem;
  font-weight: 700;
}

.brand-link {
  text-decoration: none;
  color: #111827;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  transition: color 0.2s;
}

.brand-link:hover {
  color: #667eea;
}

.nav-menu {
  display: flex;
  gap: 2rem;
  flex: 1;
}

.nav-link {
  text-decoration: none;
  color: #6b7280;
  font-weight: 500;
  padding: 0.5rem 0;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.nav-link:hover {
  color: #111827;
}

.nav-link.router-link-active {
  color: #667eea;
  border-bottom-color: #667eea;
}

.nav-user {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.user-email {
  color: #6b7280;
  font-size: 0.875rem;
}

.user-role {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  background: #e0e7ff;
  color: #3730a3;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.logout-button {
  background: none;
  border: 1px solid #d1d5db;
  color: #6b7280;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
}

.logout-button:hover {
  background: #f3f4f6;
  color: #111827;
  border-color: #9ca3af;
}

.main-content {
  flex: 1;
  width: 100%;
}

/* Responsive */
@media (max-width: 768px) {
  .nav-content {
    flex-direction: column;
    gap: 1rem;
    padding: 1rem;
  }

  .nav-menu {
    width: 100%;
    justify-content: center;
  }

  .nav-user {
    width: 100%;
    justify-content: center;
  }

  .user-email {
    display: none;
  }
}
</style>
