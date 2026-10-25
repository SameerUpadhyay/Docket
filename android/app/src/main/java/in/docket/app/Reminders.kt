package `in`.docket.app

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import java.time.LocalDate
import java.time.ZonedDateTime

object ReminderScheduler {
    fun reschedule(context: Context, notices: List<Notice> = NoticeStore(context).read()) {
        val store = NoticeStore(context)
        val alarm = context.getSystemService(AlarmManager::class.java)
        store.preferences.getStringSet("scheduled_alarm_ids", emptySet()).orEmpty().forEach { key ->
            val pending = PendingIntent.getBroadcast(context, key.hashCode(), Intent(context, ReminderReceiver::class.java).setAction(key), PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE)
            if (pending != null) { alarm.cancel(pending); pending.cancel() }
        }
        val keys = mutableSetOf<String>()
        if (store.preferences.getBoolean("reminders", false)) {
            notices.filter { !it.isDemo && !it.quarantined && !it.closed && it.deadline.isNotBlank() && (!store.connected || it.json.optBoolean("facts_confirmed")) }.forEach { notice ->
                for (days in listOf(7L, 3L, 1L)) {
                    val whenAt = runCatching { LocalDate.parse(notice.deadline).minusDays(days).atTime(9, 0).atZone(indiaZone) }.getOrNull() ?: continue
                    if (whenAt.isBefore(ZonedDateTime.now(indiaZone))) continue
                    val key = "${notice.id}/T-$days"
                    val intent = Intent(context, ReminderReceiver::class.java).setAction(key).putExtra("case_id", notice.id).putExtra("title", notice.title).putExtra("milestone", days.toInt())
                    val pending = PendingIntent.getBroadcast(context, key.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                    alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, whenAt.toInstant().toEpochMilli(), pending)
                    keys += key
                }
            }
        }
        store.preferences.edit().putStringSet("scheduled_alarm_ids", keys).apply()
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!NoticeStore(context).preferences.getBoolean("reminders", false)) return
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("deadlines", "Notice deadlines", NotificationManager.IMPORTANCE_DEFAULT).apply { description = "Local planning reminders for notices added to this workspace"; lockscreenVisibility = NotificationCompat.VISIBILITY_PRIVATE })
        val caseId = intent.getStringExtra("case_id") ?: return
        val notice = runCatching { NoticeStore(context).read() }.getOrElse { return }.firstOrNull { it.id == caseId } ?: return
        if (notice.closed || notice.quarantined || notice.isDemo) return
        val open = Intent(context, MainActivity::class.java).putExtra("case_id", caseId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val contentIntent = PendingIntent.getActivity(context, caseId.hashCode(), open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, "deadlines").setSmallIcon(R.drawable.ic_docket).setContentTitle("A notice needs your attention").setContentText("T-${intent.getIntExtra("milestone", 1)} checkpoint · Review the planning deadline in Docket.").setContentIntent(contentIntent).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build()
        NotificationManagerCompat.from(context).notify(caseId.hashCode(), notification)
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { if (intent.action == Intent.ACTION_BOOT_COMPLETED) runCatching { ReminderScheduler.reschedule(context) } }
}
