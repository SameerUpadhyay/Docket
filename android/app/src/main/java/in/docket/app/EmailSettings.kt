package `in`.docket.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.*
import org.json.JSONObject

private const val EMAIL = "/v1/email"

/** Poll durable metadata only while the activity is visible; no inbox polling. */
@Composable fun IncomingEmailUpdates(vm: DocketViewModel, workspace: String) {
    val lifecycle = (LocalContext.current as? LifecycleOwner)?.lifecycle
    LaunchedEffect(workspace, lifecycle) {
        if (workspace.isBlank() || lifecycle == null) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            var cursor = ""
            while (isActive) {
                try {
                    val client = vm.api()
                    val result = withContext(Dispatchers.IO) { JSONObject(client.json("$EMAIL/events?after=$cursor")) }
                    val arrived = result.getJSONArray("events").objects().any { it.text("event") == "NEW_NOTICE_INGESTED" }
                    if (arrived) {
                        val loaded = withContext(Dispatchers.IO) { client.notices() }
                        vm.applyIncomingNotices(workspace, loaded)
                    }
                    cursor = result.text("cursor", cursor)
                } catch (e: CancellationException) { throw e }
                catch (e: ApiFailure) { if (e.status in listOf(401,403) && vm.store.session.workspace == workspace) { vm.signOut(); return@repeatOnLifecycle } }
                catch (_: Exception) { /* A reconnect replays durable events. */ }
                delay(3000)
            }
        }
    }
}

@Composable fun EmailSettingsCard(vm: DocketViewModel, busy: Boolean) {
    val context = LocalContext.current
    val uri = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    var options by remember { mutableStateOf<JSONObject?>(null) }
    var verification by remember { mutableStateOf<JSONObject?>(null) }
    var deliveries by remember { mutableStateOf(emptyList<JSONObject>()) }
    var consent by remember { mutableStateOf(false) }
    var confirmed by remember { mutableStateOf(false) }
    var working by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    suspend fun load() {
        val client = vm.api()
        val data = withContext(Dispatchers.IO) { Triple(JSONObject(client.json("$EMAIL/settings")), JSONObject(client.json("$EMAIL/verification")), org.json.JSONArray(client.json("$EMAIL/receipts")).objects()) }
        options = data.first; verification = data.second.optJSONObject("verification"); deliveries = data.third
    }
    fun action(path: String, method: String = "POST", body: JSONObject? = JSONObject().put("consent", true)) {
        scope.launch {
            working = true
            try { withContext(Dispatchers.IO) { vm.api().json(EMAIL + path, method, if (method == "DELETE") null else body) }; load(); message = "Mail settings saved. Update your mailbox rule if the address changed." }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { message = e.message.orEmpty() }
            finally { working = false }
        }
    }
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/xml")) { destination ->
        if (destination != null) scope.launch {
            try { withContext(Dispatchers.IO) { val bytes = vm.api().download("$EMAIL/gmail-filter.xml"); context.contentResolver.openOutputStream(destination)?.use { it.write(bytes) } ?: error("Could not save filter.") }; message = "Filter saved. Review matches in Gmail before importing." }
            catch (e: Exception) { message = e.message.orEmpty() }
        }
    }
    val lifecycle = (context as? LifecycleOwner)?.lifecycle
    LaunchedEffect(lifecycle) {
        if (lifecycle == null) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (isActive) {
                try { load() } catch (e: CancellationException) { throw e } catch (e: Exception) { message = e.message.orEmpty() }
                delay(5000)
            }
        }
    }
    val route = options?.optJSONObject("route")
    val enabled = route?.optBoolean("enabled") == true
    val disabled = busy || working
    SurfaceCard {
        Text("Selective email forwarding", style = MaterialTheme.typography.titleLarge)
        Text("Docket never requests access to your inbox. Your mailbox applies a rule you review; only forwarded messages reach the receiving provider and this business.")
        if (options?.optBoolean("delivery_configured") != true) Text("Local preview only. This address cannot be added to Gmail. Configure a receiving provider and webhook, then replace the preview address. Use fictional test messages below meanwhile.", color = GoldInk)
        if (message.isNotBlank()) Text(message, style = MaterialTheme.typography.bodySmall)
        if (!enabled) {
            Row { Checkbox(consent, { consent = it }); Text("I control the mailbox and may forward selected notices to this workspace and provider.", Modifier.weight(1f)) }
            Button(onClick = { action("/routing") }, enabled = consent && !disabled && options != null) { Text(if (options?.optBoolean("delivery_configured") == true) "Enable receiving address" else "Enable local preview") }
        } else {
            Text("1 · Add the destination in Gmail", style = MaterialTheme.typography.titleMedium)
            SelectionContainer { Text(route!!.text("address"), style = MaterialTheme.typography.bodySmall) }
            OutlinedButton(onClick = { (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Docket receiving address", route!!.text("address"))); message = "Address copied." }) { Text("Copy address") }
            Text("Use this Docket receiving address, not your own Gmail address. Gmail on a computer → Settings → Forwarding and POP/IMAP → Add a forwarding address. Keep forwarding for all mail disabled.", style = MaterialTheme.typography.bodySmall)
            Text("2 · Confirm in Gmail", style = MaterialTheme.typography.titleMedium)
            val code = verification?.takeIf { it.optDouble("expires_at") * 1000 > System.currentTimeMillis() }
            if (code != null) {
                Text(if (code.optBoolean("simulation")) "Fictional test confirmation" else "Google forwarding confirmation received", color = Positive)
                SelectionContainer { Text(code.text("confirmation_code"), style = MaterialTheme.typography.headlineMedium) }
                if (code.text("confirmation_url").startsWith("https://")) TextButton(onClick = { uri.openUri(code.text("confirmation_url")) }) { Text("Review Google confirmation link") }
            } else Text("Waiting for an authenticated Google confirmation message. Codes expire after 10 minutes.", style = MaterialTheme.typography.bodySmall)
            Row { Checkbox(confirmed || route!!.optDouble("confirmed_at") > 0, { confirmed = it }, enabled = options?.optBoolean("delivery_configured") == true && route.optDouble("confirmed_at") == 0.0); Text("I completed confirmation in Gmail.", Modifier.weight(1f)) }
            OutlinedButton(onClick = { action("/routing/confirm") }, enabled = !disabled && options?.optBoolean("delivery_configured") == true && confirmed && route!!.optDouble("confirmed_at") == 0.0) { Text("Save confirmation") }
            Text("3 · Review and import the filter", style = MaterialTheme.typography.titleMedium)
            Text("Keyword rules may match personal mail too. Sender rules do not authenticate a notice. Review matching messages before enabling forwarding.", style = MaterialTheme.typography.bodySmall)
            SelectionContainer { Text(options!!.text("filter_query"), style = MaterialTheme.typography.bodySmall) }
            Button(onClick = { export.launch("docket-selective-mail-filter.xml") }, enabled = !disabled && options?.optBoolean("delivery_configured") == true && route!!.optDouble("confirmed_at") > 0) { Text("Save Gmail filter XML") }
            Text("Replace the address to invalidate the old one, or disable receiving. Remove or update the Gmail rule too. Existing cases remain until deleted.", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { action("/routing/rotate") }, enabled = !disabled) { Text("Replace address") }
                TextButton(onClick = { action("/routing", "DELETE") }, enabled = !disabled) { Text("Disable receiving", color = Danger) }
            }
            if (options?.optBoolean("simulator_enabled") == true) {
                Text("Local test messages · fictional data", style = MaterialTheme.typography.titleMedium)
                listOf("verification" to "Google confirmation", "gst" to "GST notice + PDF", "legal" to "Manual legal forward", "phishing" to "Spoofed payment demand").forEach { (scenario, label) -> OutlinedButton(onClick = { action("/simulate", body = JSONObject().put("scenario", scenario)) }, enabled = !disabled, modifier = Modifier.fillMaxWidth()) { Text(label) } }
            }
        }
        if (deliveries.isNotEmpty()) {
            Text("Recent deliveries", style = MaterialTheme.typography.titleMedium)
            deliveries.take(5).forEach { Text((if (it.optInt("simulation") == 1) "Sample · " else "") + it.text("status") + if (it.text("error_code").isNotEmpty()) " · " + it.text("error_code") else "", style = MaterialTheme.typography.bodySmall) }
        }
    }
}
