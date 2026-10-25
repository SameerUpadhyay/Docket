package `in`.docket.app

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

@Composable fun SurfaceCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), color = Color.White, border = BorderStroke(1.dp, Hairline)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
    }
}
@Composable fun PageIntro(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium)
        Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = Muted)
    }
}
@Composable fun SectionTitle(title: String, action: String? = null, onAction: () -> Unit = {}) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
        if (action != null) TextButton(onClick = onAction, contentPadding = PaddingValues(horizontal = 8.dp)) { Text(action) }
    }
}
@Composable fun ServiceIcon(service: String, modifier: Modifier = Modifier) {
    val image = when (service) { "Tax" -> Icons.Outlined.AccountBalance; "Labour" -> Icons.Outlined.Business; "Legal" -> Icons.Outlined.Gavel; "Security" -> Icons.Outlined.Shield; else -> Icons.Outlined.Description }
    Box(modifier.size(42.dp).background(if (service == "Security") Color(0xFFFCF0F0) else Color(0xFFEDF1F7), RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
        Icon(image, contentDescription = null, tint = if (service == "Security") Danger else Navy, modifier = Modifier.size(21.dp))
    }
}
@Composable fun StatusPill(notice: Notice) {
    val color = when (notice.severity) { "RED", "PHISHING_SCAM" -> Danger; "GREEN" -> Positive; else -> GoldInk }
    val bg = when (notice.severity) { "RED", "PHISHING_SCAM" -> Color(0xFFFBEFEF); "GREEN" -> Color(0xFFEEF7F1); else -> Color(0xFFFBF5DF) }
    Surface(color = if (notice.closed) Color(0xFFF0F2F5) else bg, shape = RoundedCornerShape(6.dp)) {
        Text(if (notice.closed) "Closed" else severityLabel(notice.severity), style = MaterialTheme.typography.labelMedium, color = if (notice.closed) Muted else color, modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp))
    }
}
@Composable fun NoticeCard(notice: Notice, onClick: () -> Unit) {
    Surface(Modifier.fillMaxWidth().clickable(onClick = onClick), shape = RoundedCornerShape(16.dp), color = Color.White, border = BorderStroke(1.dp, Hairline)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ServiceIcon(notice.service)
                Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                    Text(notice.service, style = MaterialTheme.typography.labelMedium, color = Muted)
                    Text(notice.title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                Icon(Icons.Outlined.ChevronRight, contentDescription = null, tint = Muted, modifier = Modifier.size(20.dp))
            }
            Text(notice.law, style = MaterialTheme.typography.bodySmall, color = Muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                StatusPill(notice)
                Text(if (notice.quarantined) "Do not engage" else notice.days?.let { if (it < 0) "${-it}d overdue" else if (it == 0L) "Due today" else "$it days left" } ?: "Review deadline", style = MaterialTheme.typography.labelMedium, color = if ((notice.days ?: 99) <= 3 && !notice.closed) Danger else Navy)
            }
        }
    }
}
@Composable fun InfoBanner(title: String, detail: String, icon: ImageVector = Icons.Outlined.Info, caution: Boolean = false) {
    Surface(color = if (caution) Color(0xFFFBF5DF) else Color(0xFFEDF2F8), shape = RoundedCornerShape(12.dp)) {
        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.spacedBy(11.dp)) {
            Icon(icon, contentDescription = null, tint = if (caution) GoldInk else Navy, modifier = Modifier.size(20.dp))
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = MaterialTheme.typography.titleSmall, color = if (caution) GoldInk else Navy)
                Text(detail, style = MaterialTheme.typography.bodySmall, color = if (caution) Color(0xFF75642E) else Muted)
            }
        }
    }
}
@Composable fun EmptyState(title: String, detail: String, icon: ImageVector = Icons.Outlined.FolderOpen) {
    Column(Modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(icon, contentDescription = null, tint = Muted, modifier = Modifier.size(36.dp))
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = Muted)
    }
}
@Composable fun DetailLine(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = Muted)
        Text(value.ifBlank { "Requires confirmation" }, style = MaterialTheme.typography.bodyLarge)
    }
}
