<script setup lang="ts">
import { ref, onMounted } from 'vue'
import FileUploader from './components/FileUploader.vue'
import AdminDashboard from './components/AdminDashboard.vue'

const token = ref<string | null>(null)
const isAdmin = ref(false)

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  token.value = params.get('token')
  isAdmin.value = params.get('admin') === 'true' || !token.value
})

function navigateToAdmin() {
  window.history.pushState({}, '', '?admin=true')
  isAdmin.value = true
  token.value = null
}

function navigateToHome() {
  window.history.pushState({}, '', '/')
  isAdmin.value = false
  token.value = null
}
</script>

<template>
  <div class="min-h-screen bg-slate-950 flex flex-col text-slate-100">
    <!-- Header -->
    <header class="border-b border-white/5 py-4 px-6 glass-card sticky top-0 z-50">
      <div class="max-w-6xl mx-auto flex items-center justify-between">
        <div class="flex items-center gap-3 cursor-pointer" @click="navigateToHome">
          <span class="text-3xl">☁️</span>
          <div>
            <h1 class="text-xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400">
              GDrive Relay
            </h1>
            <p class="text-[10px] text-slate-400 font-medium tracking-wide uppercase">Secure Upload Portal</p>
          </div>
        </div>

        <nav class="flex items-center gap-4">
          <button 
            v-if="!isAdmin" 
            @click="navigateToAdmin" 
            class="text-xs font-semibold text-slate-400 hover:text-white transition-colors duration-200 px-3 py-1.5 rounded-lg hover:bg-white/5 border border-transparent hover:border-white/5 cursor-pointer"
          >
            Admin Panel
          </button>
          <button 
            v-else-if="token"
            @click="navigateToHome"
            class="text-xs font-semibold text-slate-400 hover:text-white transition-colors duration-200 px-3 py-1.5 rounded-lg hover:bg-white/5 border border-transparent hover:border-white/5 cursor-pointer"
          >
            Back to Upload
          </button>
        </nav>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-grow flex items-center justify-center p-4 md:p-8">
      <div class="w-full max-w-4xl">
        <Transition name="fade-slide" mode="out-in">
          <FileUploader v-if="token" :token="token" />
          <AdminDashboard v-else />
        </Transition>
      </div>
    </main>

    <!-- Footer -->
    <footer class="py-6 border-t border-white/5 text-center text-xs text-slate-500 glass-card">
      <p>© {{ new Date().getFullYear() }} GDrive Upload Relay. Keeps your Google API keys secure.</p>
    </footer>
  </div>
</template>

<style>
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s ease-out;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
