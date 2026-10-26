package `in`.docket.app

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class DocketViewModel(application: Application) : AndroidViewModel(application) {
    val store = NoticeStore(application)
    private val _notices = MutableStateFlow(if (store.connected) emptyList() else runCatching { store.read() }.getOrElse { store.templates() })
    val notices = _notices.asStateFlow()
    private val _busy = MutableStateFlow(false)
    val busy = _busy.asStateFlow()
    private val _reading = MutableStateFlow("")
    val reading = _reading.asStateFlow()
    private val _ocrPreview = MutableStateFlow<JSONObject?>(null)
    val ocrPreview = _ocrPreview.asStateFlow()
    private var pendingReading: Pair<String, DocumentReader.Extraction>? = null
    fun clearOcrPreview() { _ocrPreview.value = null }
    private fun readingKey(bytes: ByteArray, language: String) = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) } + language
    fun previewDocument(uri: Uri) = task {
        val language = "auto"
        val file = store.selectedFile(uri)
        _reading.value = "Reading all pages before suggesting dates…"
        _ocrPreview.value = if (store.connected) api().uploadJson("/ocr/ingest-and-triage", file.first, file.second, mapOf("ocr_language" to language)) else {
            val extraction = DocumentReader(getApplication()).read(uri, file.first, file.second, language) { page, total -> _reading.value = "Reading page $page of $total…" }
            pendingReading = readingKey(file.second, language) to extraction
            OcrSuggestions.preview(extraction)
        }
        _message.value = "Document read. Confirm the suggested dates and response period against the original."
    }
    private val _message = MutableStateFlow<String?>(null)
    val message = _message.asStateFlow()
    private val _apiMode = MutableStateFlow(store.connected)
    val apiMode = _apiMode.asStateFlow()
    private val _account = MutableStateFlow<JSONObject?>(null)
    val account = _account.asStateFlow()
    private val _demo = MutableStateFlow(false)
    val demo = _demo.asStateFlow()
    fun api() = ApiClient(store.server, store.session.token, store.session.workspace)
    init { if (store.session.token.isNotBlank()) restoreAccount() }
    private fun acceptAccount(info: JSONObject) {
        val value = store.session.value ?: error("Sign in again.")
        val workspace = info.getJSONObject("workspace")
        value.put("workspace_id", workspace.getString("id")).put("role", workspace.getString("role"))
        store.session.save(value)
        _account.value = info
    }
    fun restoreAccount() = task {
        store.mode(true, store.session.value?.text("origin", store.server) ?: store.server)
        acceptAccount(JSONObject(api().json("/auth/me")))
        val loaded = api().notices(); store.save(loaded, true); _notices.value = loaded; _apiMode.value = true
        ReminderScheduler.reschedule(getApplication(), loaded)
    }
    fun signIn(url: String, email: String, password: String) = task {
        val credentials = JSONObject().put("email", email).put("password", password)
        val result = JSONObject(ApiClient(url).json("/auth/login", "POST", credentials))
        store.clearPrivateCache(); store.mode(true, url.trim().trimEnd('/'))
        store.session.save(result.put("origin", store.server))
        acceptAccount(JSONObject(api().json("/auth/me")))
        val loaded = api().notices(); store.save(loaded, true); _notices.value = loaded; _apiMode.value = true; _demo.value = false
        ReminderScheduler.reschedule(getApplication(), loaded)
    }
    fun exploreDemo() { store.mode(false); _notices.value = store.templates(); _apiMode.value = false; _demo.value = true; ReminderScheduler.reschedule(getApplication(), emptyList()) }
    fun signOut(all: Boolean = false) = task {
        val revoked = runCatching { if (store.session.token.isNotBlank()) api().json(if (all) "/auth/logout-all" else "/auth/logout", "POST") }.isSuccess
        store.clearPrivateCache(); pendingReading = null; _ocrPreview.value = null; store.mode(false); _account.value = null; _demo.value = false; _notices.value = emptyList(); _apiMode.value = false
        ReminderScheduler.reschedule(getApplication(), emptyList())
        _message.value = if (revoked) "Signed out. The device cache was cleared." else "Device signed out. Server revocation could not be confirmed; reset your password to revoke other sessions."
    }
    fun accountAction(path: String, method: String = "POST", body: JSONObject? = null, after: (String) -> Unit = {}) = task {
        val result = api().json(path, method, body)
        if (path == "/account/profile" || path == "/workspace/invitations/accept") acceptAccount(JSONObject(api().json("/auth/me")))
        withContext(Dispatchers.Main) { after(result) }
    }
    fun selectWorkspace(id: String) = task {
        val saved = store.session.value ?: error("Sign in again.")
        store.save(emptyList(), true); _notices.value = emptyList()
        store.session.save(saved.put("workspace_id", id))
        acceptAccount(JSONObject(api().json("/auth/me")))
        val loaded = api().notices(); store.save(loaded, true); _notices.value = loaded
        ReminderScheduler.reschedule(getApplication(), loaded)
    }
    fun removeAccount(password: String) = task {
        api().json("/account", "DELETE", JSONObject().put("password", password))
        store.clearPrivateCache(); pendingReading = null; _ocrPreview.value = null; store.mode(false); _account.value = null; _demo.value = false; _notices.value = emptyList(); _apiMode.value = false
        ReminderScheduler.reschedule(getApplication(), emptyList()); _message.value = "Account and owned business records deleted."
    }
    fun caseAction(id: String, suffix: String, method: String, body: JSONObject) = task { commit(Notice(JSONObject(api().json("/notices/$id/$suffix", method, body)))) }
    fun attachProof(id: String, uri: Uri) = task {
        val (name, bytes) = store.selectedFile(uri)
        commit(api().upload("/notices/$id/acknowledgement", name, bytes))
        _message.value = "Submission receipt attached. Record the official acknowledgement next."
    }
    fun deleteCase(id: String) = task { api().json("/notices/$id", "DELETE"); val next = _notices.value.filterNot { it.id == id }; store.save(next); _notices.value = next; ReminderScheduler.reschedule(getApplication(), next); _message.value = "Case and live records deleted." }
    fun exportAccount(uri: Uri) = task {
        val bytes = api().download("/account/export")
        getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("Could not save account export.")
        _message.value = "Account export saved. Review it before sharing."
    }
    fun dismissMessage() { _message.value = null }
    fun notify(message: String) { _message.value = message }
    private fun task(block: suspend () -> Unit) {
        if (_busy.value) return
        _busy.value = true
        viewModelScope.launch { try { withContext(Dispatchers.IO) { block() } } catch (e: Exception) {
            if (e is ApiFailure && (e.status == 401 || (e.status == 403 && e.message.orEmpty().startsWith("Workspace access was revoked")))) {
                store.clearPrivateCache(); pendingReading = null; _ocrPreview.value = null; store.mode(false); _account.value = null; _demo.value = false; _notices.value = emptyList(); _apiMode.value = false
                ReminderScheduler.reschedule(getApplication(), emptyList())
            }
            _message.value = e.message ?: "The action could not be completed. Try again." } finally { _busy.value = false; _reading.value = "" } }
    }
    private fun commit(notice: Notice) {
        val next = listOf(notice) + _notices.value.filterNot { it.id == notice.id }
        store.save(next); _notices.value = next
        ReminderScheduler.reschedule(getApplication(), next)
    }
    private fun editable(id: String): Notice = _notices.value.first { it.id == id }.also { require(!it.quarantined && !it.closed && (!store.connected || store.session.role != "reviewer")) { "This case is read-only." } }
    fun toggle(id: String, docId: String, collected: Boolean) = task {
        val current = editable(id)
        val updated = if (store.connected) api().patch("/notices/$id/checklist/$docId", JSONObject().put("is_collected", collected)) else current.duplicate().apply { documents.first { it.text("doc_id") == docId }.put("is_collected", collected); store.advance(this) }
        commit(updated)
    }
    fun saveDraft(id: String, text: String, after: () -> Unit = {}) = task {
        val current = editable(id)
        require(text.length <= 50000) { "The draft exceeds the 50,000 character limit." }
        commit(if (store.connected) api().patch("/notices/$id/draft", JSONObject().put("draft_reply", text).put("expected_revision", current.json.optInt("revision"))) else current.duplicate().apply { json.put("draft_reply", text) })
        _message.value = "Draft saved. Nothing has been submitted."
        withContext(Dispatchers.Main) { after() }
    }
    fun state(id: String, state: String) = task {
        val current = editable(id)
        commit(if (store.connected) api().patch("/notices/$id/state", JSONObject().put("state", state)) else current.duplicate().apply { json.put("state", state) })
        _message.value = if (state == "CA_ESCALATED") "Marked for advisor review. Nothing has been sent." else "Case marked closed. No legal response has been filed."
    }
    fun attach(id: String, docId: String, uri: Uri) = task {
        val current = editable(id)
        val (name, bytes) = store.selectedFile(uri)
        commit(if (store.connected) api().upload("/notices/$id/evidence/$docId", name, bytes) else store.attach(current, docId, name, bytes))
        _message.value = "Evidence attached to the case."
    }
    fun analyze(uri: Uri, issue: String, service: String, window: Int, sunday: Boolean, after: (String) -> Unit) = task {
        val language = "auto"
        RuleEngine.limitation(issue, service, window, sunday)
        val file = store.selectedFile(uri)
        _reading.value = "Reading and checking the complete document…"
        val result = if (store.connected) api().upload("/notices/analyze", file.first, file.second, mapOf("date_of_issue" to issue, "date_of_service" to service, "window_days" to window.toString(), "ocr_language" to language, "confirm_office_rollover" to sunday.toString())) else {
            val extraction = pendingReading?.takeIf { it.first == readingKey(file.second, language) }?.second ?: DocumentReader(getApplication()).read(uri, file.first, file.second, language) { page, total -> _reading.value = "Reading page $page of $total…" }
            RuleEngine.analyze(OcrSuggestions.normalize(extraction.text), extraction.qr, issue, service, window, sunday, store.templates(), file.first).apply { json.put("ocr_report", extraction.quality); if (store.isCameraDocument(uri)) { store.retainCameraOriginal(id, file.second); json.put("source_capture", true) } else json.put("source_uri", uri.toString()) }
        }
        if (!store.connected) result.json.put("source_sha256", java.security.MessageDigest.getInstance("SHA-256").digest(file.second).joinToString("") { "%02x".format(it) })
        commit(result)
        withContext(Dispatchers.Main) { after(result.id) }
    }
    fun connect(url: String) = task {
        require(url.trim().trimEnd('/') == store.server && store.session.token.isNotBlank()) { "Sign in to that server from the welcome screen." }
        val loaded = api().notices(); store.save(loaded, true); _notices.value = loaded; _apiMode.value = true
    }
    fun deviceMode() = task {
        require(store.session.token.isBlank()) { "Sign out before switching to the sample workspace." }
        store.mode(false); _notices.value = store.read(false); _apiMode.value = false
        ReminderScheduler.reschedule(getApplication(), _notices.value)
        _message.value = "Using the private device workspace."
    }
    fun refresh() = task {
        if (store.connected) { val loaded = api().notices(); store.save(loaded, true); _notices.value = loaded; ReminderScheduler.reschedule(getApplication(), loaded) }
        else _notices.value = store.read(false)
    }
    fun applyIncomingNotices(workspace: String, loaded: List<Notice>) {
        // A delayed response must never replace a different business's screen.
        if (_account.value != null && store.session.workspace == workspace) _notices.value = loaded
    }
    fun export(notice: Notice, uri: Uri, type: String) = task {
        val bytes = if (store.connected) api().download(if (type == "zip") "/notices/${notice.id}/export-ca-brief" else if (type == "reply") "/notices/${notice.id}/reply.pdf" else "/notices/${notice.id}/report.pdf", if (type == "zip") "POST" else "GET") else CaseExporter(getApplication(), store).bytes(notice, type)
        getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("Could not write the export.")
        _message.value = "Export saved. No document has been sent."
    }
    fun mailFilter(address: String, uri: Uri) = task {
        val xml = MailRules.generate(address)
        getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(xml.toByteArray()) } ?: error("Could not save the mail rule.")
        _message.value = "Gmail rule saved. Import and review it in Gmail settings."
    }
}
