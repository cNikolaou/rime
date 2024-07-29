import { ref } from 'vue';
import { defineStore } from 'pinia';

export const useStateStore = defineStore('state', () => {
  const displayTimeline = ref(false);

  function toggleTimeline() {
    displayTimeline.value = !displayTimeline.value;
  }

  return { displayTimeline, toggleTimeline };
});
