package `in`.docket.app

import android.app.DatePickerDialog
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import java.time.LocalDate

@Composable fun IntakeScreen(vm: DocketViewModel, busy: Boolean, apiMode: Boolean, selectFile: () -> Unit, capturePages: () -> Unit, selectedUri: Uri?, filename: String, removeFile: () -> Unit, done: (String) -> Unit) {
    val preview by vm.ocrPreview.collectAsState()
    val reading by vm.reading.collectAsState()
    var issue by rememberSaveable { mutableStateOf("") }
    var received by rememberSaveable { mutableStateOf(LocalDate.now(indiaZone).toString()) }
    var window by rememberSaveable { mutableStateOf("") }
    var sunday by rememberSaveable { mutableStateOf(false) }
    var confirmed by rememberSaveable { mutableStateOf(false) }
    val period = window.toIntOrNull()
    LaunchedEffect(selectedUri) { vm.clearOcrPreview(); issue = ""; window = ""; confirmed = false }
    LaunchedEffect(preview?.text("document_id")) {
        preview?.optJSONObject("structured_triage")?.let { fields ->
            if (!fields.isNull("date_of_issue_iso")) issue = fields.text("date_of_issue_iso")
            if (!fields.isNull("response_window_days")) window = fields.text("response_window_days")
            confirmed = false
        }
    }
    LazyColumn(contentPadding = PaddingValues(20.dp, 20.dp, 20.dp, 30.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { PageIntro("Add a notice", "One intake for screening, dates and next steps.") }
        item { SurfaceCard {
            Icon(Icons.Outlined.DocumentScanner, null, tint = Navy, modifier = Modifier.size(30.dp))
            Text(if (selectedUri == null) "Scan or upload your notice" else filename, style = MaterialTheme.typography.titleMedium)
            Text("Capture every page and submit them together, or choose an existing file. Up to 12 pages and 10 MB.", style = MaterialTheme.typography.bodyMedium, color = Muted)
            Button(onClick = capturePages, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Outlined.PhotoCamera, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("Capture pages") }
            OutlinedButton(onClick = selectFile, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text(if (selectedUri == null) "Choose file" else "Choose a different file") }
            if (selectedUri != null) TextButton(onClick = removeFile, enabled = !busy) { Text("Remove document") }
            Text("English and Hindi are recognized automatically. No language selection is needed.", style = MaterialTheme.typography.bodySmall, color = Muted)
        } }
        if (selectedUri != null) item { Button(onClick = { vm.previewDocument(selectedUri) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text(if (busy) reading.ifBlank { "Reading document…" } else "Read document & suggest fields") } }
        if (preview != null) item { InfoBanner("Candidate fields found", "Issue date: ${preview?.optJSONObject("structured_triage")?.text("date_of_issue_iso", "not established")} · Response period: ${preview?.optJSONObject("structured_triage")?.text("response_window_days", "not established")} days. These are candidates; confirm them against the original. No case has been created yet.") }
        item { SectionTitle("Confirm the response period") }
        item { DateField("Date of issue", issue) { issue = it; confirmed = false } }
        item { DateField("Date received / served", received) { received = it; confirmed = false } }
        item { OutlinedTextField(value = window, onValueChange = { window = it.filter(Char::isDigit).take(3); confirmed = false }, modifier = Modifier.fillMaxWidth(), label = { Text("Response period in days") }, supportingText = { Text("Use the period stated in the original notice. It is not always 15 days.") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), isError = window.isNotEmpty() && (period == null || period !in 1..365)) }
        item { Row { Checkbox(checked = sunday, onCheckedChange = { sunday = it }); Text("Apply a Sunday adjustment only after confirming that office closure and the relevant law permit it.", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 10.dp).weight(1f)) } }
        item { Row { Checkbox(checked = confirmed, onCheckedChange = { confirmed = it }); Text("I checked the service date and response period against the notice.", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 10.dp).weight(1f)) } }
        item { InfoBanner(if (apiMode) "Analysis uses your API service" else "Analysis stays on this device", if (apiMode) "The selected original document is uploaded to ${vm.store.server}. Its configured OCR privacy choices apply. For a source-image inspector, enable original retention in Account → Privacy before upload." else "OCR and QR screening run on the phone. Camera originals are kept encrypted for source review. Review the extraction before acting.", Icons.Outlined.Lock) }
        item { Button(onClick = { selectedUri?.let { vm.analyze(it, issue, received, period ?: 0, sunday, done) } }, enabled = !busy && confirmed && issue.isNotBlank() && period != null && period in 1..365 && selectedUri != null, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
            if (busy) { CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = androidx.compose.ui.graphics.Color.White); Spacer(Modifier.width(10.dp)); Text(reading.ifBlank { "Reading and screening…" }) } else { Text("Analyze notice"); Spacer(Modifier.width(8.dp)); Icon(Icons.Outlined.ArrowForward, null, Modifier.size(18.dp)) }
        } }
    }
}
@Composable private fun DateField(label: String, value: String, update: (String) -> Unit) {
    val context = LocalContext.current
    val date = runCatching { LocalDate.parse(value) }.getOrDefault(LocalDate.now(indiaZone))
    OutlinedTextField(value = if (value.isBlank()) "Not established · choose date" else dayLabel(value), onValueChange = {}, modifier = Modifier.fillMaxWidth(), label = { Text(label) }, readOnly = true, singleLine = true, trailingIcon = { IconButton(onClick = { DatePickerDialog(context, { _, year, month, day -> update(LocalDate.of(year, month + 1, day).toString()) }, date.year, date.monthValue - 1, date.dayOfMonth).show() }) { Icon(Icons.Outlined.CalendarMonth, "Choose $label") } })
}
