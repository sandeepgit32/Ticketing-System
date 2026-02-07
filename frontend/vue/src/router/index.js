import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/',
    redirect: '/events'
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/events',
    name: 'events',
    component: () => import('../views/EventsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/events/:id',
    name: 'booking',
    component: () => import('../views/BookingView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/bookings',
    name: 'bookings',
    component: () => import('../views/BookingsView.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guard
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  const requiresAuth = to.meta.requiresAuth

  if (requiresAuth && !authStore.isAuthenticated) {
    // Redirect to login if not authenticated
    next('/login')
  } else if (!requiresAuth && authStore.isAuthenticated && to.path === '/login') {
    // Redirect to events if already logged in and trying to access login
    next('/events')
  } else {
    next()
  }
})

export default router
