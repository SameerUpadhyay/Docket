package `in`.docket.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

data class CaptureState(
    val pages: List<CapturedPage> = emptyList(),
    val busy: Boolean = false,
    val message: String = "",
    val retake: Int? = null,
    val rejected: PhotoQuality? = null,
    val awaitingRetake: Boolean = false
)

class CaptureViewModel(application: Application) : AndroidViewModel(application) {
    private val root = File(application.cacheDir, "notice-capture")
    private var directory = File(root, UUID.randomUUID().toString())
    private var generation = 0
    private val _state = MutableStateFlow(CaptureState())
    val state = _state.asStateFlow()
    init {
        // Cache is private and excluded from backup. Clean abandoned sessions;
        // no camera document is published to the device gallery.
        viewModelScope.launch(Dispatchers.IO) { listOf(root,File(application.cacheDir,"captured-notices")).forEach { folder -> folder.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 24 * 60 * 60 * 1000L }?.forEach { it.deleteRecursively() } } }
    }
    fun newPhoto(): File? {
        if (_state.value.busy || _state.value.rejected != null || (_state.value.pages.size >= CaptureDocuments.MAX_PAGES && _state.value.retake == null)) return null
        directory.mkdirs()
        _state.value = _state.value.copy(busy = true, message = "Capturing…")
        return File(directory, "${UUID.randomUUID()}.jpg")
    }
    fun captured(file: File) {
        if (file.parentFile != directory) { file.delete(); return }
        val version = generation; val replacement = _state.value.retake
        viewModelScope.launch {
            try {
                val (page, quality) = withContext(Dispatchers.Default) { CaptureDocuments.prepare(file) }
                if (version != generation) { file.delete(); return@launch }
                if (page == null) { withContext(Dispatchers.IO) { file.delete() }; _state.value = _state.value.copy(busy = false, rejected = quality, awaitingRetake = true, message = "Retake this page") }
                else {
                    val next = _state.value.pages.toMutableList()
                    if (replacement != null && replacement in next.indices) { val old = next[replacement]; next[replacement] = page; withContext(Dispatchers.IO) { old.file.delete(); old.thumbnail.delete() } } else next += page
                    _state.value = CaptureState(pages = next, message = "Page ${if (replacement == null) next.size else replacement + 1} saved · capture the next page or submit")
                }
            } catch (e: Exception) { file.delete(); if (version == generation) { val reason = e.message ?: "Could not read this photo. Retake it."; _state.value = _state.value.copy(busy = false, rejected = PhotoQuality(false,reason,0.0,0.0), awaitingRetake = true, message = reason) } }
        }
    }
    fun failed(file: File?, message: String) { file?.delete(); if (file != null && file.parentFile != directory) return; _state.value = _state.value.copy(busy = false, message = message) }
    fun dismissRetake() { _state.value = _state.value.copy(rejected = null, message = "Hold steady and keep the complete page in view.") }
    fun retake(index: Int) { if (!_state.value.busy && index in _state.value.pages.indices) _state.value = _state.value.copy(retake = index, message = "Retaking page ${index + 1}. The previous photo stays until its replacement is clear.") }
    fun cancelRetake() { _state.value = _state.value.copy(retake = null, rejected = null, awaitingRetake = false, message = "Previous page kept") }
    fun skipFailedPhoto() { if (!_state.value.busy && _state.value.retake == null) _state.value = _state.value.copy(rejected = null, awaitingRetake = false, message = "Failed photo discarded. Check that all required pages are included.") }
    fun remove(index: Int) {
        if (_state.value.busy || index !in _state.value.pages.indices) return
        val next = _state.value.pages.toMutableList(); val removed = next.removeAt(index)
        _state.value = CaptureState(pages = next, message = "Page removed")
        viewModelScope.launch(Dispatchers.IO) { removed.file.delete(); removed.thumbnail.delete() }
    }
    fun move(index: Int, offset: Int) {
        if (_state.value.busy || _state.value.retake != null) return
        val next = _state.value.pages.toMutableList(); val destination = index + offset
        if (index !in next.indices || destination !in next.indices) return
        java.util.Collections.swap(next, index, destination)
        _state.value = _state.value.copy(pages = next, message = "Page order updated")
    }
    fun submit(ready: (File) -> Unit) {
        val snapshot = _state.value
        if (snapshot.busy || snapshot.pages.isEmpty() || snapshot.rejected != null || snapshot.retake != null || snapshot.awaitingRetake) return
        val version = generation; val destination = File(File(getApplication<Application>().cacheDir, "captured-notices").apply { mkdirs() }, "notice-${UUID.randomUUID()}.pdf")
        _state.value = snapshot.copy(busy = true, message = "Preparing one document…")
        viewModelScope.launch {
            try {
                val pdf = withContext(Dispatchers.IO) { CaptureDocuments.writePdf(snapshot.pages, destination) }
                if (version == generation) { _state.value = _state.value.copy(busy = false, message = "Document ready"); ready(pdf) } else pdf.delete()
            } catch (e: Exception) { if (version == generation) _state.value = _state.value.copy(busy = false, message = e.message ?: "Could not prepare the document. Your photos are still available.") }
        }
    }
    fun clear() {
        generation++; val old = directory; directory = File(root, UUID.randomUUID().toString()); _state.value = CaptureState()
        viewModelScope.launch(Dispatchers.IO) { old.deleteRecursively() }
    }
    override fun onCleared() { directory.deleteRecursively(); super.onCleared() }
}
