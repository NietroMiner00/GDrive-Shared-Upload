<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface LinkItem {
  id: string;
  name: string;
  target_folder_id: string;
  expiry: string;
  created_at: string;
  uploaded_count: number;
  max_file_size_mb: number | null;
  allow_view?: boolean;
  allow_delete?: boolean;
  token?: string;
}

interface AppStatus {
  authenticated: boolean;
  has_credentials_json: boolean;
  passkey_configured: boolean;
}

interface BreadcrumbItem {
  id: string;
  name: string;
}

interface FolderItem {
  id: string;
  name: string;
}

const passkey = ref(localStorage.getItem('admin_passkey') || '')
const isAuthenticatedAdmin = ref(false)
const appStatus = ref<AppStatus>({ authenticated: false, has_credentials_json: false, passkey_configured: false })
const statusLoading = ref(true)

// Form fields for generating links
const newLinkName = ref('')
const targetFolderId = ref('')
const expiryDays = ref(7)
const maxFileSizeMb = ref<number | null>(null)
const allowView = ref(false)
const allowDelete = ref(false)
const generating = ref(false)
const formError = ref('')

const activeLinks = ref<LinkItem[]>([])
const loginError = ref('')
const verifying = ref(false)

// Folder Browser Modal States
const showBrowserModal = ref(false)
const browserFolderId = ref('root')
const browserFolders = ref<FolderItem[]>([])
const browserBreadcrumbs = ref<BreadcrumbItem[]>([])
const browserLoading = ref(false)
const newFolderName = ref('')
const creatingFolder = ref(false)

// Load API status and verify existing passkey on load
onMounted(() => {
  fetchStatus()
  if (passkey.value) {
    verifyPasskey()
  }
})

async function fetchStatus() {
  try {
    const res = await fetch('/api/status')
    if (res.ok) {
      appStatus.value = await res.json()
    }
  } catch (err) {
    console.error("Failed to fetch backend status:", err)
  } finally {
    statusLoading.value = false
  }
}

async function verifyPasskey() {
  if (!passkey.value) {
    loginError.value = "Passkey is required"
    return
  }
  verifying.value = true
  loginError.value = ''
  try {
    const res = await fetch('/api/links/list', {
      headers: {
        'Authorization': `Passkey ${passkey.value}`
      }
    })
    if (res.ok) {
      isAuthenticatedAdmin.value = true
      localStorage.setItem('admin_passkey', passkey.value)
      activeLinks.value = await res.json()
    } else {
      loginError.value = "Invalid passkey. Check your server console."
      isAuthenticatedAdmin.value = false
      localStorage.removeItem('admin_passkey')
    }
  } catch (err) {
    loginError.value = "Failed to communicate with server."
    console.error(err)
  } finally {
    verifying.value = false
  }
}

async function login() {
  await verifyPasskey()
}

function logout() {
  passkey.value = ''
  isAuthenticatedAdmin.value = false
  localStorage.removeItem('admin_passkey')
}

async function startGoogleOAuth() {
  try {
    const res = await fetch('/api/auth/google')
    if (res.ok) {
      const data = await res.json()
      if (data.authorization_url) {
        window.location.href = data.authorization_url
      }
    } else {
      const data = await res.json()
      alert(data.error || "Failed to initiate authorization.")
    }
  } catch (err) {
    alert("Connection error.")
  }
}

async function generateLink() {
  if (!newLinkName.value || !targetFolderId.value) {
    formError.value = "Please fill in all required fields."
    return
  }
  formError.value = ''
  generating.value = true
  try {
    const res = await fetch('/api/links/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Passkey ${passkey.value}`
      },
      body: JSON.stringify({
        name: newLinkName.value,
        target_folder_id: targetFolderId.value,
        expiry_days: expiryDays.value,
        max_file_size_mb: maxFileSizeMb.value || null,
        allow_view: allowView.value,
        allow_delete: allowDelete.value
      })
    })
    
    if (res.ok) {
      const newLink = await res.json()
      activeLinks.value.unshift(newLink)
      
      // Reset form
      newLinkName.value = ''
      targetFolderId.value = ''
      maxFileSizeMb.value = null
      allowView.value = false
      allowDelete.value = false
    } else {
      const data = await res.json()
      formError.value = data.error || "Failed to generate link"
    }
  } catch (err) {
    formError.value = "Network error occurred."
  } finally {
    generating.value = false
  }
}

async function revokeLink(id: string) {
  if (!confirm("Are you sure you want to revoke this upload link? Any uploads in progress will be cut off immediately.")) {
    return
  }
  try {
    const res = await fetch(`/api/links/revoke/${id}`, {
      method: 'POST',
      headers: {
        'Authorization': `Passkey ${passkey.value}`
      }
    })
    if (res.ok) {
      activeLinks.value = activeLinks.value.filter(link => link.id !== id)
    } else {
      alert("Failed to revoke link.")
    }
  } catch (err) {
    alert("Network error.")
  }
}

// Drive Browser Operations
async function openFolderBrowser() {
  if (!appStatus.value.authenticated) {
    alert("Please authenticate with Google Drive first.")
    return
  }
  showBrowserModal.value = true
  await fetchFolders(browserFolderId.value)
}

async function fetchFolders(folderId: string) {
  browserLoading.value = true
  try {
    const res = await fetch(`/api/admin/drive/list?parent_id=${folderId}`, {
      headers: {
        'Authorization': `Passkey ${passkey.value}`
      }
    })
    if (res.ok) {
      const data = await res.json()
      browserFolders.value = data.folders
      browserBreadcrumbs.value = data.breadcrumbs
      browserFolderId.value = data.current_folder_id
    } else {
      alert("Failed to retrieve directory contents.")
    }
  } catch (err) {
    console.error(err)
    alert("Network error listing folders.")
  } finally {
    browserLoading.value = false
  }
}

async function createSubfolder() {
  if (!newFolderName.value.trim()) return
  creatingFolder.value = true
  try {
    const res = await fetch('/api/admin/drive/create-folder', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Passkey ${passkey.value}`
      },
      body: JSON.stringify({
        name: newFolderName.value.trim(),
        parent_id: browserFolderId.value
      })
    })
    if (res.ok) {
      newFolderName.value = ''
      // Refresh directory list
      await fetchFolders(browserFolderId.value)
    } else {
      const data = await res.json()
      alert(data.error || "Failed to create folder.")
    }
  } catch (err) {
    alert("Network error creating folder.")
  } finally {
    creatingFolder.value = false
  }
}

function selectCurrentFolder() {
  targetFolderId.value = browserFolderId.value
  showBrowserModal.value = false
}

function getShareableUrl(token: string | undefined): string {
  if (!token) return ''
  return `${window.location.origin}/?token=${token}`
}

const copiedLinkId = ref('')

function copyToClipboard(id: string, text: string) {
  navigator.clipboard.writeText(text)
  copiedLinkId.value = id
  setTimeout(() => {
    copiedLinkId.value = ''
  }, 2000)
}

function formatDateTime(isoStr: string) {
  const dt = new Date(isoStr)
  return dt.toLocaleString()
}
</script>

<template>
  <div class="w-full">
    <!-- Login Card -->
    <div v-if="!isAuthenticatedAdmin" class="max-w-md mx-auto glass-card rounded-2xl p-8 border border-white/5 shadow-2xl glow-indigo">
      <div class="text-center mb-6">
        <span class="text-4xl">🔐</span>
        <h2 class="text-2xl font-bold mt-3 text-white">Admin Authentication</h2>
        <p class="text-slate-400 text-sm mt-1">Enter your auto-generated backend passkey to continue.</p>
      </div>

      <form @submit.prevent="login" class="space-y-4">
        <div>
          <label class="block text-slate-300 text-xs font-semibold uppercase tracking-wider mb-2" for="passkey-input">
            Admin Passkey
          </label>
          <input
            id="passkey-input"
            v-model="passkey"
            type="password"
            placeholder="Check backend console for key..."
            class="w-full bg-slate-900 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition duration-200"
            required
          />
        </div>

        <p v-if="loginError" class="text-rose-500 text-xs font-medium bg-rose-500/10 px-3.5 py-2 rounded-lg border border-rose-500/10">
          ⚠️ {{ loginError }}
        </p>

        <button
          type="submit"
          :disabled="verifying"
          class="w-full bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white font-semibold py-3 px-4 rounded-xl transition duration-200 shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30 cursor-pointer disabled:opacity-50"
        >
          <span v-if="verifying">Verifying...</span>
          <span v-else>Authenticate</span>
        </button>
      </form>
    </div>

    <!-- Authenticated Dashboard -->
    <div v-else class="space-y-8">
      <!-- Status Banner -->
      <div class="glass-card rounded-2xl p-6 border border-white/5 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <h2 class="text-xl font-bold text-white flex items-center gap-2">
            System Dashboard
            <span v-if="appStatus.authenticated" class="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
              Connected
            </span>
            <span v-else class="inline-flex items-center rounded-full bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-400 ring-1 ring-inset ring-amber-500/20">
              Auth Needed
            </span>
          </h2>
          <p class="text-slate-400 text-sm mt-1">
            Configure Google Drive and generate secure file upload links.
          </p>
        </div>

        <div class="flex items-center gap-3">
          <!-- Google Auth Trigger -->
          <button
            v-if="!appStatus.authenticated"
            @click="startGoogleOAuth"
            class="bg-amber-600 hover:bg-amber-500 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition cursor-pointer shadow-lg shadow-amber-600/20"
          >
            🔑 Connect Google Drive
          </button>
          
          <button
            @click="logout"
            class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-sm font-semibold px-4 py-2.5 rounded-xl transition cursor-pointer"
          >
            Logout
          </button>
        </div>
      </div>

      <!-- Warning if credentials.json is missing -->
      <div v-if="!appStatus.has_credentials_json" class="bg-rose-500/10 border border-rose-500/20 rounded-2xl p-6 flex items-start gap-4">
        <span class="text-2xl mt-0.5">⚠️</span>
        <div>
          <h3 class="font-bold text-rose-200">credentials.json Missing!</h3>
          <p class="text-slate-300 text-sm mt-1">
            Please download your Google Desktop Client secrets file, rename it to <code class="bg-black/30 px-1 py-0.5 rounded text-rose-300">credentials.json</code>, and place it in the <code class="bg-black/30 px-1 py-0.5 rounded">backend/</code> directory. Then restart the Flask server.
          </p>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <!-- Link Generator Form -->
        <div class="lg:col-span-1 glass-card rounded-2xl p-6 border border-white/5 space-y-6 glow-purple h-fit">
          <div>
            <h3 class="text-lg font-bold text-white">Generate Upload Link</h3>
            <p class="text-slate-400 text-xs mt-1">Create a signed link for friends to drop files.</p>
          </div>

          <form @submit.prevent="generateLink" class="space-y-4">
            <div>
              <label class="block text-slate-400 text-xs font-medium mb-1.5" for="invite-name">
                Friendly Name *
              </label>
              <input
                id="invite-name"
                v-model="newLinkName"
                type="text"
                placeholder="e.g. Game Jam Summer 2026"
                class="w-full bg-slate-900 border border-white/10 rounded-xl px-4.5 py-2.5 text-white text-sm focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition duration-200"
                required
              />
            </div>

            <div>
              <label class="block text-slate-400 text-xs font-medium mb-1.5 flex justify-between items-center" for="folder-id">
                <span>Google Drive Folder ID *</span>
                <button
                  type="button"
                  @click="openFolderBrowser"
                  class="text-[10px] text-indigo-400 hover:text-indigo-300 font-semibold uppercase tracking-wider flex items-center gap-1 cursor-pointer"
                >
                  📂 Browse Drive
                </button>
              </label>
              <input
                id="folder-id"
                v-model="targetFolderId"
                type="text"
                placeholder="Select or paste folder hash"
                class="w-full bg-slate-900 border border-white/10 rounded-xl px-4.5 py-2.5 text-white text-sm focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition duration-200"
                required
              />
            </div>

            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-slate-400 text-xs font-medium mb-1.5" for="expiry-days">
                  Expiration (Days)
                </label>
                <input
                  id="expiry-days"
                  v-model="expiryDays"
                  type="number"
                  min="1"
                  max="365"
                  class="w-full bg-slate-900 border border-white/10 rounded-xl px-4.5 py-2.5 text-white text-sm focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition duration-200"
                />
              </div>

              <div>
                <label class="block text-slate-400 text-xs font-medium mb-1.5" for="max-size">
                  Max Size (MB)
                </label>
                <input
                  id="max-size"
                  v-model="maxFileSizeMb"
                  type="number"
                  placeholder="Unlimited"
                  min="1"
                  class="w-full bg-slate-900 border border-white/10 rounded-xl px-4.5 py-2.5 text-white text-sm focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition duration-200"
                />
              </div>
            </div>

            <!-- Permission Checkboxes -->
            <div class="space-y-2 pt-2 border-t border-white/5">
              <div class="flex items-center gap-2">
                <input
                  id="allow-view"
                  v-model="allowView"
                  type="checkbox"
                  class="h-4 w-4 rounded border-white/10 bg-slate-900 text-indigo-600 focus:ring-indigo-500"
                />
                <label for="allow-view" class="text-xs text-slate-300 font-medium select-none cursor-pointer">
                  Allow viewing folder contents
                </label>
              </div>

              <div class="flex items-center gap-2">
                <input
                  id="allow-delete"
                  v-model="allowDelete"
                  type="checkbox"
                  class="h-4 w-4 rounded border-white/10 bg-slate-900 text-indigo-600 focus:ring-indigo-500"
                />
                <label for="allow-delete" class="text-xs text-slate-300 font-medium select-none cursor-pointer">
                  Allow deleting files
                </label>
              </div>
            </div>

            <p v-if="formError" class="text-rose-500 text-xs font-medium bg-rose-500/10 px-3.5 py-2 rounded-lg border border-rose-500/10">
              {{ formError }}
            </p>

            <button
              type="submit"
              :disabled="generating"
              class="w-full bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-600 hover:to-indigo-700 text-white font-semibold py-2.5 rounded-xl transition duration-200 shadow-md cursor-pointer disabled:opacity-50 text-sm"
            >
              <span v-if="generating">Generating...</span>
              <span v-else>Generate Upload Link</span>
            </button>
          </form>
        </div>

        <!-- Links List -->
        <div class="lg:col-span-2 glass-card rounded-2xl p-6 border border-white/5 flex flex-col min-h-[400px]">
          <div class="mb-4">
            <h3 class="text-lg font-bold text-white">Active Upload Links</h3>
            <p class="text-slate-400 text-xs mt-1">Directly revoke access or copy link URLs.</p>
          </div>

          <div v-if="activeLinks.length === 0" class="flex-grow flex flex-col items-center justify-center text-center text-slate-500 p-8 border border-dashed border-white/5 rounded-xl">
            <span class="text-3xl mb-2">🔗</span>
            <p class="text-sm">No upload links created yet.</p>
            <p class="text-xs mt-1">Use the generator on the left to create one.</p>
          </div>

          <div v-else class="space-y-4 overflow-y-auto max-h-[500px] pr-2">
            <div 
              v-for="link in activeLinks" 
              :key="link.id" 
              class="bg-slate-900/60 rounded-xl p-4 border border-white/5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 transition hover:bg-slate-900/90"
            >
              <div class="space-y-1.5 flex-grow min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <h4 class="font-semibold text-white text-sm">{{ link.name }}</h4>
                  <span class="text-[10px] bg-slate-800 text-slate-300 font-mono px-2 py-0.5 rounded">
                    uploads: {{ link.uploaded_count }}
                  </span>
                  <!-- Display active flags -->
                  <span v-if="link.allow_view" class="text-[8px] uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded font-bold">
                    View
                  </span>
                  <span v-if="link.allow_delete" class="text-[8px] uppercase tracking-wider bg-rose-500/10 text-rose-400 border border-rose-500/20 px-1.5 py-0.5 rounded font-bold">
                    Delete
                  </span>
                </div>
                <div class="text-xs text-slate-400 font-mono select-all bg-black/25 px-2.5 py-1 rounded max-w-full truncate">
                  {{ getShareableUrl(link.token) }}
                </div>
                <div class="flex items-center gap-4 text-[10px] text-slate-500">
                  <span>Folder ID: {{ link.target_folder_id.slice(0,8) }}...{{ link.target_folder_id.slice(-6) }}</span>
                  <span>Expires: {{ formatDateTime(link.expiry) }}</span>
                  <span v-if="link.max_file_size_mb">Max Size: {{ link.max_file_size_mb }}MB</span>
                </div>
              </div>

              <div class="flex items-center gap-2 w-full md:w-auto justify-end border-t border-white/5 md:border-t-0 pt-2.5 md:pt-0">
                <button
                  @click="copyToClipboard(link.id, getShareableUrl(link.token))"
                  class="bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-3.5 py-2 rounded-lg transition cursor-pointer"
                >
                  {{ copiedLinkId === link.id ? 'Copied!' : 'Copy URL' }}
                </button>
                <button
                  @click="revokeLink(link.id)"
                  class="bg-rose-500/10 hover:bg-rose-500/25 border border-rose-500/20 text-rose-400 text-xs font-semibold px-3.5 py-2 rounded-lg transition cursor-pointer"
                >
                  Revoke
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Drive Folder Selector Modal -->
    <div v-if="showBrowserModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div class="glass-card w-full max-w-2xl rounded-2xl border border-white/10 shadow-2xl p-6 flex flex-col max-h-[85vh]">
        <!-- Header -->
        <div class="flex items-center justify-between pb-4 border-b border-white/5">
          <h3 class="text-lg font-bold text-white flex items-center gap-2">
            <span>📁</span> Google Drive Browser
          </h3>
          <button 
            @click="showBrowserModal = false"
            class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/5 transition cursor-pointer"
          >
            ✕
          </button>
        </div>

        <!-- Breadcrumbs Navigation -->
        <div class="flex items-center gap-1.5 py-3 overflow-x-auto text-xs border-b border-white/5 font-medium scrollbar-thin">
          <span 
            v-for="(bc, index) in browserBreadcrumbs" 
            :key="bc.id"
            class="flex items-center gap-1.5 shrink-0"
          >
            <button 
              @click="fetchFolders(bc.id)" 
              class="text-indigo-400 hover:text-indigo-300 font-semibold cursor-pointer"
            >
              {{ bc.name }}
            </button>
            <span v-if="index < browserBreadcrumbs.length - 1" class="text-slate-600">/</span>
          </span>
        </div>

        <!-- Subfolders List -->
        <div class="flex-grow overflow-y-auto py-4 space-y-2 min-h-[250px] max-h-[400px]">
          <div v-if="browserLoading" class="flex flex-col items-center justify-center h-[200px] text-slate-400">
            <div class="h-8 w-8 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin"></div>
            <p class="text-xs mt-3">Loading directories...</p>
          </div>

          <div v-else-if="browserFolders.length === 0" class="flex flex-col items-center justify-center h-[200px] text-slate-500 text-center">
            <span class="text-2xl mb-1">📂</span>
            <p class="text-sm font-semibold">No subfolders found</p>
            <p class="text-xs">Create a new folder below or select the current one.</p>
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div 
              v-for="folder in browserFolders" 
              :key="folder.id"
              @dblclick="fetchFolders(folder.id)"
              @click="fetchFolders(folder.id)"
              class="flex items-center gap-3 p-3 bg-slate-900/50 hover:bg-slate-900 border border-white/5 rounded-xl transition cursor-pointer select-none"
            >
              <span class="text-xl">📁</span>
              <span class="text-sm font-medium text-slate-200 truncate">{{ folder.name }}</span>
            </div>
          </div>
        </div>

        <!-- Create Folder Area -->
        <div class="pt-4 border-t border-white/5">
          <form @submit.prevent="createSubfolder" class="flex items-center gap-2">
            <input 
              v-model="newFolderName"
              placeholder="New folder name..."
              class="flex-grow bg-slate-900 border border-white/10 rounded-xl px-4 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
              required
            />
            <button 
              type="submit"
              :disabled="creatingFolder"
              class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs px-4 py-2 rounded-xl transition cursor-pointer shrink-0"
            >
              {{ creatingFolder ? 'Creating...' : '+ Create Folder' }}
            </button>
          </form>
        </div>

        <!-- Actions -->
        <div class="flex items-center justify-end gap-3 pt-6 border-t border-white/5 mt-4">
          <button 
            @click="showBrowserModal = false"
            class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-semibold px-4 py-2.5 rounded-xl transition cursor-pointer"
          >
            Cancel
          </button>
          <button 
            @click="selectCurrentFolder"
            class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl transition cursor-pointer shadow-lg shadow-indigo-600/20"
          >
            Select Current Folder
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
