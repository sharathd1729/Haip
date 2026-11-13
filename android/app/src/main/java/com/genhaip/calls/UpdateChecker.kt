package com.genhaip.calls

import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Environment
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException

/**
 * In-app update (no Play Store): when the app opens, ask HAIP for the latest published version of this app
 * (/api/v1/app/android/version, scripts/publish_android_release.py). If it is newer, offer it; Update downloads the APK with
 * Android's DownloadManager and hands it to the system installer. The same signing key means it installs over this one.
 */
object UpdateChecker {
    private const val CHECK_EVERY_MS = 6 * 60 * 60 * 1000L
    private const val APK = "application/vnd.android.package-archive"

    fun maybeCheck(activity: ComponentActivity) {
        val prefs = activity.getSharedPreferences("updates", Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now - prefs.getLong("last_check", 0L) < CHECK_EVERY_MS) return
        prefs.edit().putLong("last_check", now).apply()
        activity.lifecycleScope.launch {
            val info = withContext(Dispatchers.IO) {
                try { Api.latestVersion(BuildConfig.FLAVOR) } catch (e: IOException) { null }
            } ?: return@launch
            if (info.versionCode <= BuildConfig.VERSION_CODE || activity.isFinishing) return@launch
            AlertDialog.Builder(activity)
                .setTitle(activity.getString(R.string.update_title, info.versionName))
                .setMessage(info.notes.ifBlank { activity.getString(R.string.update_body) })
                .setPositiveButton(R.string.update_now) { _, _ -> start(activity, info) }
                .setNegativeButton(R.string.update_later, null)
                .show()
        }
    }

    private fun start(activity: ComponentActivity, info: Api.Release) {
        if (!activity.packageManager.canRequestPackageInstalls()) {
            // Android asks once per app: "Allow installing apps from this source". Ask again when the person comes back.
            activity.getSharedPreferences("updates", Context.MODE_PRIVATE).edit().putLong("last_check", 0L).apply()
            Toast.makeText(activity, R.string.update_allow, Toast.LENGTH_LONG).show()
            activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${activity.packageName}")))
            return
        }
        val dm = activity.getSystemService(DownloadManager::class.java) ?: return
        val request = DownloadManager.Request(Uri.parse(Api.base + info.url))
            .setTitle(activity.getString(R.string.app_name) + " " + info.versionName)
            .setMimeType(APK)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalFilesDir(activity, Environment.DIRECTORY_DOWNLOADS, "update-${info.versionCode}.apk")
        val id = dm.enqueue(request)
        Toast.makeText(activity, R.string.update_downloading, Toast.LENGTH_SHORT).show()
        val app = activity.applicationContext
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                if (intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L) != id) return
                app.unregisterReceiver(this)
                val uri = dm.getUriForDownloadedFile(id)
                if (uri == null) {
                    Toast.makeText(app, R.string.update_failed, Toast.LENGTH_LONG).show()
                    return
                }
                app.startActivity(
                    Intent(Intent.ACTION_VIEW).setDataAndType(uri, APK)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
        }
        ContextCompat.registerReceiver(
            app, receiver, IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE), ContextCompat.RECEIVER_EXPORTED,
        )
    }
}
