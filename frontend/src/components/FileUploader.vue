<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps<{
  token: string
}>()

interface ValidationDetails {
  name: string;
  folder_name: string;
  expiry: string;
  max_file_size_mb: number | null;
  allow_view: boolean;
  allow_delete: boolean;
}

interface GoogleFileItem {
  id: string;
  name: string;
  mimeType: string;
  md5Checksum?: string;
  size?: string;
  createdTime?: string;
}

interface BreadcrumbItem {
  id: string;
  name: string;
}

interface QueueItem {
  id: string;
  file: File;
  relativePath: string; // e.g. "myfolder/sub/file.zip" or "file.zip"
  size: number;
  status: 'queued' | 'uploading' | 'paused' | 'cancelled' | 'success' | 'failed';
  progress: number;
  bytesUploaded: number;
  speed: number;
  eta: number | null;
  sessionId?: string;
  error?: string;
  targetFolderId: string;
}

interface IncompleteSession {
  session_id: string;
  filename: string;
  filesize: number;
  folder_id: string;
  bytes_uploaded: number;
  created_at: string;
}

interface ChecksumVerifyResult {
  [filename: string]: {
    expectedMd5: string;
    actualMd5?: string;
    status: 'verified' | 'mismatch' | 'not_found_on_drive';
  }
}

const isValidating = ref(true)
const linkDetails = ref<ValidationDetails | null>(null)
const validationError = ref('')

// File Selection & Drag States
const isDragging = ref(false)

// Queue management
const uploadQueue = ref<QueueItem[]>([])
const queueState = ref<'idle' | 'uploading' | 'paused'>('idle')
const currentItemIndex = ref(-1)

// Incomplete uploads list
const incompleteUploads = ref<IncompleteSession[]>([])
const loadingIncomplete = ref(false)
const activeResumeSession = ref<IncompleteSession | null>(null)

// Checksum Verifier States
const loadedChecksums = ref<{ [filename: string]: string }>({})
const checksumFilename = ref('')
const verificationResults = ref<ChecksumVerifyResult>({})
const showChecksumVerification = ref(false)
const verificationRootPath = ref('')

// Folder contents cache to avoid redundant API checking
const folderContentsCache = ref<{ [folderId: string]: GoogleFileItem[] }>({})
const resolvedFoldersCache = ref<{ [key: string]: string }>({})

// Directory Explorer States
const currentFolderId = ref('')
const rootFolderId = ref('')
const explorerBreadcrumbs = ref<BreadcrumbItem[]>([])
const explorerFiles = ref<GoogleFileItem[]>([])
const explorerLoading = ref(false)
const explorerError = ref('')

// Performance tracking for active chunk upload
let activeXhr: XMLHttpRequest | null = null
let speedInterval: any = null
let lastUploadedBytes = 0
let lastUploadedTime = 0

onMounted(async () => {
  await validateToken()
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
})

function handleBeforeUnload(e: BeforeUnloadEvent) {
  if (queueState.value === 'uploading') {
    e.preventDefault()
    e.returnValue = '' // Prompts standard browser dialog
  }
}

async function validateToken() {
  try {
    const res = await fetch(`/api/links/validate?token=${encodeURIComponent(props.token)}`)
    if (res.ok) {
      const data = await res.json()
      linkDetails.value = data
      
      // Load folder contents and incomplete lists if viewing is allowed
      if (data.allow_view) {
        await fetchFolderContents('')
      }
      await fetchIncompleteUploads()
    } else {
      const data = await res.json()
      validationError.value = data.error || "The link token is invalid or expired."
    }
  } catch (err) {
    validationError.value = "Failed to connect to the upload server."
  } finally {
    isValidating.value = false
  }
}

async function fetchFolderContents(folderId: string) {
  explorerLoading.value = true
  explorerError.value = ''
  try {
    const folderParam = folderId ? `&folder_id=${folderId}` : ''
    const res = await fetch(`/api/upload/files?token=${encodeURIComponent(props.token)}${folderParam}`)
    if (res.ok) {
      const data = await res.json()
      explorerFiles.value = data.files
      explorerBreadcrumbs.value = data.breadcrumbs
      
      if (data.breadcrumbs && data.breadcrumbs.length > 0) {
        const leafFolderId = data.breadcrumbs[data.breadcrumbs.length - 1].id
        folderContentsCache.value[leafFolderId] = data.files
        currentFolderId.value = leafFolderId
        if (!rootFolderId.value) {
          rootFolderId.value = data.breadcrumbs[0].id
        }
      }
      
      // Rerun checksum validation with new file list if active
      if (showChecksumVerification.value) {
        runChecksumVerification()
      }
    } else {
      const data = await res.json()
      explorerError.value = data.error || "Failed to load files list."
    }
  } catch (err) {
    explorerError.value = "Failed to fetch files list."
  } finally {
    explorerLoading.value = false
  }
}

async function fetchIncompleteUploads() {
  loadingIncomplete.value = true
  try {
    const res = await fetch(`/api/upload/incomplete?token=${encodeURIComponent(props.token)}`)
    if (res.ok) {
      incompleteUploads.value = await res.json()
    }
  } catch (err) {
    console.error("Failed to query incomplete sessions:", err)
  } finally {
    loadingIncomplete.value = false
  }
}

async function deleteFile(fileId: string, fileName: string) {
  if (!confirm(`Are you sure you want to delete "${fileName}"? This action cannot be undone.`)) {
    return
  }
  try {
    const res = await fetch(`/api/upload/file/${fileId}?token=${encodeURIComponent(props.token)}`, {
      method: 'DELETE'
    })
    if (res.ok) {
      await fetchFolderContents(currentFolderId.value)
    } else {
      const data = await res.json()
      alert(data.error || "Failed to delete file.")
    }
  } catch (err) {
    alert("Connection error during deletion.")
  }
}

async function deleteIncompleteSession(sessionId: string) {
  if (!confirm("Are you sure you want to discard this incomplete upload?")) return
  try {
    const res = await fetch(`/api/upload/session/${sessionId}?token=${encodeURIComponent(props.token)}`, {
      method: 'DELETE'
    })
    if (res.ok) {
      incompleteUploads.value = incompleteUploads.value.filter(s => s.session_id !== sessionId)
    } else {
      alert("Failed to discard session.")
    }
  } catch (err) {
    alert("Network error.")
  }
}

// Drag and Drop Traversal
function handleDragOver(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function handleDragLeave() {
  isDragging.value = false
}

async function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  
  if (e.dataTransfer?.items) {
    const items = Array.from(e.dataTransfer.items)
    const fileEntries: { file: File; relativePath: string }[] = []
    
    for (const item of items) {
      if (item.kind === 'file') {
        const entry = item.webkitGetAsEntry()
        if (entry) {
          await traverseDirectory(entry, '', fileEntries)
        }
      }
    }
    
    enqueueFiles(fileEntries)
  } else if (e.dataTransfer?.files) {
    const files = Array.from(e.dataTransfer.files)
    enqueueFiles(files.map(file => ({ file, relativePath: file.name })))
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files) {
    const files = Array.from(input.files)
    // Preserves directories if picking folders, otherwise uses simple names
    enqueueFiles(files.map(file => ({ 
      file, 
      relativePath: file.webkitRelativePath || file.name 
    })))
  }
}

// Traverse directory recursively using webkit directory API
async function traverseDirectory(entry: any, path: string, fileList: { file: File; relativePath: string }[]) {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject))
    fileList.push({ file, relativePath: path + file.name })
  } else if (entry.isDirectory) {
    const dirReader = entry.createReader()
    const entries = await readAllEntries(dirReader)
    for (const subEntry of entries) {
      await traverseDirectory(subEntry, path + entry.name + '/', fileList)
    }
  }
}

async function readAllEntries(dirReader: any): Promise<any[]> {
  let allEntries: any[] = []
  const read = async () => {
    const entries = await new Promise<any[]>((resolve, reject) => dirReader.readEntries(resolve, reject))
    if (entries.length > 0) {
      allEntries = allEntries.concat(entries)
      await read()
    }
  }
  await read()
  return allEntries
}

function enqueueFiles(filesList: { file: File; relativePath: string }[]) {
  for (const item of filesList) {
    // Validate size limit
    if (linkDetails.value?.max_file_size_mb) {
      const maxBytes = linkDetails.value.max_file_size_mb * 1024 * 1024
      if (item.file.size > maxBytes) {
        alert(`File "${item.file.name}" exceeds the maximum size of ${linkDetails.value.max_file_size_mb} MB. Skipping.`)
        continue
      }
    }
    
    // Add to queue
    uploadQueue.value.push({
      id: Math.random().toString(36).substring(2, 9),
      file: item.file,
      relativePath: item.relativePath,
      size: item.file.size,
      status: 'queued',
      progress: 0,
      bytesUploaded: 0,
      speed: 0,
      eta: null,
      targetFolderId: currentFolderId.value
    })
  }
  
  if (queueState.value === 'idle') {
    startQueue()
  }
}

// Queue supervisor operations
function startQueue() {
  if (uploadQueue.value.length === 0) return
  queueState.value = 'uploading'
  processNextQueueItem()
}

function pauseQueue() {
  queueState.value = 'paused'
  if (currentItemIndex.value >= 0 && currentItemIndex.value < uploadQueue.value.length) {
    const item = uploadQueue.value[currentItemIndex.value]
    if (item.status === 'uploading') {
      item.status = 'paused'
    }
  }
}

function resumeQueue() {
  queueState.value = 'uploading'
  if (currentItemIndex.value >= 0 && currentItemIndex.value < uploadQueue.value.length) {
    const item = uploadQueue.value[currentItemIndex.value]
    if (item.status === 'paused') {
      item.status = 'uploading'
      processNextQueueItem()
      return
    }
  }
  processNextQueueItem()
}

function cancelItem(id: string) {
  const index = uploadQueue.value.findIndex(item => item.id === id)
  if (index === -1) return
  
  const item = uploadQueue.value[index]
  
  if (item.status === 'uploading') {
    item.status = 'cancelled'
    if (activeXhr) {
      activeXhr.abort()
      activeXhr = null
    }
    stopSpeedTracking()
    
    if (item.sessionId) {
      fetch(`/api/upload/session/${item.sessionId}?token=${encodeURIComponent(props.token)}`, { method: 'DELETE' })
    }
    
    setTimeout(() => processNextQueueItem(), 200)
  } else {
    item.status = 'cancelled'
  }
}

function retryItem(id: string) {
  const item = uploadQueue.value.find(i => i.id === id)
  if (item) {
    item.status = 'queued'
    item.progress = 0
    item.bytesUploaded = 0
    item.error = ''
    if (queueState.value === 'idle') {
      startQueue()
    } else if (queueState.value === 'uploading') {
      processNextQueueItem()
    }
  }
}

function clearCompleted() {
  uploadQueue.value = uploadQueue.value.filter(item => 
    item.status !== 'success' && item.status !== 'cancelled' && item.status !== 'failed'
  )
  if (uploadQueue.value.length === 0) {
    queueState.value = 'idle'
    currentItemIndex.value = -1
  }
}

function cancelAll() {
  if (activeXhr) {
    activeXhr.abort()
    activeXhr = null
  }
  stopSpeedTracking()
  
  uploadQueue.value.forEach(item => {
    if (item.status === 'uploading' || item.status === 'queued' || item.status === 'paused') {
      item.status = 'cancelled'
      if (item.sessionId) {
        fetch(`/api/upload/session/${item.sessionId}?token=${encodeURIComponent(props.token)}`, { method: 'DELETE' })
      }
    }
  })
  
  queueState.value = 'idle'
  currentItemIndex.value = -1
}

async function processNextQueueItem() {
  if (queueState.value !== 'uploading') return
  
  const nextIdx = uploadQueue.value.findIndex(item => item.status === 'queued' || item.status === 'paused')
  if (nextIdx === -1) {
    queueState.value = 'idle'
    currentItemIndex.value = -1
    await fetchIncompleteUploads() // Refresh incomplete list at completion
    return
  }
  
  currentItemIndex.value = nextIdx
  const item = uploadQueue.value[nextIdx]
  item.status = 'uploading'
  
  try {
    // 1. Recreate directory structures if dropped inside nested folders
    let destinationFolderId = item.targetFolderId
    if (item.relativePath.includes('/')) {
      const folderPath = item.relativePath.substring(0, item.relativePath.lastIndexOf('/'))
      const cacheKey = `${item.targetFolderId}::${folderPath}`
      
      if (resolvedFoldersCache.value[cacheKey]) {
        destinationFolderId = resolvedFoldersCache.value[cacheKey]
      } else {
        const folderRes = await fetch('/api/upload/ensure-folders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: props.token,
            parent_id: item.targetFolderId,
            path: folderPath
          })
        })
        if (!folderRes.ok) {
          throw new Error("Failed to configure remote subfolders structure.")
        }
        const folderData = await folderRes.json()
        destinationFolderId = folderData.folder_id
        resolvedFoldersCache.value[cacheKey] = destinationFolderId
      }
    }
    
    item.targetFolderId = destinationFolderId // Update target to final subfolder ID
    
    // Check if destination folder is in cache. Fetch if missing and allow_view is true.
    if (linkDetails.value?.allow_view && !folderContentsCache.value[destinationFolderId]) {
      const folderParam = destinationFolderId ? `&folder_id=${destinationFolderId}` : ''
      const cacheRes = await fetch(`/api/upload/files?token=${encodeURIComponent(props.token)}${folderParam}`)
      if (cacheRes.ok) {
        const cacheData = await cacheRes.json()
        folderContentsCache.value[destinationFolderId] = cacheData.files
      }
    }
    
    // Check cache for duplicate file name and size to skip API call overhead
    if (linkDetails.value?.allow_view && folderContentsCache.value[destinationFolderId]) {
      const cachedFiles = folderContentsCache.value[destinationFolderId]
      const duplicate = cachedFiles.find(f => !isFolder(f.mimeType) && f.name === item.file.name && Number(f.size) === item.file.size)
      if (duplicate) {
        item.progress = 100
        item.bytesUploaded = item.size
        item.status = 'success'
        
        if (destinationFolderId === currentFolderId.value) {
          await fetchFolderContents(currentFolderId.value)
        }
        
        processNextQueueItem()
        return
      }
    }
    
    // 2. Initiate resumable upload with backend
    const initRes = await fetch('/api/upload/initiate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: props.token,
        filename: item.file.name,
        filesize: item.file.size,
        mimetype: item.file.type || 'application/octet-stream',
        folder_id: destinationFolderId
      })
    })
    
    if (!initRes.ok) {
      const data = await initRes.json()
      throw new Error(data.error || "Failed to initiate session")
    }
    
    const initData = await initRes.json()
    if (initData.completed) {
      item.progress = 100
      item.bytesUploaded = item.size
      item.status = 'success'
      if (linkDetails.value?.allow_view) {
        await fetchFolderContents(currentFolderId.value)
      }
      processNextQueueItem()
      return
    }
    
    const { session_id, chunk_size, bytes_uploaded, resumed } = initData
    item.sessionId = session_id
    item.bytesUploaded = bytes_uploaded || 0
    
    // Instantly remove from incomplete list since we are actively uploading it!
    incompleteUploads.value = incompleteUploads.value.filter(s => s.session_id !== session_id)
    
    if (resumed && bytes_uploaded > 0) {
      item.progress = Math.min(Math.round((bytes_uploaded / item.size) * 100), 99)
    }
    
    // Start speed tracking
    startSpeedTracking(item)
    
    // 3. Upload chunks
    await uploadFileInChunks(item, session_id, chunk_size)
    
  } catch (err: any) {
    if ((item.status as string) === 'cancelled') return
    
    console.error(err)
    item.status = 'failed'
    item.error = err.message || "Failed to upload."
    stopSpeedTracking()
    processNextQueueItem()
  }
}

async function uploadFileInChunks(item: QueueItem, sessionId: string, chunkSize: number) {
  const file = item.file
  const total = item.size
  let currentChunkSize = chunkSize
  
  while (item.bytesUploaded < total) {
    if (queueState.value === 'paused') {
      item.status = 'paused'
      stopSpeedTracking()
      return
    }
    if (item.status === 'cancelled') {
      stopSpeedTracking()
      return
    }
    
    const start = item.bytesUploaded
    const end = Math.min(start + currentChunkSize, total)
    const chunk = file.slice(start, end)
    
    const rangeHeader = `bytes ${start}-${end - 1}/${total}`
    
    const chunkStartTime = Date.now()
    
    await new Promise<boolean>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      activeXhr = xhr
      
      xhr.open('PUT', `/api/upload/chunk/${sessionId}`)
      xhr.setRequestHeader('Content-Range', rangeHeader)
      xhr.setRequestHeader('Content-Type', 'application/octet-stream')
      
      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) {
          item.bytesUploaded = start + evt.loaded
          item.progress = Math.min(Math.round((item.bytesUploaded / total) * 100), 99)
        }
      }
      
      xhr.onload = () => {
        activeXhr = null
        if (xhr.status === 200 || xhr.status === 201) {
          item.bytesUploaded = total
          item.progress = 100
          item.status = 'success'
          resolve(true)
        } else if (xhr.status === 308) {
          item.bytesUploaded = end
          item.progress = Math.min(Math.round((end / total) * 100), 99)
          resolve(true)
        } else {
          try {
            const data = JSON.parse(xhr.responseText)
            reject(new Error(data.error || "Chunk upload rejected by server."))
          } catch {
            reject(new Error(`Server error: status ${xhr.status}`))
          }
        }
      }
      
      xhr.onerror = () => {
        activeXhr = null
        reject(new Error("Connection error occurred during chunk transfer."))
      }
      
      xhr.send(chunk)
    })
    
    // Dynamically adjust chunk size based on performance (target 4s duration per request)
    const elapsedSecs = (Date.now() - chunkStartTime) / 1000
    if (elapsedSecs > 0 && (item.status as string) !== 'failed' && (item.status as string) !== 'cancelled') {
      const bytesTransferred = end - start
      const currentSpeed = bytesTransferred / elapsedSecs
      
      const targetDurationSecs = 4
      let newChunkSize = currentSpeed * targetDurationSecs
      
      const minChunk = 256 * 1024
      const maxChunk = 1024 * 1024 * 1024
      
      if (newChunkSize < minChunk) newChunkSize = minChunk
      if (newChunkSize > maxChunk) newChunkSize = maxChunk
      
      newChunkSize = Math.round(newChunkSize / (256 * 1024)) * (256 * 1024)
      if (newChunkSize < minChunk) newChunkSize = minChunk
      
      currentChunkSize = Math.round((currentChunkSize + newChunkSize) / 2)
      currentChunkSize = Math.round(currentChunkSize / (256 * 1024)) * (256 * 1024)
      if (currentChunkSize < minChunk) currentChunkSize = minChunk
    }
    
    if (item.status === 'success') {
      stopSpeedTracking()
      
      if (item.sessionId) {
        incompleteUploads.value = incompleteUploads.value.filter(s => s.session_id !== item.sessionId)
      }
      
      // Update cache with successfully uploaded file metadata
      const destId = item.targetFolderId
      if (folderContentsCache.value[destId]) {
        const exists = folderContentsCache.value[destId].some(f => f.name === item.file.name)
        if (!exists) {
          folderContentsCache.value[destId].push({
            id: 'uploaded-' + Math.random().toString(36).substring(2, 9),
            name: item.file.name,
            mimeType: item.file.type || 'application/octet-stream',
            size: String(item.file.size)
          })
        }
      }
      
      if (linkDetails.value?.allow_view) {
        await fetchFolderContents(currentFolderId.value)
      }
      processNextQueueItem()
      return
    }
  }
}

// Resuming incomplete upload manually with picker
const resumeFileInput = ref<HTMLInputElement | null>(null)

function triggerResume(session: IncompleteSession) {
  activeResumeSession.value = session
  resumeFileInput.value?.click()
}

function handleResumeFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0 || !activeResumeSession.value) return
  
  const file = input.files[0]
  const session = activeResumeSession.value
  
  if (file.name !== session.filename || file.size !== session.filesize) {
    alert(`File mismatch! Please select the exact matching file:\nName: "${session.filename}"\nSize: ${formatBytes(session.filesize)}`)
    input.value = ''
    return
  }
  
  // Enqueue the item directly linked to the existing session
  uploadQueue.value.push({
    id: Math.random().toString(36).substring(2, 9),
    file: file,
    relativePath: file.name,
    size: file.size,
    status: 'queued',
    progress: Math.min(Math.round((session.bytes_uploaded / file.size) * 100), 99),
    bytesUploaded: session.bytes_uploaded,
    speed: 0,
    eta: null,
    sessionId: session.session_id,
    targetFolderId: session.folder_id
  })
  
  // Filter it out from UI list since it's now active in the queue
  incompleteUploads.value = incompleteUploads.value.filter(s => s.session_id !== session.session_id)
  activeResumeSession.value = null
  input.value = ''
  
  if (queueState.value === 'idle') {
    startQueue()
  } else if (queueState.value === 'uploading') {
    processNextQueueItem()
  }
}

// Checksums Manifest Upload & Parsing
const checksumFileInput = ref<HTMLInputElement | null>(null)

function triggerChecksumFilePicker() {
  checksumFileInput.value?.click()
}

function handleChecksumFileLoad(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return
  
  const file = input.files[0]
  checksumFilename.value = file.name
  
  const reader = new FileReader()
  reader.onload = (event) => {
    const text = event.target?.result as string
    parseChecksumFile(text)
  }
  reader.readAsText(file)
  input.value = ''
}

function parseChecksumFile(text: string) {
  // Reconstruct relative directory path where the MD5 file is loaded
  verificationRootPath.value = explorerBreadcrumbs.value.slice(1).map(b => b.name).join('/')
  
  const lines = text.split('\n')
  const map: { [filename: string]: string } = {}
  const regex = /^([a-fA-F0-9]{32})[\s*]+(.+)$/
  
  for (let line of lines) {
    line = line.trim()
    if (!line) continue
    const match = line.match(regex)
    if (match) {
      const md5 = match[1].toLowerCase()
      const rawFilename = match[2].trim()
      // Normalize backslashes to forward slashes and strip leading "./"
      const normalizedPath = rawFilename.replace(/\\/g, '/').replace(/^\.\//, '')
      map[normalizedPath] = md5
    }
  }
  
  loadedChecksums.value = map
  showChecksumVerification.value = true
  runChecksumVerification()
}

function runChecksumVerification() {
  if (Object.keys(loadedChecksums.value).length === 0) return
  
  const results: ChecksumVerifyResult = {}
  
  // Reconstruct current relative path from breadcrumbs
  const currentDirPath = explorerBreadcrumbs.value.slice(1).map(b => b.name).join('/')
  
  // Create a map of files in the current folder on Google Drive
  const driveFileMap: { [name: string]: GoogleFileItem } = {}
  for (const file of explorerFiles.value) {
    if (!isFolder(file.mimeType)) {
      driveFileMap[file.name] = file
    }
  }
  
  // Verify checksum entries that belong to the current navigated folder
  for (const [manifestPath, expectedMd5] of Object.entries(loadedChecksums.value)) {
    // Resolve full path relative to link root by prefixing verification root path
    const fullPath = verificationRootPath.value
      ? `${verificationRootPath.value}/${manifestPath}`
      : manifestPath
      
    const lastSlashIdx = fullPath.lastIndexOf('/')
    const manifestFolderPath = lastSlashIdx !== -1 ? fullPath.substring(0, lastSlashIdx) : ''
    const manifestFilename = lastSlashIdx !== -1 ? fullPath.substring(lastSlashIdx + 1) : fullPath
    
    // Check if this manifest item belongs to the current directory (case-insensitive)
    if (manifestFolderPath.toLowerCase() === currentDirPath.toLowerCase()) {
      const driveFile = driveFileMap[manifestFilename]
      if (driveFile) {
        const actualMd5 = driveFile.md5Checksum ? driveFile.md5Checksum.toLowerCase() : ''
        if (actualMd5 === expectedMd5) {
          results[manifestPath] = {
            expectedMd5,
            actualMd5,
            status: 'verified'
          }
        } else {
          results[manifestPath] = {
            expectedMd5,
            actualMd5,
            status: 'mismatch'
          }
        }
      } else {
        results[manifestPath] = {
          expectedMd5,
          status: 'not_found_on_drive'
        }
      }
    }
  }
  
  verificationResults.value = results
}

function getVerificationResult(fileName: string) {
  const currentDirPath = explorerBreadcrumbs.value.slice(1).map(b => b.name).join('/')
  const fullPath = currentDirPath ? (currentDirPath + '/' + fileName) : fileName
  
  // Strip verificationRootPath prefix to get expected manifestPath key
  let manifestPath = fullPath
  if (verificationRootPath.value) {
    const prefix = verificationRootPath.value + '/'
    if (fullPath.startsWith(prefix)) {
      manifestPath = fullPath.substring(prefix.length)
    }
  }
  
  if (verificationResults.value[manifestPath]) {
    return verificationResults.value[manifestPath]
  }
  if (verificationResults.value[fileName]) {
    return verificationResults.value[fileName]
  }
  return null
}

function clearChecksumVerification() {
  loadedChecksums.value = {}
  checksumFilename.value = ''
  verificationResults.value = {}
  showChecksumVerification.value = false
  verificationRootPath.value = ''
}

// Download local files MD5 sum manifest
function downloadMd5Manifest() {
  let content = ''
  for (const file of explorerFiles.value) {
    if (!isFolder(file.mimeType) && file.md5Checksum) {
      content += `${file.md5Checksum.toLowerCase()}  ${file.name}\n`
    }
  }
  if (!content) {
    alert("No uploaded files with checksums found in this directory.")
    return
  }
  
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${linkDetails.value?.name || 'folder'}_checksums.md5`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// Speed Tracking Helpers
function startSpeedTracking(item: QueueItem) {
  lastUploadedBytes = item.bytesUploaded
  lastUploadedTime = Date.now()
  let lastProgressTime = Date.now()
  
  speedInterval = setInterval(() => {
    const now = Date.now()
    const elapsedSecs = (now - lastUploadedTime) / 1000
    if (elapsedSecs > 0) {
      const chunkBytes = item.bytesUploaded - lastUploadedBytes
      
      if (chunkBytes > 0) {
        lastProgressTime = now
        const calculatedSpeed = chunkBytes / elapsedSecs
        // Smooth speed with moving average to eliminate sudden drops
        item.speed = item.speed === 0 ? calculatedSpeed : (item.speed * 0.7 + calculatedSpeed * 0.3)
      } else {
        const idleTime = (now - lastProgressTime) / 1000
        if (idleTime > 3) {
          // Decay speed to 0 if idle for more than 3s (real stall)
          item.speed = item.speed * 0.5
          if (item.speed < 10) item.speed = 0
        }
        // If idleTime <= 3, keep the last speed to buffer between chunks/handshakes
      }
      
      const remainingBytes = item.size - item.bytesUploaded
      if (item.speed > 0) {
        item.eta = Math.ceil(remainingBytes / item.speed)
      } else {
        item.eta = null
      }
      
      lastUploadedBytes = item.bytesUploaded
      lastUploadedTime = now
    }
  }, 1000)
}

function stopSpeedTracking() {
  if (speedInterval) {
    clearInterval(speedInterval)
    speedInterval = null
  }
}

function formatBytes(bytes: number | string, decimals = 2) {
  const bytesNum = typeof bytes === 'string' ? parseInt(bytes, 10) : bytes
  if (isNaN(bytesNum) || bytesNum === 0) return '0 Bytes'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytesNum) / Math.log(k))
  return parseFloat((bytesNum / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}

function formatSpeed(bytesPerSec: number) {
  return `${formatBytes(bytesPerSec, 1)}/s`
}

function formatEta(secs: number) {
  if (secs < 60) return `${secs}s remaining`
  const mins = Math.floor(secs / 60)
  const remainingSecs = secs % 60
  return `${mins}m ${remainingSecs}s remaining`
}

function copyChecksum(text: string) {
  navigator.clipboard.writeText(text)
  alert("MD5 Checksum copied to clipboard!")
}

function isFolder(mimeType: string) {
  return mimeType === 'application/vnd.google-apps.folder'
}

// Queue Stats Computeds
const totalQueueSize = computed(() => {
  return uploadQueue.value.reduce((acc, item) => acc + item.size, 0)
})

const totalQueueUploadedBytes = computed(() => {
  return uploadQueue.value.reduce((acc, item) => acc + item.bytesUploaded, 0)
})

const overallProgress = computed(() => {
  if (uploadQueue.value.length === 0) return 0
  return Math.round((totalQueueUploadedBytes.value / totalQueueSize.value) * 100)
})

const pendingCount = computed(() => {
  return uploadQueue.value.filter(item => item.status === 'queued' || item.status === 'paused').length
})

// Checksums verification list stats
const missingVerificationFiles = computed(() => {
  return Object.entries(verificationResults.value)
    .filter(([_, data]) => data.status === 'not_found_on_drive')
    .map(([filename, data]) => ({ filename, expectedMd5: data.expectedMd5 }))
})

const currentSpeed = computed(() => {
  if (queueState.value !== 'uploading' || currentItemIndex.value === -1) return 0
  const activeItem = uploadQueue.value[currentItemIndex.value]
  return activeItem ? activeItem.speed : 0
})

const overallEta = computed(() => {
  if (queueState.value !== 'uploading' || currentSpeed.value <= 0) return null
  const remainingBytes = totalQueueSize.value - totalQueueUploadedBytes.value
  return Math.ceil(remainingBytes / currentSpeed.value)
})

// Template refs for file pickers
const fileInput = ref<HTMLInputElement | null>(null)
const addFileInput = ref<HTMLInputElement | null>(null)
const multipleFilesInput = ref<HTMLInputElement | null>(null)

function triggerFileInput() {
  fileInput.value?.click()
}

function triggerAddFileInput() {
  addFileInput.value?.click()
}

function triggerMultipleFilesInput() {
  multipleFilesInput.value?.click()
}
</script>

<template>
  <div class="w-full space-y-8">
    <!-- Hidden inputs placed at the root level to prevent event propagation bubbling bugs -->
    <input 
      type="file" 
      ref="fileInput" 
      class="hidden" 
      multiple 
      webkitdirectory
      directory
      @change="handleFileSelect" 
    />
    <input 
      type="file" 
      ref="multipleFilesInput" 
      class="hidden" 
      multiple 
      @change="handleFileSelect" 
    />
    <input 
      type="file" 
      ref="addFileInput" 
      class="hidden" 
      multiple 
      @change="handleFileSelect" 
    />
    
    <div class="w-full max-w-xl mx-auto space-y-6">
      <!-- Validation Loading -->
      <div v-if="isValidating" class="glass-card rounded-2xl p-12 text-center border border-white/5 flex flex-col items-center">
        <div class="h-10 w-10 border-4 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin"></div>
        <p class="text-slate-400 text-sm mt-4 font-medium">Validating your upload invitation...</p>
      </div>

      <!-- Invalid/Expired Token Error -->
      <div v-else-if="validationError" class="glass-card rounded-2xl p-8 border border-rose-500/10 text-center shadow-2xl">
        <span class="text-5xl">🚫</span>
        <h2 class="text-2xl font-bold text-rose-200 mt-4">Upload Link Invalid</h2>
        <p class="text-slate-400 text-sm mt-2 px-4 leading-relaxed">{{ validationError }}</p>
        <div class="mt-6">
          <a 
            href="/?admin=true" 
            class="inline-block bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-semibold px-4 py-2 rounded-xl transition cursor-pointer"
          >
            Go to Admin Panel
          </a>
        </div>
      </div>

      <!-- Active Uploader Queue Card -->
      <div v-else class="glass-card rounded-2xl border border-white/5 overflow-hidden shadow-2xl">
        <!-- Top info banner -->
        <div class="bg-gradient-to-r from-indigo-500/10 via-purple-500/10 to-pink-500/10 border-b border-white/5 px-6 py-5">
          <h2 class="text-lg font-bold text-white tracking-tight">{{ linkDetails?.name }}</h2>
          <div class="flex items-center justify-between mt-1.5 text-xs text-slate-400">
            <div class="flex items-center gap-1.5">
              <span>Destination:</span>
              <span class="bg-indigo-500/15 text-indigo-300 px-2 py-0.5 rounded font-medium border border-indigo-500/20">
                {{ explorerBreadcrumbs.map(b => b.name).join(' / ') || linkDetails?.folder_name }}
              </span>
            </div>
            <span v-if="linkDetails?.max_file_size_mb" class="text-[10px] text-slate-500">
              Max Size: {{ linkDetails.max_file_size_mb }}MB
            </span>
          </div>
        </div>

        <!-- Drop Zone (Only shown if uploader is idle) -->
        <div class="p-6 space-y-6">
          <div 
            v-if="queueState === 'idle' && uploadQueue.length === 0"
            @dragover="handleDragOver"
            @dragleave="handleDragLeave"
            @drop="handleDrop"
            :class="[
              'border-2 border-dashed rounded-2xl p-10 text-center flex flex-col items-center justify-center transition duration-200 cursor-pointer select-none group min-h-[220px]',
              isDragging 
                ? 'border-indigo-500 bg-indigo-500/5 scale-[1.01]' 
                : 'border-white/10 hover:border-indigo-500/40 hover:bg-white/[0.01]'
            ]"
            @click="triggerMultipleFilesInput"
          >
            <span class="text-4xl group-hover:scale-110 transition duration-200">📤</span>
            <h3 class="text-base font-bold text-white mt-4">Drag & drop files or folders here</h3>
            <p class="text-slate-400 text-xs mt-1">or select items to browse</p>
            
            <div class="mt-4 flex items-center gap-3">
              <button 
                @click.stop="triggerMultipleFilesInput"
                class="bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-4 py-2 rounded-xl transition cursor-pointer flex items-center gap-1.5"
              >
                📄 Select Files
              </button>
              <button 
                @click.stop="triggerFileInput"
                class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-semibold px-4 py-2 rounded-xl transition cursor-pointer flex items-center gap-1.5"
              >
                📁 Select Folder
              </button>
            </div>
            
            <div class="mt-5 flex flex-col gap-1 text-[10px] text-slate-500">
              <span>Supports recursive folder structure recreation</span>
              <span>Resumable: Partially uploaded files can be resumed below</span>
            </div>
          </div>

          <!-- Active Queue Manager View -->
          <div v-else class="space-y-6">
            <!-- Overall Queue Progress -->
            <div class="bg-slate-900/40 border border-white/5 rounded-2xl p-5 space-y-4">
              <div class="flex items-center justify-between">
                <div>
                  <h3 class="text-sm font-bold text-white">
                    <span v-if="queueState === 'uploading'">Uploading Queue</span>
                    <span v-else-if="queueState === 'paused'">Queue Paused</span>
                    <span v-else>Upload Queue Summary</span>
                  </h3>
                  <p class="text-slate-400 text-[10px] mt-0.5">
                    {{ uploadQueue.filter(i => i.status === 'success').length }} of {{ uploadQueue.length }} files uploaded ({{ formatBytes(totalQueueUploadedBytes) }} / {{ formatBytes(totalQueueSize) }})
                  </p>
                  <div v-if="queueState === 'uploading'" class="flex items-center gap-2 text-[10px] font-mono text-indigo-400 mt-1">
                    <span>⚡ {{ currentSpeed > 0 ? formatSpeed(currentSpeed) : 'Calculating speed...' }}</span>
                    <template v-if="currentSpeed > 0 && overallEta">
                      <span class="text-slate-700">•</span>
                      <span>{{ formatEta(overallEta) }}</span>
                    </template>
                  </div>
                </div>
                <span class="text-lg font-extrabold text-indigo-400 font-mono">{{ overallProgress }}%</span>
              </div>

              <!-- Overall progress bar -->
              <div class="w-full bg-slate-950 border border-white/5 rounded-full h-3 overflow-hidden">
                <div 
                  class="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 h-full rounded-full transition-all duration-300"
                  :style="{ width: `${overallProgress}%` }"
                ></div>
              </div>

              <!-- Queue Actions -->
              <div class="flex flex-wrap items-center gap-2 pt-2 border-t border-white/5">
                <button
                  v-if="queueState === 'uploading'"
                  @click="pauseQueue"
                  class="bg-amber-600/20 hover:bg-amber-500/35 border border-amber-500/20 text-amber-300 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer"
                >
                  ⏸ Pause Queue
                </button>
                <button
                  v-if="queueState === 'paused' || (queueState === 'idle' && pendingCount > 0)"
                  @click="resumeQueue"
                  class="bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/20 text-indigo-300 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer"
                >
                  ▶ Resume Queue
                </button>
                <button
                  @click="cancelAll"
                  class="bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/20 text-rose-400 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer"
                >
                  🚫 Cancel All
                </button>
                <button
                  @click="clearCompleted"
                  class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 hover:text-slate-200 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer ml-auto"
                >
                  🧹 Clear Finished
                </button>
              </div>
            </div>

            <!-- List of Queue Items -->
            <div class="space-y-2.5 max-h-[300px] overflow-y-auto pr-1.5 scrollbar-thin">
              <div 
                v-for="item in uploadQueue" 
                :key="item.id" 
                class="bg-slate-900/50 rounded-xl p-3.5 border border-white/5 flex flex-col gap-2.5"
              >
                <!-- Row Header -->
                <div class="flex items-start justify-between gap-3">
                  <div class="flex items-start gap-2.5 min-w-0">
                    <span class="text-xl shrink-0 mt-0.5">📄</span>
                    <div class="min-w-0">
                      <h4 class="text-xs font-semibold text-slate-200 truncate pr-2" :title="item.relativePath">
                        {{ item.relativePath || item.file.name }}
                      </h4>
                      <div class="flex items-center gap-3 text-[10px] text-slate-500 font-medium mt-0.5">
                        <span>{{ formatBytes(item.size) }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- Status badge & Actions -->
                  <div class="flex items-center gap-2 shrink-0">
                    <span 
                      :class="[
                        'text-[8px] uppercase tracking-wider font-bold border px-1.5 py-0.5 rounded',
                        item.status === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : '',
                        item.status === 'uploading' ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20 animate-pulse' : '',
                        item.status === 'queued' ? 'bg-slate-800 text-slate-400 border-slate-700' : '',
                        item.status === 'paused' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : '',
                        item.status === 'cancelled' ? 'bg-slate-700/55 text-slate-400 border-white/5' : '',
                        item.status === 'failed' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' : ''
                      ]"
                    >
                      {{ item.status }}
                    </span>

                    <button 
                      v-if="item.status === 'uploading' || item.status === 'queued' || item.status === 'paused'"
                      @click="cancelItem(item.id)"
                      class="text-[10px] text-rose-400 hover:text-rose-300 font-semibold p-1 hover:bg-rose-500/10 rounded cursor-pointer"
                      title="Cancel file upload"
                    >
                      ✕
                    </button>
                    <button 
                      v-if="item.status === 'cancelled' || item.status === 'failed'"
                      @click="retryItem(item.id)"
                      class="text-[10px] text-indigo-400 hover:text-indigo-300 font-semibold p-1 hover:bg-indigo-500/10 rounded cursor-pointer"
                    >
                      Retry
                    </button>
                  </div>
                </div>

                <!-- Error Display if Failed -->
                <p v-if="item.error" class="text-[9px] font-medium text-rose-400 bg-rose-500/10 border border-rose-500/10 rounded-lg px-2.5 py-1">
                  {{ item.error }}
                </p>

                <!-- Item Progress Bar -->
                <div v-if="item.status === 'uploading' || item.status === 'paused' || item.progress > 0" class="flex items-center gap-3">
                  <div class="flex-grow bg-slate-950 rounded-full h-1.5 border border-white/5 overflow-hidden">
                    <div 
                      class="bg-indigo-500 h-full rounded-full transition-all duration-300"
                      :style="{ width: `${item.progress}%` }"
                    ></div>
                  </div>
                  <span class="text-[10px] font-mono font-bold text-slate-400 shrink-0">{{ item.progress }}%</span>
                </div>
              </div>
            </div>

            <!-- Add More Files Trigger -->
            <div 
              @dragover="handleDragOver"
              @dragleave="handleDragLeave"
              @drop="handleDrop"
              :class="[
                'border border-dashed rounded-xl py-4 text-center cursor-pointer select-none transition border-white/10 hover:border-indigo-500/40 hover:bg-white/[0.01]',
                isDragging ? 'border-indigo-500 bg-indigo-500/5' : ''
              ]"
              @click="triggerAddFileInput"
            >
              <span class="text-xs font-semibold text-slate-400 group-hover:text-white">
                Drag and drop more files or click to add
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Incomplete Uploads List -->
      <div 
        v-if="!isValidating && !validationError && incompleteUploads.length > 0" 
        class="glass-card rounded-2xl border border-white/5 overflow-hidden shadow-2xl p-6 space-y-4"
      >
        <div>
          <h3 class="text-sm font-bold text-white flex items-center gap-2">
            <span>⏳</span> Unfinished Upload Sessions
          </h3>
          <p class="text-slate-400 text-[10px] mt-0.5">
            Partially uploaded sessions found. Re-select the local file to resume from the exact byte offset.
          </p>
        </div>

        <div class="space-y-2">
          <div 
            v-for="session in incompleteUploads" 
            :key="session.session_id"
            class="bg-slate-900/50 rounded-xl p-3.5 border border-white/5 flex items-center justify-between gap-4"
          >
            <div class="min-w-0 flex-grow space-y-1">
              <h4 class="text-xs font-semibold text-slate-200 truncate">{{ session.filename }}</h4>
              <div class="flex items-center gap-3 text-[10px] text-slate-500">
                <span>Total: {{ formatBytes(session.filesize) }}</span>
                <span>Uploaded: {{ formatBytes(session.bytes_uploaded) }}</span>
                <span class="font-bold text-indigo-400">
                  {{ Math.round((session.bytes_uploaded / session.filesize) * 100) }}% complete
                </span>
              </div>
            </div>

            <!-- Action buttons -->
            <div class="flex items-center gap-2 shrink-0">
              <button
                @click="triggerResume(session)"
                class="bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/20 text-indigo-300 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer"
              >
                Resume
              </button>
              <button
                @click="deleteIncompleteSession(session.session_id)"
                class="bg-rose-500/10 hover:bg-rose-500/25 border border-rose-500/20 text-rose-400 text-[10px] font-semibold px-3 py-1.5 rounded-lg transition cursor-pointer"
                title="Discard uncompleted upload"
              >
                🗑️
              </button>
            </div>
          </div>
        </div>

        <!-- Hidden input for selecting the file to resume -->
        <input 
          type="file" 
          ref="resumeFileInput" 
          class="hidden" 
          @change="handleResumeFileSelect" 
        />
      </div>
    </div>

    <!-- Files Explorer Section (if allow_view is true) -->
    <div v-if="!isValidating && !validationError && linkDetails?.allow_view" class="w-full max-w-4xl mx-auto glass-card rounded-2xl border border-white/5 overflow-hidden shadow-2xl p-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4 pb-4 border-b border-white/5">
        <div>
          <h3 class="text-lg font-bold text-white flex items-center gap-2">
            <span>📁</span> Folder Directory
          </h3>
          <p class="text-slate-400 text-xs mt-1">Navigate folders, inspect file checksums, and delete items.</p>
        </div>

        <!-- Checksum actions -->
        <div class="flex items-center gap-2.5">
          <button
            @click="triggerChecksumFilePicker"
            class="bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/20 text-indigo-300 text-xs font-semibold px-3.5 py-2 rounded-lg transition cursor-pointer flex items-center gap-1"
          >
            🔍 Verify MD5 sum File
          </button>
          
          <button
            @click="downloadMd5Manifest"
            class="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-semibold px-3.5 py-2 rounded-lg transition cursor-pointer"
          >
            💾 Download Checksums (.md5)
          </button>

          <!-- Hidden Checksum picker -->
          <input 
            type="file" 
            ref="checksumFileInput" 
            class="hidden" 
            accept=".md5,.txt"
            @change="handleChecksumFileLoad" 
          />
        </div>
      </div>

      <!-- Checksum Status Summary -->
      <div v-if="showChecksumVerification" class="bg-indigo-950/20 border border-indigo-500/20 rounded-xl p-4 mb-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-lg">📋</span>
            <span class="text-xs font-bold text-indigo-200">
              Verifying against: <span class="underline">{{ checksumFilename }}</span>
            </span>
          </div>
          <button 
            @click="clearChecksumVerification" 
            class="text-[10px] text-indigo-400 hover:text-indigo-300 font-semibold cursor-pointer uppercase tracking-wider"
          >
            Clear Verification
          </button>
        </div>

        <!-- Missing Files warning -->
        <div v-if="missingVerificationFiles.length > 0" class="text-xs border-t border-indigo-500/10 pt-2.5">
          <h4 class="font-bold text-amber-300 flex items-center gap-1">
            <span>⚠️</span> Missing Files (Found in MD5 file, not in Drive):
          </h4>
          <ul class="list-disc list-inside mt-1.5 space-y-1 pl-1 text-[11px] text-slate-300 max-h-[120px] overflow-y-auto scrollbar-thin">
            <li v-for="file in missingVerificationFiles" :key="file.filename" class="truncate font-mono">
              {{ file.filename }} <span class="text-slate-500">({{ file.expectedMd5 }})</span>
            </li>
          </ul>
        </div>
        <div v-else class="text-xs border-t border-indigo-500/10 pt-2 text-emerald-400 font-semibold flex items-center gap-1.5">
          <span>✓</span> All expected files in MD5 sum manifest are present in this directory!
        </div>
      </div>

      <!-- Navigation Breadcrumbs -->
      <div class="flex items-center gap-1.5 py-2.5 px-3 bg-slate-900/40 rounded-xl text-xs border border-white/5 overflow-x-auto scrollbar-thin">
        <span 
          v-for="(bc, index) in explorerBreadcrumbs" 
          :key="bc.id"
          class="flex items-center gap-1.5 shrink-0"
        >
          <button 
            @click="fetchFolderContents(bc.id)" 
            class="text-indigo-400 hover:text-indigo-300 font-semibold cursor-pointer"
          >
            {{ bc.name }}
          </button>
          <span v-if="index < explorerBreadcrumbs.length - 1" class="text-slate-600">/</span>
        </span>
      </div>

      <!-- Directories & Files list -->
      <div class="mt-4 min-h-[200px] relative">
        <div v-if="explorerLoading" class="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px] z-10 flex flex-col items-center justify-center text-slate-400 rounded-xl">
          <div class="h-8 w-8 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin"></div>
          <p class="text-xs mt-3">Fetching directory...</p>
        </div>

        <div v-if="explorerError" class="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-rose-300 text-xs font-semibold">
          {{ explorerError }}
        </div>

        <div v-else-if="explorerFiles.length === 0" class="flex flex-col items-center justify-center py-16 text-slate-500 border border-dashed border-white/5 rounded-xl">
          <span class="text-3xl mb-1">📁</span>
          <p class="text-sm font-semibold">This directory is empty</p>
          <p class="text-xs">Drag and drop files to add contents.</p>
        </div>

        <div v-else class="space-y-2 max-h-[500px] overflow-y-auto pr-1.5 scrollbar-thin">
          <div 
            v-for="item in explorerFiles" 
            :key="item.id"
            :class="[
              'flex flex-col md:flex-row md:items-center justify-between p-3.5 rounded-xl border border-white/5 gap-3 transition',
              isFolder(item.mimeType) 
                ? 'bg-indigo-950/20 hover:bg-indigo-950/40 border-indigo-500/10 cursor-pointer select-none' 
                : 'bg-slate-900/60 hover:bg-slate-900'
            ]"
            @click="isFolder(item.mimeType) && fetchFolderContents(item.id)"
          >
            <!-- Left: Icon, Name, and Checksum details -->
            <div class="flex items-start gap-3 flex-grow min-w-0">
              <span class="text-2xl mt-0.5">{{ isFolder(item.mimeType) ? '📁' : '📄' }}</span>
              <div class="space-y-1 min-w-0 flex-grow">
                <div class="flex items-center gap-2 flex-wrap">
                  <h4 class="text-sm font-semibold text-slate-200 truncate pr-2">{{ item.name }}</h4>
                  
                  <!-- Checksum Verification Badges -->
                  <template v-if="showChecksumVerification && !isFolder(item.mimeType)">
                    <span 
                      v-if="getVerificationResult(item.name)?.status === 'verified'"
                      class="text-[8px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded uppercase tracking-wider"
                    >
                      ✓ Match
                    </span>
                    <span 
                      v-else-if="getVerificationResult(item.name)?.status === 'mismatch'"
                      class="text-[8px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20 px-1.5 py-0.5 rounded uppercase tracking-wider"
                      :title="`Expected: ${getVerificationResult(item.name)?.expectedMd5}\nActual: ${getVerificationResult(item.name)?.actualMd5}`"
                    >
                      ⚠ MD5 Mismatch
                    </span>
                    <span 
                      v-else
                      class="text-[8px] font-bold bg-slate-800 text-slate-400 border border-white/5 px-1.5 py-0.5 rounded uppercase tracking-wider"
                    >
                      Untracked
                    </span>
                  </template>
                </div>
                
                <!-- Display Checksum for files -->
                <div v-if="!isFolder(item.mimeType) && item.md5Checksum" class="flex items-center gap-1.5 text-[10px] text-slate-500">
                  <span class="font-mono bg-black/25 px-1.5 py-0.5 rounded select-all font-semibold">
                    MD5: {{ item.md5Checksum }}
                  </span>
                  <button 
                    @click.stop="copyChecksum(item.md5Checksum)"
                    class="text-[9px] hover:text-white uppercase tracking-wider font-extrabold cursor-pointer"
                    title="Copy MD5 to Clipboard"
                  >
                    Copy
                  </button>
                </div>
              </div>
            </div>

            <!-- Right: Size, Date, Actions -->
            <div class="flex items-center justify-between md:justify-end gap-6 shrink-0 border-t border-white/5 md:border-t-0 pt-2 md:pt-0">
              <div class="flex items-center gap-4 text-right text-[10px] text-slate-400">
                <span v-if="!isFolder(item.mimeType) && item.size">{{ formatBytes(item.size) }}</span>
                <span v-else class="text-indigo-400 font-semibold uppercase tracking-wider">Folder</span>
                
                <span v-if="item.createdTime">{{ new Date(item.createdTime).toLocaleDateString() }}</span>
              </div>

              <!-- Delete Button -->
              <div v-if="linkDetails?.allow_delete && !isFolder(item.mimeType)" class="flex justify-end">
                <button
                  @click.stop="deleteFile(item.id, item.name)"
                  class="bg-rose-500/10 hover:bg-rose-500/25 border border-rose-500/20 text-rose-400 text-xs font-semibold p-2 rounded-xl transition cursor-pointer"
                  title="Delete file"
                >
                  🗑️
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
