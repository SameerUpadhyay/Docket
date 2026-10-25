package `in`.docket.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalUriHandler
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable fun AuthScreen(vm: DocketViewModel, busy: Boolean, message: String?) {
    var stage by rememberSaveable { mutableStateOf("login") }
    var origin by rememberSaveable { mutableStateOf(vm.store.server) }
    var email by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var name by rememberSaveable { mutableStateOf("") }
    var business by rememberSaveable { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var consent by rememberSaveable { mutableStateOf(false) }
    var working by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope(); val uri = LocalUriHandler.current
    fun perform(path: String, body: JSONObject, next: String) {
        working = true; status = ""
        scope.launch {
            try { val result = withContext(Dispatchers.IO) { JSONObject(ApiClient(origin).json(path, "POST", body)) }; status = result.text("message"); if (result.text("delivery") == "development-outbox") status += " Development server: the code is in the private dev-outbox folder."; stage = next; password = ""; code = "" }
            catch (e: Exception) { status = e.message.orEmpty() } finally { working = false }
        }
    }
    Surface(color = Canvas, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Spacer(Modifier.height(20.dp)); Text("DOCKET", color = Navy, style = MaterialTheme.typography.headlineLarge)
            Text(when(stage) { "register" -> "Create your business account"; "verify" -> "Verify your email"; "forgot" -> "Recover your account"; "reset" -> "Set a new password"; else -> "Your business. In order." }, style = MaterialTheme.typography.headlineMedium)
            Text("A secure workspace for your notices, evidence and advisors.", style = MaterialTheme.typography.bodyLarge, color = Muted)
            OutlinedTextField(value = email, onValueChange = { email = it }, label = { Text("Email address") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
            if (stage == "register") {
                OutlinedTextField(name, { name = it }, label = { Text("Your full name") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                OutlinedTextField(business, { business = it }, label = { Text("Business name") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            }
            if (stage in listOf("login", "register", "reset")) OutlinedTextField(password, { password = it }, label = { Text(if (stage == "login") "Password" else "Password · at least 12 characters") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
            if (stage in listOf("verify", "reset")) OutlinedTextField(code, { code = it }, label = { Text("8-digit email code") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            if (stage == "register") Row { Checkbox(consent, { consent = it }); Text("I accept the pilot terms and privacy notice and have authority to manage this business's documents.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f).padding(top = 10.dp)) }
            if (status.isNotBlank()) Text(status, color = Navy, style = MaterialTheme.typography.bodyMedium)
            if (!message.isNullOrBlank()) Text(message, color = Danger, style = MaterialTheme.typography.bodyMedium)
            Button(onClick = {
                val body = JSONObject().put("email", email.trim()).put("password", password).put("code", code.trim())
                when(stage) {
                    "login" -> { vm.signIn(origin, email.trim(), password); password = "" }
                    "register" -> perform("/auth/register", body.put("name", name).put("business", business).put("consent", consent), "verify")
                    "verify" -> perform("/auth/verify", body, "login")
                    "forgot" -> perform("/auth/forgot", body, "reset")
                    "reset" -> perform("/auth/reset", body, "login")
                }
            }, enabled = !busy && !working && email.contains('@') && (stage != "register" || consent), modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) { Text(if (busy || working) "Please wait…" else when(stage) { "login" -> "Sign in"; "register" -> "Create account"; "verify" -> "Verify email"; "forgot" -> "Send recovery code"; else -> "Change password" }) }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                TextButton(onClick = { stage = if (stage == "login") "register" else "login"; password = ""; status = "" }, enabled = !working && !busy) { Text(if (stage == "login") "Create account" else "Back to sign in") }
                if (stage == "login") TextButton(onClick = { stage = "forgot"; status = "" }) { Text("Forgot password?") }
                if (stage == "verify") TextButton(onClick = { perform("/auth/resend", JSONObject().put("email", email), "verify") }, enabled = !working) { Text("Resend code") }
            }
            OutlinedButton(onClick = { vm.exploreDemo() }, modifier = Modifier.fillMaxWidth(), enabled = !working && !busy) { Text("Explore sample workspace") }
            Text("Samples stay separate from your business account. No sample data is added to a new account.", style = MaterialTheme.typography.bodySmall, color = Muted)
            HorizontalDivider(color = Hairline)
            Row { TextButton(onClick = { runCatching { uri.openUri(origin.trimEnd('/') + "/api/public/privacy") } }) { Text("Privacy") }; TextButton(onClick = { runCatching { uri.openUri(origin.trimEnd('/') + "/api/public/terms") } }) { Text("Terms") } }
            var serverOptions by remember { mutableStateOf(false) }
            TextButton(onClick = { serverOptions = !serverOptions }) { Text("Server connection") }
            if (serverOptions) { OutlinedTextField(origin, { origin = it }, label = { Text("API origin") }, modifier = Modifier.fillMaxWidth(), singleLine = true); Text("Use your deployed HTTPS service. Local development uses USB port forwarding to 127.0.0.1:8000.", style = MaterialTheme.typography.bodySmall, color = Muted) }
        }
    }
}
