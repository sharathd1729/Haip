package com.genhaip.calls

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/**
 * Yaad phone notifications. The app is a WebView, which cannot receive web push, so each background sync asks HAIP
 * (GET /devices/updates) and shows what comes back: summary ready, reminders due today, your day at a glance.
 * Every item has a stable id; ids already shown are skipped, so asking twice never notifies twice.
 */
object Notifier {
    private const val CHANNEL = "yaad_updates"
    private const val KEEP_IDS = 200

    fun check(context: Context, prefs: Prefs, token: String) {
        val r = Api.updates(token, prefs.notifySince)
        if (r.code != 200) return
        val j = r.json()
        val items = j.optJSONArray("notifications")
        val shown = prefs.shownNotifications.toMutableList()
        if (items != null) {
            for (i in 0 until items.length()) {
                val n = items.optJSONObject(i) ?: continue
                val id = n.optString("id")
                if (id.isBlank() || id in shown) continue
                post(context, id, n.optString("title"), n.optString("body"), n.optString("path"))
                shown.add(id)
            }
        }
        prefs.shownNotifications = shown.takeLast(KEEP_IDS)
        j.optString("now").takeIf { it.isNotBlank() }?.let { prefs.notifySince = it }
    }

    fun allowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission") // checked by allowed()
    private fun post(context: Context, id: String, title: String, body: String, path: String) {
        if (!allowed(context)) return
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, context.getString(R.string.notify_channel), NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        val open = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_PATH, path)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val tap = PendingIntent.getActivity(
            context, id.hashCode(), open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_notify)
            .setColor(ContextCompat.getColor(context, R.color.brand_accent))
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(tap)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(id.hashCode(), notification)
    }
}
