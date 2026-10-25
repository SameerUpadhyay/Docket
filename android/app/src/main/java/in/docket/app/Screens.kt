package `in`.docket.app

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.time.LocalDate

@Composable fun HomeScreen(notices: List<Notice>, open: (String) -> Unit, showCases: () -> Unit, apiMode: Boolean) {
    val active = notices.filter { !it.closed && !it.quarantined }.sortedBy { it.deadline }
    val urgent = active.firstOrNull()
    LazyColumn(contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 100.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
        item { PageIntro("A clearer way forward.", "Your notices and next steps, together.") }
        item {
            Surface(shape = RoundedCornerShape(20.dp), color = Navy) {
                Column(Modifier.fillMaxWidth().padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.size(7.dp).background(Gold, RoundedCornerShape(50)))
                        Text("YOUR NEXT PRIORITY", style = MaterialTheme.typography.labelMedium, color = Color(0xFFE0E7F1))
                    }
                    Text(urgent?.title ?: "You’re all caught up.", style = MaterialTheme.typography.headlineSmall, color = Color.White)
                    Text(urgent?.let { "Planning deadline · ${dayLabel(it.deadline)}" } ?: "Add a notice when you’re ready. We’ll help you organize the response.", style = MaterialTheme.typography.bodyMedium, color = Color(0xFFCBD6E5))
                    if (urgent != null) Button(onClick = { open(urgent.id) }, colors = ButtonDefaults.buttonColors(containerColor = Gold, contentColor = Navy), shape = RoundedCornerShape(10.dp)) { Text("Review notice"); Spacer(Modifier.width(8.dp)); Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(18.dp)) }
                    HorizontalDivider(color = Color.White.copy(alpha = .18f))
                    Row(Modifier.fillMaxWidth()) {
                        Column(Modifier.weight(1f)) { Text(active.size.toString().padStart(2, '0'), style = MaterialTheme.typography.headlineSmall, color = Color.White); Text("Open notices", style = MaterialTheme.typography.bodySmall, color = Color(0xFFCBD6E5)) }
                        Column(Modifier.weight(1f)) { Text(active.count { (it.days ?: 999) <= 7 }.toString().padStart(2, '0'), style = MaterialTheme.typography.headlineSmall, color = Gold); Text("Due within 7 days", style = MaterialTheme.typography.bodySmall, color = Color(0xFFCBD6E5)) }
                    }
                }
            }
        }
        if (active.size > 1) item { SectionTitle("Also on your desk", "View all", showCases) }
        items(active.drop(1).take(2), key = { it.id }) { notice -> NoticeCard(notice) { open(notice.id) } }
        if (notices.any { it.quarantined && !it.closed }) item {
            val threats = notices.filter { it.quarantined && !it.closed }
            SurfaceCard {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    ServiceIcon("Security")
                    Column(Modifier.weight(1f)) { Text("${threats.size} suspicious notice isolated", style = MaterialTheme.typography.titleMedium); Text("Keep payment requests outside your response workflow.", style = MaterialTheme.typography.bodySmall, color = Muted) }
                }
                TextButton(onClick = { open(threats.first().id) }, contentPadding = PaddingValues(0.dp)) { Text("Review security findings"); Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(17.dp).padding(start = 4.dp)) }
            }
        }
        item { InfoBanner(if (apiMode) "Connected API workspace" else "Private device workspace", if (apiMode) "Uploads and edits use your configured API service." else "Cases stay in app-private storage. The five sample cases use a fixed demo clock of 24 Oct 2026.", Icons.Outlined.Lock) }
    }
}

@Composable fun NoticesScreen(notices: List<Notice>, open: (String) -> Unit, refresh: () -> Unit, busy: Boolean) {
    var query by rememberSaveable { mutableStateOf("") }
    var service by rememberSaveable { mutableStateOf("All") }
    var status by rememberSaveable { mutableStateOf("Open") }
    val filtered = notices.filter { n ->
        (service == "All" || n.service == service) && (if (status == "Closed") n.closed else !n.closed) && (query.isBlank() || "${n.title} ${n.authority} ${n.law}".contains(query, true))
    }.sortedWith(compareBy<Notice> { it.quarantined }.thenBy { it.deadline.ifBlank { "9999" } })
    LazyColumn(contentPadding = PaddingValues(20.dp, 20.dp, 20.dp, 100.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { PageIntro("Your notices", "Tax, labour, legal and security — one place.") }
        item { OutlinedTextField(value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(), placeholder = { Text("Search notices or authorities") }, leadingIcon = { Icon(Icons.Outlined.Search, null) }, singleLine = true, shape = RoundedCornerShape(12.dp)) }
        item { Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("All", "Tax", "Labour", "Legal", "Security").forEach { label -> FilterChip(selected = service == label, onClick = { service = label }, label = { Text(label) }, modifier = Modifier.testTag("service-$label")) } } }
        item { Row(verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("Open", "Closed").forEach { value -> TextButton(onClick = { status = value }, colors = ButtonDefaults.textButtonColors(contentColor = if (status == value) Navy else Muted)) { Text(value, fontWeight = if (status == value) FontWeight.Bold else FontWeight.Normal) } } }
            IconButton(onClick = refresh, enabled = !busy) { Icon(Icons.Outlined.Refresh, "Refresh cases") }
        } }
        if (filtered.isEmpty()) item { EmptyState("No notices here", "Try another service, status or search.") }
        items(filtered, key = { it.id }) { notice -> NoticeCard(notice) { open(notice.id) } }
    }
}

data class Milestone(val notice: Notice, val date: LocalDate, val remaining: Int)
fun milestones(notices: List<Notice>): List<Milestone> = notices.filter { !it.closed && !it.quarantined && it.deadline.isNotBlank() }.flatMap { notice ->
    val today = if (notice.isDemo) demoDate else LocalDate.now(indiaZone)
    listOf(7, 3, 1).mapNotNull { days -> runCatching { LocalDate.parse(notice.deadline).minusDays(days.toLong()) }.getOrNull()?.takeIf { !it.isBefore(today) }?.let { Milestone(notice, it, days) } }
}.sortedBy { it.date }

@Composable fun DeadlinesScreen(notices: List<Notice>, remindersEnabled: Boolean, open: (String) -> Unit, settings: () -> Unit) {
    val checkpoints = remember(notices) { milestones(notices) }
    LazyColumn(contentPadding = PaddingValues(20.dp, 20.dp, 20.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { PageIntro("Stay ahead of deadlines", "A simple schedule for the next response.") }
        item { InfoBanner(if (remindersEnabled) "Device reminders enabled" else "Your planning schedule", if (remindersEnabled) "Real cases get local T−7, T−3 and T−1 reminders around 09:00 IST. Android may defer delivery. Sample cases are never scheduled." else "Review upcoming checkpoints here. Enable optional device reminders in Workspace.", Icons.Outlined.Notifications) }
        if (!remindersEnabled) item { OutlinedButton(onClick = settings, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp)) { Text("Manage reminders") } }
        val overdue = notices.filter { !it.closed && !it.quarantined && (it.days ?: 1) < 0 }
        if (overdue.isNotEmpty()) item { InfoBanner("${overdue.size} overdue notice(s)", "Open Notices and obtain professional advice promptly.", Icons.Outlined.WarningAmber, true) }
        if (checkpoints.isEmpty()) item { EmptyState("No upcoming checkpoints", "Your cases may be closed, due soon or awaiting a confirmed deadline.", Icons.Outlined.EventAvailable) }
        items(checkpoints, key = { "${it.notice.id}/${it.remaining}" }) { item ->
            SurfaceCard {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(13.dp)) {
                    Surface(color = Color(0xFFEDF1F7), shape = RoundedCornerShape(12.dp)) { Column(Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) { Text(item.date.dayOfMonth.toString(), style = MaterialTheme.typography.headlineSmall); Text(item.date.month.name.take(3), style = MaterialTheme.typography.labelMedium, color = Muted) } }
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) { Text(item.notice.title, style = MaterialTheme.typography.titleMedium); Text("T−${item.remaining} checkpoint · 09:00 IST", style = MaterialTheme.typography.bodySmall, color = Muted); Text(if (item.notice.isDemo) "Demo schedule" else "Planning reminder", style = MaterialTheme.typography.labelMedium, color = GoldInk) }
                }
                TextButton(onClick = { open(item.notice.id) }, contentPadding = PaddingValues(0.dp)) { Text("Open case"); Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(18.dp).padding(start = 4.dp)) }
            }
        }
        item { Text("Deadlines are planning estimates. Confirm the prescribed response period, service date and applicable office calendar.", style = MaterialTheme.typography.bodySmall, color = Muted) }
    }
}
