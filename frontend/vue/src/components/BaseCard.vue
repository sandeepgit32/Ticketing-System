<template>
  <div class="card" :class="{ 'card-hover': hover }">
    <div v-if="title" class="card-header">
      <h3 class="card-title">{{ title }}</h3>
    </div>
    <div class="card-body">
      <slot></slot>
    </div>
    <div v-if="$slots.footer" class="card-footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: String,
  hover: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped>
.card {
  background: white;
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  transition: all 0.2s;
}

.card-hover:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.card-header {
  padding: 1.25rem;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.card-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #111827;
}

.card-body {
  padding: 1.25rem;
}

.card-footer {
  padding: 1rem 1.25rem;
  border-top: 1px solid #e5e7eb;
  background: #f9fafb;
}
</style>
