package `in`.docket.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

@Composable fun WorkspaceScreen(vm: DocketViewModel, apiMode: Boolean, busy: Boolean, accountSettings: () -> Unit, exportCenter: () -> Unit, mailRule: (String) -> Unit, remindersChanged: () -> Unit) {
    val context = LocalContext.current
    var connection by rememberSaveable { mutableStateOf(false) }
    var mail by rememberSaveable { mutableStateOf(false) }
    var about by rememberSaveable { mutableStateOf(false) }
    var url by rememberSaveable { mutableStateOf(vm.store.server) }
    var sourceEmail by rememberSaveable { mutableStateOf("") }
    var address by rememberSaveable { mutableStateOf("") }
    var verified by rememberSaveable { mutableStateOf(false) }
    var reminders by remember { mutableStateOf(vm.store.preferences.getBoolean("reminders", false)) }
    fun reminderState(value: Boolean) { reminders = value; vm.store.preferences.edit().putBoolean("reminders", value).apply(); ReminderScheduler.reschedule(context); remindersChanged() }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> reminderState(granted); if (!granted) vm.notify("Notifications were not enabled. Your deadline schedule is still available.") }
    LazyColumn(contentPadding = PaddingValues(20.dp, 20.dp, 20.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
        item { PageIntro("Your workspace", "Privacy, reminders and hand-off, together.") }
        item { SurfaceCard { WorkspaceRow(if (apiMode) "Account & business" else "Sign in to your business", if (apiMode) "Profile, advisor access, privacy and sessions" else "Leave samples and open a verified account", Icons.Outlined.AccountCircle, accountSettings) } }
        item { SurfaceCard {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) { ServiceIcon("Tax"); Column { Text("Docket workspace", style = MaterialTheme.typography.titleMedium); Text(if (apiMode) "Connected API service" else "Private device storage", style = MaterialTheme.typography.bodyMedium, color = Muted) } }
            Text(if (apiMode) vm.store.server else "Works offline. No mailbox account is connected.", style = MaterialTheme.typography.bodySmall, color = Muted)
        } }
        item { Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { Text("WORKSPACE & PRIVACY", style = MaterialTheme.typography.labelMedium, color = Muted); SurfaceCard {
            WorkspaceRow("Storage & API connection", "Choose device storage or your existing API", Icons.Outlined.Storage) { connection = true }
            HorizontalDivider(color = Hairline)
            WorkspaceRow("Mail rules & privacy", if (apiMode) "Set up selective forwarding in Account → Email" else "A selective Gmail filter, without mailbox access", Icons.Outlined.PrivacyTip) { if (apiMode) accountSettings() else mail = true }
        } } }
        item { Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { Text("REMINDERS & HAND-OFF", style = MaterialTheme.typography.labelMedium, color = Muted); SurfaceCard {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Icon(Icons.Outlined.Notifications, null, tint = Navy)
                Column(Modifier.weight(1f)) { Text("Device reminders", style = MaterialTheme.typography.titleMedium); Text("T−7, T−3 and T−1 for real cases", style = MaterialTheme.typography.bodySmall, color = Muted) }
                Switch(checked = reminders, onCheckedChange = { enabled -> if (enabled && Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.POST_NOTIFICATIONS) else reminderState(enabled) })
            }
            Text("Local notifications are approximate; Android may delay delivery. Sample cases never generate real reminders. No SMS or WhatsApp is sent.", style = MaterialTheme.typography.bodySmall, color = Muted)
            HorizontalDivider(color = Hairline)
            WorkspaceRow("Case exports", "Save briefs, replies and a complete advisor package", Icons.Outlined.FolderZip, exportCenter)
        } } }
        item { SurfaceCard { WorkspaceRow("About & service scope", "What is verified, estimated or not connected", Icons.Outlined.Info) { about = true } } }
        item { Text("Local-first by default. App-private files are excluded from Android backup. Review documents before sharing them.", style = MaterialTheme.typography.bodySmall, color = Muted) }
    }
    if (connection) AlertDialog(onDismissRequest = { if (!busy) connection = false }, title = { Text("Choose your workspace") }, text = { Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Business accounts use authenticated API storage. Sign out to explore a separate sample workspace.", style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(value = url, onValueChange = { url = it }, label = { Text("API server origin") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Text("For USB or emulator use: adb reverse tcp:8000 tcp:8000. Then use http://127.0.0.1:8000. Remote services require HTTPS; the API requires a verified account. Sign in from the welcome screen.", style = MaterialTheme.typography.bodySmall, color = Muted)
    } }, confirmButton = { TextButton(onClick = { vm.connect(url); connection = false }, enabled = !busy) { Text("Connect API") } }, dismissButton = { TextButton(onClick = { vm.deviceMode(); connection = false }, enabled = !busy) { Text("Use device storage") } })
    if (mail) AlertDialog(onDismissRequest = { mail = false }, title = { Text("Your inbox stays yours") }, text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("This device-only rule forwards matching notices to a separate address you control. It does not import them into Docket. For automatic ingestion, sign in and use Account → Email with a connected receiving provider. Gmail cannot forward to itself, including dot and plus aliases.")
        OutlinedTextField(value = sourceEmail, onValueChange = { sourceEmail = it; verified = false }, label = { Text("Gmail account you are importing into") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = address, onValueChange = { address = it; verified = false }, label = { Text("Separate verified receiving address") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row { Checkbox(checked = verified, onCheckedChange = { verified = it }); Text("I control this address and have verified it in Gmail Forwarding settings.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 10.dp).weight(1f)) }
        Text("Download the XML. In Gmail on a computer, open Settings → Filters and blocked addresses → Import filters. Review the matches before enabling forwarding.", style = MaterialTheme.typography.bodySmall, color = Muted)
    } }, confirmButton = { TextButton(onClick = { runCatching { MailRules.generate(address, sourceEmail) }.onSuccess { mailRule(address); mail = false }.onFailure { vm.notify(it.message.orEmpty()) } }, enabled = verified && sourceEmail.contains('@') && address.contains('@')) { Text("Save Gmail rule") } }, dismissButton = { TextButton(onClick = { mail = false }) { Text("Close") } })
    if (about) AlertDialog(onDismissRequest = { about = false }, title = { Text("Clear about our limits") }, text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Native Android · Kotlin + Jetpack Compose. Four supported notice playbooks, with five fictional sample cases.")
        Text("DIN format and mail headers are not verified signatures. Dates are planning estimates, not guaranteed extensions.")
        Text("Device OCR supports Latin text and QR codes. Regex redaction is not complete anonymization. Device data uses Android Keystore encryption. Account owners can opt in to encrypted original retention and external AI summaries on the server.")
        Text("No legal filing, payment, cybercrime report or advisor message is submitted automatically. Selective forwarded email intake requires owner setup in Account → Email and a configured receiving provider.")
    } }, confirmButton = { TextButton(onClick = { about = false }) { Text("Got it") } })
}
@Composable private fun WorkspaceRow(title: String, subtitle: String, image: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(image, null, tint = Navy, modifier = Modifier.size(23.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) { Text(title, style = MaterialTheme.typography.titleMedium); Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Muted) }
        Icon(Icons.Outlined.ChevronRight, null, tint = Muted)
    }
}
