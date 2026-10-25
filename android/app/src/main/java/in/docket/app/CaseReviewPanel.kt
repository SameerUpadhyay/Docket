package `in`.docket.app

import androidx.compose.foundation.layout.*
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.json.JSONArray

/** One consolidated workflow for confirmed facts, professional review and filing records. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun CaseReviewPanel(notice: Notice, vm: DocketViewModel, busy: Boolean, close: () -> Unit) {
    var tab by remember { mutableIntStateOf(0) }
    var issue by remember { mutableStateOf(notice.limitation?.text("date_of_issue").orEmpty()) }
    var service by remember { mutableStateOf(notice.limitation?.text("date_of_service").orEmpty()) }
    var window by remember { mutableStateOf(notice.limitation?.optInt("statutory_window_days").toString()) }
    var amount by remember { mutableStateOf(notice.amount.toString()) }
    var authority by remember { mutableStateOf(notice.authority) }; var section by remember { mutableStateOf(notice.law) }
    var basis by remember { mutableStateOf("") }; var comment by remember { mutableStateOf("") }
    var decision by remember { mutableStateOf("COMMENT") }
    var acknowledgement by remember { mutableStateOf("") }; var submitted by remember { mutableStateOf(java.time.LocalDate.now(indiaZone).toString()) }; var channel by remember { mutableStateOf("") }
    var history by remember { mutableStateOf(emptyList<JSONObject>()) }
    val editable = vm.store.session.role in listOf("owner", "editor") && !notice.closed
    val receiptPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) vm.attachProof(notice.id, uri) }
    val message by vm.message.collectAsState()
    LaunchedEffect(notice.json.toString(), tab) { if (tab == 3) try { history = withContext(Dispatchers.IO) { JSONArray(vm.api().json("/notices/${notice.id}/history")).objects() } } catch (e: Exception) { vm.notify(e.message.orEmpty()) } }
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Scaffold(topBar = { TopAppBar(title = { Text("Review & submission") }, navigationIcon = { TextButton(onClick = close) { Text("Back") } }) }, containerColor = Canvas) { padding -> Column(Modifier.padding(padding)) {
            TabRow(tab) { listOf("Facts", "Review", "Filing", "History").forEachIndexed { index, label -> Tab(tab == index, { tab = index }, text = { Text(label) }) } }
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                if (!message.isNullOrBlank()) Text(message.orEmpty(), color = Navy)
                Text("Facts: ${if (notice.json.optBoolean("facts_confirmed")) "confirmed" else "needs confirmation"} · Review: ${notice.json.text("professional_review", "PENDING")}", style = MaterialTheme.typography.bodySmall, color = Muted)
                when(tab) {
                    0 -> {
                        Text("Check every field against the original notice and proof of service. The response window must be confirmed for the applicable law and jurisdiction.", style = MaterialTheme.typography.bodyMedium)
                        OutlinedTextField(issue, { issue = it }, label = { Text("Issue date · YYYY-MM-DD") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(service, { service = it }, label = { Text("Service date · YYYY-MM-DD") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(window, { window = it }, label = { Text("Confirmed response period · days") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(amount, { amount = it }, label = { Text("Confirmed amount · INR") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(authority, { authority = it }, label = { Text("Issuing authority") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(section, { section = it }, label = { Text("Statute and section") }, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        OutlinedTextField(basis, { basis = it }, label = { Text("Source / reasoning for confirmation") }, minLines = 3, modifier = Modifier.fillMaxWidth(), enabled = editable)
                        Text("This action uses the dates as entered and removes any previously assumed Sunday adjustment. A professional must establish any extension before changing the dates.", style = MaterialTheme.typography.bodySmall, color = Muted)
                        Button(onClick = { val days = window.toIntOrNull(); val rupees = amount.toDoubleOrNull(); if (days == null || rupees == null) vm.notify("Enter a valid period and amount.") else vm.caseAction(notice.id, "facts", "PATCH", JSONObject().put("issue", issue).put("service", service).put("window", days).put("amount", rupees).put("authority", authority).put("section", section).put("basis", basis)) }, enabled = editable && !busy && basis.length >= 10, modifier = Modifier.fillMaxWidth()) { Text("Confirm facts & plan reminders") }
                    }
                    1 -> {
                        Text("Record the professional's findings. Docket does not certify qualifications or submit the response. Changing a saved draft requires a fresh review.", style = MaterialTheme.typography.bodyMedium)
                        listOf("COMMENT" to "Comment", "CHANGES_REQUESTED" to "Request changes", "REVIEWED" to "Record completed review").forEach { (value, title) -> FilterChip(decision == value, { decision = value }, label = { Text(title) }) }
                        OutlinedTextField(comment, { comment = it }, label = { Text("Review findings and basis") }, minLines = 5, modifier = Modifier.fillMaxWidth())
                        Button(onClick = { vm.caseAction(notice.id, "reviews", "POST", JSONObject().put("decision", decision).put("comment", comment)); comment = "" }, enabled = !busy && !notice.closed && comment.length >= 5 && vm.store.session.role in listOf("owner", "reviewer"), modifier = Modifier.fillMaxWidth()) { Text("Save review record") }
                    }
                    2 -> {
                        Text("After filing through the official channel, record its acknowledgement here. This records an external submission; the app does not file for you.", style = MaterialTheme.typography.bodyMedium)
                        notice.json.text("submission_receipt").takeIf { it.isNotBlank() }?.let { Text("Recorded acknowledgement: $it", color = Positive) }
                        OutlinedButton(onClick = { receiptPicker.launch(arrayOf("application/pdf", "image/png", "image/jpeg", "text/plain")) }, enabled = editable && !busy, modifier = Modifier.fillMaxWidth()) { Text(if (notice.json.text("submission_proof_name").isBlank()) "Attach official filing receipt" else "Replace filing receipt") }
                        notice.json.text("submission_proof_name").takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                        OutlinedTextField(acknowledgement, { acknowledgement = it }, label = { Text("Official acknowledgement / receipt reference") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(submitted, { submitted = it }, label = { Text("Submitted on · YYYY-MM-DD") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(channel, { channel = it }, label = { Text("Official portal / filing channel") }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = { vm.caseAction(notice.id, "submission", "POST", JSONObject().put("acknowledgement", acknowledgement).put("submitted_at", submitted).put("channel", channel)) }, enabled = editable && !busy && acknowledgement.length >= 3 && channel.length >= 3, modifier = Modifier.fillMaxWidth()) { Text("Record acknowledgement") }
                        OutlinedButton(onClick = { vm.state(notice.id, "SUBMITTED_CLOSED") }, enabled = editable && !busy && notice.json.text("submission_receipt").isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Close submitted case") }
                    }
                    3 -> {
                        Text("Case activity & draft versions", style = MaterialTheme.typography.titleLarge)
                        if (history.isEmpty()) Text("No history available yet.", color = Muted)
                        history.forEach { item -> SurfaceCard {
                            Text(item.text("event").replace('.', ' '), style = MaterialTheme.typography.titleSmall)
                            val instant = java.time.Instant.ofEpochMilli((item.optDouble("created_at") * 1000).toLong())
                            Text(instant.atZone(indiaZone).format(java.time.format.DateTimeFormatter.ofPattern("d MMM yyyy · HH:mm")), style = MaterialTheme.typography.bodySmall, color = Muted)
                            Text("Actor: ${item.text("actor")}", style = MaterialTheme.typography.bodySmall, color = Muted)
                            Text(item.optJSONObject("details")?.toString(2).orEmpty(), style = MaterialTheme.typography.bodySmall)
                        } }
                    }
                }
                Text("Playbook ${notice.json.text("playbook_version", "2026-10-25-unreviewed")} · professional legal sign-off required.", style = MaterialTheme.typography.bodySmall, color = Muted)
            }
        } }
    }
}
