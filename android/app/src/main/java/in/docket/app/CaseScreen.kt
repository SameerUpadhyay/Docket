package `in`.docket.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import org.json.JSONObject

@Composable fun CaseScreen(notice: Notice, busy: Boolean, draft: String, onDraft: (String) -> Unit, vm: DocketViewModel, attach: (String) -> Unit, export: () -> Unit, report: () -> Unit) {
    var inspectOcr by remember { mutableStateOf(false) }
    if (inspectOcr) OcrDocumentInspector(notice, vm) { inspectOcr = false }
    var deleteRequested by remember { mutableStateOf(false) }
    if (deleteRequested) AlertDialog(onDismissRequest = { deleteRequested = false }, title = { Text("Delete this case?") }, text = { Text("This permanently removes the live case, evidence, history and pending reminders. Export it first if needed. Backup retention follows the operator policy.") }, confirmButton = { TextButton(onClick = { vm.deleteCase(notice.id); deleteRequested = false }, enabled = !busy) { Text("Delete case", color = Danger) } }, dismissButton = { TextButton(onClick = { deleteRequested = false }) { Text("Cancel") } })
    var workflow by remember { mutableStateOf(false) }
    if (workflow) CaseReviewPanel(notice, vm, busy) { workflow = false }
    val canEdit = !vm.store.connected || vm.store.session.role != "reviewer"
    var tab by rememberSaveable(notice.id) { mutableIntStateOf(0) }
    var hindi by rememberSaveable(notice.id) { mutableStateOf(false) }
    var showNotes by rememberSaveable(notice.id) { mutableStateOf(false) }
    Column(Modifier.fillMaxSize()) {
        if (!notice.quarantined) TabRow(selectedTabIndex = tab, containerColor = Color.White, contentColor = Navy) {
            listOf("Overview", "Response", "Files").forEachIndexed { index, title -> Tab(selected = tab == index, onClick = { tab = index }, text = { Text(title) }) }
        }
        LazyColumn(contentPadding = PaddingValues(20.dp, 20.dp, 20.dp, 32.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            if (notice.quarantined) {
                item { InfoBanner("Suspicious notice isolated", "Do not pay, reply, install attachments or share credentials. Verify the claim through an independently located official channel.", Icons.Outlined.Shield, true) }
                item { PageIntro("Review the warning signs", "Fraud score ${notice.forensics.optInt("fraud_risk_score")}/100 · heuristic screening") }
                items(notice.flags) { flag -> SurfaceCard { Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { Icon(Icons.Outlined.WarningAmber, null, tint = Danger, modifier = Modifier.size(20.dp)); Text(flag, style = MaterialTheme.typography.bodyMedium) } } }
                item { Button(onClick = report, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Outlined.Download, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Save forensic report") } }
                item { Text("${if (notice.isDemo) "This is a fictional phishing scenario. " else ""}No report has been sent. An advocate or an independently contacted authority can help if authenticity remains unclear.", style = MaterialTheme.typography.bodySmall, color = Muted) }
                if (vm.store.connected && vm.store.session.role == "owner" && !notice.isDemo) item { TextButton(onClick = { deleteRequested = true }, enabled = !busy) { Text("Delete case and its data", color = Danger) } }
                item { SurfaceCard { Text("Redacted source", style = MaterialTheme.typography.titleMedium); SelectionContainer { Text(notice.redactedText, style = MaterialTheme.typography.bodySmall) } } }
            } else when (tab) {
                0 -> {
                    item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) { Text(notice.service, style = MaterialTheme.typography.labelLarge, color = Muted); StatusPill(notice) } }
                    item { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { Text(notice.title, style = MaterialTheme.typography.headlineMedium); Text(notice.authority, style = MaterialTheme.typography.bodyMedium, color = Muted) } }
                    if (vm.store.connected && !notice.isDemo) item { Button(onClick = { workflow = true }, modifier = Modifier.fillMaxWidth()) { Text("Review facts, filing & history") } }
                    item { InfoBanner(if (notice.isDemo) "Sample case" else "Authenticity needs confirmation", if (notice.isDemo) "Fictional figures and simulated verification. Demo date: 24 Oct 2026." else "The device has screened for common scam signals. DIN syntax and uploaded mail headers do not authenticate the notice.", Icons.Outlined.VerifiedUser) }
                    item { SurfaceCard {
                        Row(verticalAlignment = Alignment.CenterVertically) { Text("What this means", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f)); TextButton(onClick = { hindi = !hindi }) { Text(if (hindi) "English" else "हिन्दी") } }
                        Text(if (hindi) notice.hindi else notice.summary, style = MaterialTheme.typography.bodyLarge)
                        HorizontalDivider(color = Hairline)
                        DetailLine("Law / provision", notice.law)
                    } }
                    item { SurfaceCard {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Column(Modifier.weight(1f)) { Text("Amount to review", style = MaterialTheme.typography.labelMedium, color = Muted); Text(money(notice.amount), style = MaterialTheme.typography.headlineSmall); if (notice.amount == 0.0) Text("No labelled amount extracted", style = MaterialTheme.typography.bodySmall, color = Muted) }
                            Column(horizontalAlignment = Alignment.End) { Text("Risk score", style = MaterialTheme.typography.labelMedium, color = Muted); Text("${notice.risk}/100", style = MaterialTheme.typography.titleLarge) }
                        }
                        HorizontalDivider(color = Hairline)
                        DetailLine("Planning deadline", dayLabel(notice.deadline))
                        Text(notice.days?.let { if (it < 0) "${-it} days overdue · seek advice promptly" else if (it == 0L) "Due today" else "$it days remaining" }.orEmpty(), style = MaterialTheme.typography.labelLarge, color = if ((notice.days ?: 99) <= 3) Danger else Navy)
                        if (notice.limitation?.optBoolean("holiday_rollover_applied") == true) Text("Sunday adjustment shown. Confirm applicability and office closure.", style = MaterialTheme.typography.bodySmall, color = GoldInk)
                    } }
                    item { SurfaceCard {
                        Text("Recommended next step", style = MaterialTheme.typography.titleMedium)
                        Text(notice.triage?.text("professional_reason").orEmpty(), style = MaterialTheme.typography.bodyMedium, color = Muted)
                        Button(onClick = { tab = 1 }, modifier = Modifier.fillMaxWidth(), enabled = !notice.closed) { Text("Prepare your response"); Spacer(Modifier.width(8.dp)); Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(18.dp)) }
                    } }
                    item { TextButton(onClick = { showNotes = !showNotes }, contentPadding = PaddingValues(0.dp)) { Text(if (showNotes) "Hide calculation & review notes" else "Calculation & review notes"); Icon(if (showNotes) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, null) } }
                    if (showNotes) item { SurfaceCard {
                        DetailLine("Issued", dayLabel(notice.limitation?.text("date_of_issue").orEmpty()))
                        DetailLine("Received", dayLabel(notice.limitation?.text("date_of_service").orEmpty()))
                        DetailLine("Raw expiry", dayLabel(notice.limitation?.text("raw_expiry_date").orEmpty()))
                        Text("Planning estimates require confirmation of service, the prescribed period and the relevant office calendar.", style = MaterialTheme.typography.bodyMedium)
                        notice.reviewNotes.forEach { Text("• $it", style = MaterialTheme.typography.bodySmall, color = Muted) }
                    } }
                }
                1 -> {
                    item { PageIntro("Build your response", "Gather the records, then edit a single reply.") }
                    item { SurfaceCard {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text("Evidence checklist", style = MaterialTheme.typography.titleMedium); Text("${notice.collected}/${notice.documents.size}", style = MaterialTheme.typography.labelLarge, color = Muted) }
                        LinearProgressIndicator(progress = { if (notice.documents.isEmpty()) 0f else notice.collected.toFloat() / notice.documents.size }, modifier = Modifier.fillMaxWidth(), color = Navy, trackColor = Hairline)
                        Text(stateLabel(notice.state), style = MaterialTheme.typography.bodySmall, color = Muted)
                    } }
                    items(notice.documents, key = { it.text("doc_id") }) { doc -> EvidenceRow(doc, busy || notice.closed || !canEdit, { vm.toggle(notice.id, doc.text("doc_id"), it) }, { attach(doc.text("doc_id")) }) }
                    item { SectionTitle("Reply draft") }
                    item { OutlinedTextField(value = draft, onValueChange = onDraft, readOnly = notice.closed || !canEdit, modifier = Modifier.fillMaxWidth().heightIn(min = 360.dp, max = 520.dp), textStyle = MaterialTheme.typography.bodyMedium, shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp), label = { Text("Replace bracketed fields with verified facts") }) }
                    item { Button(onClick = { vm.saveDraft(notice.id, draft) }, enabled = !busy && !notice.closed && canEdit && draft != notice.draft, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Outlined.Save, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text(if (draft == notice.draft) "Draft saved" else "Save reply draft") } }
                    item { InfoBanner("Review before signing", "A template does not establish the facts. Have an advocate or CA review the reply when appropriate. Nothing is submitted automatically.") }
                }
                2 -> {
                    item { PageIntro("Your case file", "The source, evidence and hand-off in one place.") }
                    item { SurfaceCard {
                        OutlinedButton(onClick = { inspectOcr = true }, modifier = Modifier.fillMaxWidth()) { Text("Inspect OCR, fields & tables") }
                        Text("Source extraction", style = MaterialTheme.typography.titleMedium)
                        Text(notice.json.text("original_filename", "Pasted text"), style = MaterialTheme.typography.bodyMedium)
                        Text("${notice.json.optInt("pii_tokens_redacted_count")} identifiers masked. Original retention follows your business privacy settings. Confirm OCR against your original document.", style = MaterialTheme.typography.bodySmall, color = Muted)
                        SelectionContainer { Text(notice.redactedText, style = MaterialTheme.typography.bodyMedium) }
                    } }
                    item { SurfaceCard {
                        Text("Attached evidence", style = MaterialTheme.typography.titleMedium)
                        val attached = notice.documents.filter { it.text("attachment_name").isNotBlank() }
                        if (attached.isEmpty()) Text("No files attached yet. Add them from the Response checklist.", style = MaterialTheme.typography.bodyMedium, color = Muted)
                        attached.forEach { Text("• ${it.text("attachment_name")}", style = MaterialTheme.typography.bodyMedium) }
                        Text("Evidence is stored as supplied and may contain personal data. Review it before sharing.", style = MaterialTheme.typography.bodySmall, color = Muted)
                    } }
                    item { SurfaceCard {
                        Text("Ready for your advisor", style = MaterialTheme.typography.titleMedium)
                        Text("Save one package with the case brief, checklist, saved reply, redacted text and evidence files.", style = MaterialTheme.typography.bodyMedium, color = Muted)
                        if (vm.store.connected && vm.store.session.role == "owner" && !notice.isDemo) TextButton(onClick = { deleteRequested = true }, enabled = !busy) { Text("Delete case and its data", color = Danger) }
                        Button(onClick = export, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Outlined.Download, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Export case") }
                    } }
                }
            }
        }
    }
}

@Composable private fun EvidenceRow(doc: JSONObject, disabled: Boolean, checked: (Boolean) -> Unit, attach: () -> Unit) {
    var expanded by rememberSaveable(doc.text("doc_id")) { mutableStateOf(false) }
    SurfaceCard {
        Row(verticalAlignment = Alignment.Top) {
            Checkbox(checked = doc.optBoolean("is_collected"), onCheckedChange = checked, enabled = !disabled)
            Column(Modifier.weight(1f).padding(start = 6.dp, top = 9.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(doc.text("document_name"), style = MaterialTheme.typography.titleSmall)
                Text(doc.text("why_needed"), style = MaterialTheme.typography.bodySmall, color = Muted)
            }
        }
        if (doc.text("attachment_name").isNotBlank()) Text(doc.text("attachment_name"), style = MaterialTheme.typography.bodySmall, color = Positive)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { expanded = !expanded }, contentPadding = PaddingValues(horizontal = 0.dp)) { Text("Where to find it", style = MaterialTheme.typography.labelMedium); Icon(if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, null, Modifier.size(18.dp)) }
            OutlinedButton(onClick = attach, enabled = !disabled, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)) { Icon(Icons.Outlined.AttachFile, null, Modifier.size(16.dp)); Text(if (doc.text("attachment_name").isBlank()) "Attach" else "Replace", style = MaterialTheme.typography.labelMedium) }
        }
        if (expanded) Text(doc.text("source_hint"), style = MaterialTheme.typography.bodyMedium, color = Muted)
    }
}
