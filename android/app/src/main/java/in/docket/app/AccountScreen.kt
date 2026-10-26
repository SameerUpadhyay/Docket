package `in`.docket.app

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalUriHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.json.JSONArray

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun AccountScreen(vm: DocketViewModel, busy: Boolean, back: () -> Unit) {
    val account by vm.account.collectAsState(); val message by vm.message.collectAsState()
    val current = account ?: return
    val owner = current.getJSONObject("workspace").text("role") == "owner"
    var tab by remember { mutableIntStateOf(0) }
    var name by remember { mutableStateOf(current.getJSONObject("user").text("name")) }
    var business by remember { mutableStateOf(current.getJSONObject("workspace").text("business")) }
    var memberEmail by remember { mutableStateOf("") }; var invitation by remember { mutableStateOf("") }
    var invitedRole by remember { mutableStateOf("reviewer") }
    var members by remember { mutableStateOf(emptyList<JSONObject>()) }
    var sessions by remember { mutableStateOf(emptyList<JSONObject>()) }
    var preferences by remember { mutableStateOf(JSONObject()) }
    var deleting by remember { mutableStateOf(false) }; var password by remember { mutableStateOf("") }
    var refreshed by remember { mutableIntStateOf(0) }
    val uri = LocalUriHandler.current
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { it?.let(vm::exportAccount) }
    BackHandler { back() }
    LaunchedEffect(refreshed, current.getJSONObject("workspace").text("id")) {
        try { withContext(Dispatchers.IO) {
            preferences = JSONObject(vm.api().json("/workspace/preferences")); sessions = JSONArray(vm.api().json("/auth/sessions")).objects()
            if (owner) members = JSONArray(vm.api().json("/workspace/members")).objects()
        } } catch (e: Exception) { vm.notify(e.message.orEmpty()) }
    }
    Scaffold(topBar = { TopAppBar(title = { Text("Account & business") }, navigationIcon = { TextButton(onClick = back) { Text("Back") } }) }, containerColor = Canvas) { padding -> Column(Modifier.padding(padding)) {
        TabRow(tab) { listOf("Business", "Access", "Privacy", "Email").forEachIndexed { index, title -> Tab(tab == index, { tab = index }, text = { Text(title) }) } }
        LazyColumn(contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            if (!message.isNullOrBlank()) item { Text(message.orEmpty(), style = MaterialTheme.typography.bodyMedium, color = Navy) }
            when(tab) {
                0 -> {
                    item { PageIntro(business, current.getJSONObject("user").text("email")) }
                    item { SurfaceCard {
                        Text("Business profile", style = MaterialTheme.typography.titleMedium)
                        OutlinedTextField(name, { name = it }, label = { Text("Your name") }, modifier = Modifier.fillMaxWidth(), enabled = owner)
                        OutlinedTextField(business, { business = it }, label = { Text("Business name") }, modifier = Modifier.fillMaxWidth(), enabled = owner)
                        if (owner) Button(onClick = { vm.accountAction("/account/profile", "PATCH", JSONObject().put("name", name).put("business", business)) { vm.notify("Profile saved.") } }, enabled = !busy) { Text("Save profile") }
                    } }
                    item { SurfaceCard {
                        Text("Switch business", style = MaterialTheme.typography.titleMedium)
                        current.getJSONArray("workspaces").objects().forEach { workspace ->
                            OutlinedButton(onClick = { vm.selectWorkspace(workspace.text("id")); back() }, enabled = !busy && workspace.text("id") != current.getJSONObject("workspace").text("id"), modifier = Modifier.fillMaxWidth()) { Text("${workspace.text("business")} · ${workspace.text("role")}") }
                        }
                    } }
                    item { SurfaceCard { Text("Join an invited business", style = MaterialTheme.typography.titleMedium); OutlinedTextField(invitation, { invitation = it }, label = { Text("Invitation code from email") }, modifier = Modifier.fillMaxWidth()); Button(onClick = { vm.accountAction("/workspace/invitations/accept", body = JSONObject().put("token", invitation)) { invitation = ""; vm.notify("Business joined. Select it from Switch business.") } }, enabled = !busy && invitation.length >= 20) { Text("Accept invitation") } } }
                }
                1 -> {
                    item { PageIntro("People & sessions", "Access is limited to this business and can be revoked.") }
                    if (owner) {
                        item { SurfaceCard {
                            Text("Invite an advisor or colleague", style = MaterialTheme.typography.titleMedium)
                            OutlinedTextField(memberEmail, { memberEmail = it }, label = { Text("Email address") }, modifier = Modifier.fillMaxWidth())
                            Row { FilterChip(invitedRole == "reviewer", { invitedRole = "reviewer" }, label = { Text("Reviewer") }); Spacer(Modifier.width(8.dp)); FilterChip(invitedRole == "editor", { invitedRole = "editor" }, label = { Text("Editor") }) }
                            Text("Reviewers can read cases and record reviews. Editors can prepare cases. Verify professional credentials independently before inviting anyone.", style = MaterialTheme.typography.bodySmall, color = Muted)
                            Button(onClick = { vm.accountAction("/workspace/invitations", body = JSONObject().put("email", memberEmail).put("role", invitedRole)) { vm.notify("Invitation sent."); memberEmail = "" } }, enabled = !busy && memberEmail.contains('@')) { Text("Send invitation") }
                        } }
                        item { SurfaceCard { Text("Business members", style = MaterialTheme.typography.titleMedium); members.forEach { member ->
                            Text("${member.text("name")} · ${member.text("role")}"); Text(member.text("email"), style = MaterialTheme.typography.bodySmall, color = Muted)
                            if (member.text("role") != "owner") TextButton(onClick = { vm.accountAction("/workspace/members/${member.text("id")}", "DELETE") { refreshed++; vm.notify("Access revoked.") } }, enabled = !busy) { Text("Revoke access", color = Danger) }
                        } } }
                    }
                    item { SurfaceCard { Text("Active sessions", style = MaterialTheme.typography.titleMedium); sessions.forEach { Text(it.text("label"), style = MaterialTheme.typography.bodySmall, maxLines = 2) }; Text("Sessions expire after 12 hours. Password recovery revokes every device.", style = MaterialTheme.typography.bodySmall, color = Muted); OutlinedButton(onClick = { vm.signOut(true); back() }, enabled = !busy) { Text("Sign out all devices") } } }
                }
                3 -> {
                    item { PageIntro("Incoming email", "Forward selected notices without connecting your inbox.") }
                    item { if (owner) key(current.getJSONObject("workspace").text("id")) { EmailSettingsCard(vm, busy) } else SurfaceCard { Text("The business owner manages receiving addresses and forwarding confirmation. Incoming cases appear automatically in your notice list.") } }
                }
                2 -> {
                    item { PageIntro("Your data, your choices", "Optional processing is disabled until the owner enables it.") }
                    if (owner && preferences.has("email_reminders")) item { SurfaceCard {
                        listOf(Triple("email_reminders", "Email deadline reminders", "Only after facts are confirmed. Email contains no documents. Delivery may be delayed."), Triple("cloud_ocr", "Cloud OCR for document images", "Original pages may be sent to the configured Gemini or Textract provider. Gemini supports bilingual OCR; Textract is English-only. This is separate from AI summaries."), Triple("external_ai", "External AI summaries", "Masked notice text is sent to the configured Google Gemini service. Masking may miss identifiers."), Triple("retain_original", "Retain future original uploads", "Stores future intake originals encrypted on the server. Disabling does not delete existing retained files.")).forEach { (key, title, description) ->
                            Row { Column(Modifier.weight(1f)) { Text(title, style = MaterialTheme.typography.titleSmall); Text(description, style = MaterialTheme.typography.bodySmall, color = Muted) }; Switch(preferences.optInt(key) == 1, { enabled -> preferences = JSONObject(preferences.toString()).put(key, if (enabled) 1 else 0) }) }
                        }
                        Button(onClick = { vm.accountAction("/workspace/preferences", "PATCH", JSONObject().put("email_reminders", preferences.optInt("email_reminders") == 1).put("cloud_ocr", preferences.optInt("cloud_ocr") == 1).put("external_ai", preferences.optInt("external_ai") == 1).put("retain_original", preferences.optInt("retain_original") == 1)) { refreshed++; vm.notify("Privacy choices saved.") } }, enabled = !busy) { Text("Save choices") }
                    } }
                    item { SurfaceCard {
                        Text("Data & account", style = MaterialTheme.typography.titleMedium)
                        if (owner) OutlinedButton(onClick = { export.launch("docket-account-export.zip") }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Export business data") }
                        TextButton(onClick = { uri.openUri(vm.store.server + "/api/public/privacy") }) { Text("Read privacy notice") }
                        TextButton(onClick = { deleting = true }, enabled = !busy) { Text("Delete account", color = Danger) }
                        Text("Deleting an owner account also deletes its business workspaces, evidence, history and invitations. Encrypted backups expire under the operator's retention policy.", style = MaterialTheme.typography.bodySmall, color = Muted)
                    } }
                }
            }
            item { OutlinedButton(onClick = { vm.signOut(); back() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Sign out") } }
        }
    } }
    if (deleting) AlertDialog(onDismissRequest = { if (!busy) { deleting = false; password = "" } }, title = { Text("Permanently delete your account?") }, text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) { Text("Owned business records and other members' access to them will be removed. Export your records first if you need them."); OutlinedTextField(password, { password = it }, label = { Text("Confirm your current password") }, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation()) } }, confirmButton = { TextButton(onClick = { vm.removeAccount(password); password = ""; deleting = false }, enabled = !busy && password.isNotEmpty()) { Text("Delete account", color = Danger) } }, dismissButton = { TextButton(onClick = { deleting = false; password = "" }) { Text("Cancel") } })
}
