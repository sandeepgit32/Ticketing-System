<template>
  <div class="seat-map-legacy">
    <p class="deprecation-notice">
      This component has been replaced by the new BookingView. 
      Please navigate to /events to use the new booking system.
    </p>
  </div>
</template>

<script setup>
// Legacy component - kept for backwards compatibility
defineProps({ eventId: String })
</script>

<style scoped>
.seat-map-legacy {
  padding: 2rem;
  text-align: center;
}

.deprecation-notice {
  color: #6b7280;
  font-style: italic;
}
</style>
