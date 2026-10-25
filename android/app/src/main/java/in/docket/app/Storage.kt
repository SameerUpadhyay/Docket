package `in`.docket.app

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.UUID

class NoticeStore(private val context: Context) {
    val session = AccountSession(context)
    private val vault = LocalVault(context)
    val preferences = context.getSharedPreferences("workspace", Context.MODE_PRIVATE)
    val connected: Boolean get() = preferences.getBoolean("api_mode", false)
    val server: String get() = preferences.getString("server", BuildConfig.API_ORIGIN)!!
    private fun dataFile(api: Boolean) = AtomicFile(File(context.filesDir, if (api) "api-cache.enc" else "device-notices.enc"))
    fun templates(): List<Notice> = JSONArray(context.assets.open("demo_notices.json").bufferedReader().use { it.readText() }).objects().map(::Notice)
    @Synchronized fun read(api: Boolean = connected): List<Notice> {
        val file = dataFile(api)
        if (!file.baseFile.exists() && !api) {
            val legacy = File(context.filesDir, "device-notices.json")
            if (legacy.exists()) {
                val bytes = legacy.readBytes()
                val parsed = JSONArray(String(bytes)).objects().map(::Notice)
                parsed.flatMap { it.documents }.forEach { doc ->
                    evidenceFile(doc)?.let { evidence ->
                        val content = evidence.readBytes()
                        if (content.size < 4 || String(content.copyOfRange(0, 4)) != "DKT1") vault.write("evidence/${evidence.name}", content)
                    }
                }
                vault.write("device-notices.enc", bytes)
                legacy.delete()
            }
        }
        if (!file.baseFile.exists()) return if (api) emptyList() else templates()
        return JSONArray(String(vault.decrypt(file.openRead().use { it.readBytes() }))).objects().map(::Notice).onEach { notice ->
            if (!notice.isDemo && !notice.quarantined && notice.json.text("analysis_mode") == "android-local-playbook") {
                val (initialTier, score) = RuleEngine.risk(notice.law, notice.amount, notice.days ?: 999, notice.triage?.optBoolean("has_criminal_or_arrest_clause") == true, notice.triage?.optBoolean("has_bank_freeze_or_eway_block_threat") == true)
                val unknown = notice.title == "Unclassified notice"
                notice.json.put("severity", if (unknown && initialTier == "GREEN") "AMBER" else initialTier)
                notice.json.put("deterministic_risk_score", if (unknown) score.coerceAtLeast(32) else score)
            }
        }
    }
    @Synchronized fun save(notices: List<Notice>, api: Boolean = connected) {
        val file = dataFile(api)
        val stream = file.startWrite()
        try { stream.write(vault.encrypt(JSONArray(notices.map { it.json }).toString().toByteArray())); file.finishWrite(stream) }
        catch (e: Exception) { file.failWrite(stream); throw e }
    }
    fun mode(api: Boolean, url: String = server) { preferences.edit().putBoolean("api_mode", api).putString("server", url).commit() }
    fun selectedFile(uri: Uri): Pair<String, ByteArray> {
        val name = if (uri.scheme == "file") File(uri.path!!).name else context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null } ?: "notice.txt"
        val bytes = context.contentResolver.openInputStream(uri)?.use { stream ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var total = 0
            while (true) { val count = stream.read(buffer); if (count < 0) break; total += count; require(total <= 10 * 1024 * 1024) { "The file exceeds the 10 MB limit." }; output.write(buffer, 0, count) }
            output.toByteArray()
        } ?: error("Could not open the selected file.")
        require(bytes.isNotEmpty()) { "The selected file is empty." }
        return name.substringAfterLast('/').substringAfterLast('\\') to bytes
    }
    fun isCameraDocument(uri: Uri): Boolean = uri.scheme == "file" && runCatching { File(uri.path!!).canonicalFile.parentFile == File(context.cacheDir, "captured-notices").canonicalFile }.getOrDefault(false)
    fun discardCameraDocument(uri: Uri?) { if (uri != null && isCameraDocument(uri)) File(uri.path!!).delete() }
    fun retainCameraOriginal(id: String, bytes: ByteArray) { require(id.matches(Regex("[A-Za-z0-9_-]{1,128}"))); File(context.filesDir, "capture-originals").mkdirs(); vault.write("capture-originals/$id.pdf.enc", bytes) }
    fun cameraOriginal(id: String): ByteArray { require(id.matches(Regex("[A-Za-z0-9_-]{1,128}"))); return vault.decrypt(File(context.filesDir, "capture-originals/$id.pdf.enc").readBytes()) }
    fun attach(notice: Notice, docId: String, name: String, bytes: ByteArray): Notice {
        val extension = name.substringAfterLast('.', "").lowercase()
        require(extension in setOf("pdf", "txt", "png", "jpg", "jpeg", "csv", "xlsx")) { "Choose PDF, image, TXT, CSV or XLSX evidence." }
        val updated = notice.duplicate()
        val doc = updated.documents.firstOrNull { it.text("doc_id") == docId } ?: error("Evidence item not found.")
        val directory = File(context.filesDir, "evidence").apply { mkdirs() }
        val filename = "${UUID.randomUUID()}.$extension"
        File(directory, filename).writeBytes(vault.encrypt(bytes))
        doc.put("attachment_name", name).put("local_file", filename).put("is_collected", true)
        advance(updated)
        return updated
    }
    fun evidenceFile(doc: JSONObject): File? = doc.text("local_file").takeIf { it.matches(Regex("[a-fA-F0-9-]+\\.[a-z0-9]+")) }?.let { File(context.filesDir, "evidence/$it").takeIf(File::exists) }
    fun evidenceBytes(doc: JSONObject): ByteArray? = evidenceFile(doc)?.let { vault.decrypt(it.readBytes()) }
    fun clearPrivateCache() { session.clear(); File(context.filesDir, "api-cache.enc").delete() }
    fun advance(notice: Notice) {
        if (notice.state == "CA_ESCALATED") return
        notice.json.put("state", when { notice.documents.isNotEmpty() && notice.collected == notice.documents.size -> "DRAFT_READY"; notice.collected > 0 -> "DOCS_GATHERING"; else -> "TRIAGED" })
    }
}

class ApiFailure(val status: Int, message: String) : IllegalStateException(message)

class ApiClient(base: String, private val token: String = "", private val workspace: String = "") {
    private val root = base.trim().trimEnd('/').also { value ->
        val uri = URI(value)
        require(uri.scheme in listOf("https", "http") && !uri.host.isNullOrBlank() && uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path.orEmpty() in listOf("", "/")) { "Use a server origin such as http://127.0.0.1:8000 or an HTTPS host." }
        require(uri.scheme == "https" || uri.host in listOf("localhost", "127.0.0.1", "10.0.2.2")) { "HTTP is restricted to local development addresses. Use HTTPS for a remote service." }
    }
    private fun connection(path: String, method: String): HttpURLConnection = (URL("$root/api$path").openConnection() as HttpURLConnection).apply { requestMethod = method; connectTimeout = 8000; readTimeout = 120000; instanceFollowRedirects = false; setRequestProperty("X-Docket-Request", "1"); if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token"); if (workspace.isNotBlank()) setRequestProperty("X-Workspace-ID", workspace) }
    private fun result(connection: HttpURLConnection): ByteArray {
        try {
            if (connection.responseCode !in 200..299) {
                val message = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw ApiFailure(connection.responseCode, runCatching { val detail = JSONObject(message); detail.optJSONArray("detail")?.optJSONObject(0)?.text("msg") ?: detail.text("detail", "The service could not complete this request.") }.getOrDefault("Service returned ${connection.responseCode}").take(300))
            }
            return connection.inputStream.use { it.readBytes() }
        } finally { connection.disconnect() }
    }
    fun json(path: String, method: String = "GET", body: JSONObject? = null): String {
        val conn = connection(path, method)
        if (body != null) { conn.doOutput = true; conn.setRequestProperty("Content-Type", "application/json"); conn.outputStream.use { it.write(body.toString().toByteArray()) } }
        return String(result(conn))
    }
    fun notices(): List<Notice> = JSONArray(String(result(connection("/notices", "GET")))).objects().map(::Notice)
    fun patch(path: String, body: JSONObject): Notice {
        val conn = connection(path, "PATCH"); conn.doOutput = true; conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(body.toString().toByteArray()) }
        return Notice(JSONObject(String(result(conn))))
    }
    fun uploadJson(path: String, name: String, bytes: ByteArray, fields: Map<String, String> = emptyMap()): JSONObject {
        val boundary = "Docket${UUID.randomUUID()}"
        val conn = connection(path, "POST"); conn.doOutput = true
        conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        val safeName = name.replace(Regex("[\\r\\n\"]"), "_")
        conn.outputStream.use { stream ->
            fields.forEach { (key, value) -> stream.write("--$boundary\r\nContent-Disposition: form-data; name=\"$key\"\r\n\r\n$value\r\n".toByteArray()) }
            stream.write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"$safeName\"\r\nContent-Type: application/octet-stream\r\n\r\n".toByteArray())
            stream.write(bytes); stream.write("\r\n--$boundary--\r\n".toByteArray())
        }
        return JSONObject(String(result(conn)))
    }
    fun upload(path: String, name: String, bytes: ByteArray, fields: Map<String, String> = emptyMap()): Notice = Notice(uploadJson(path, name, bytes, fields))
    fun download(path: String, method: String = "GET"): ByteArray = result(connection(path, method))
}
