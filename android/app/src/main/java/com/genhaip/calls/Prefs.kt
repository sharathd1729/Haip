package com.genhaip.calls

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import org.json.JSONObject
import java.time.LocalDate
import java.util.UUID

/** Everything the app keeps, in Keystore-backed encrypted storage (the device token above all). */
class Prefs(context: Context) {
    private val sp: SharedPreferences = open(context.applicationContext)

    var deviceToken: String?
        get() = sp.getString("device_token", null)
        set(v) = sp.edit().putString("device_token", v).apply()

    var devicePk: String?
        get() = sp.getString("device_pk", null)
        set(v) = sp.edit().putString("device_pk", v).apply()

    /** Stable id for this install, sent at registration (the server's re-register key). */
    val deviceId: String
        get() = sp.getString("device_id", null)
            ?: UUID.randomUUID().toString().replace("-", "").also { sp.edit().putString("device_id", it).apply() }

    /** Highest CallLog _ID already handled (sent, skipped or filtered). */
    var lastCallId: Long
        get() = sp.getLong("last_call_id", 0L)
        set(v) = sp.edit().putLong("last_call_id", v).apply()

    /** Calls older than this are never sent (set at the first registration: the last FIRST_SYNC_DAYS days). */
    var syncFloorMs: Long
        get() = sp.getLong("sync_floor_ms", 0L)
        set(v) = sp.edit().putLong("sync_floor_ms", v).apply()

    var lastSyncAt: Long
        get() = sp.getLong("last_sync_at", 0L)
        set(v) = sp.edit().putLong("last_sync_at", v).apply()

    var paused: Boolean
        get() = sp.getBoolean("paused", false)
        set(v) = sp.edit().putBoolean("paused", v).apply()

    var recordingsTree: String?
        get() = sp.getString("recordings_tree", null)
        set(v) = sp.edit().putString("recordings_tree", v).apply()

    /** Last settings saved to HAIP (shown again on the setup screen; HAIP holds the real copy). */
    var unknownMode: String
        get() = sp.getString("unknown_mode", "working_hours") ?: "working_hours"
        set(v) = sp.edit().putString("unknown_mode", v).apply()

    var hoursStart: String
        get() = sp.getString("hours_start", "09:00") ?: "09:00"
        set(v) = sp.edit().putString("hours_start", v).apply()

    var hoursEnd: String
        get() = sp.getString("hours_end", "19:00") ?: "19:00"
        set(v) = sp.edit().putString("hours_end", v).apply()

    var lastError: String?
        get() = sp.getString("last_error", null)
        set(v) = sp.edit().putString("last_error", v).apply()

    /** Numbers marked personal, as Logic.key(). Never leave the phone. */
    var personalKeys: Set<String>
        get() = sp.getStringSet("personal", emptySet())!!.toSet()
        set(v) = sp.edit().putStringSet("personal", v.toSet()).apply()

    fun sentToday(): Int =
        if (sp.getString("sent_day", "") == LocalDate.now().toString()) sp.getInt("sent_count", 0) else 0

    fun addSent(n: Int) {
        if (n > 0) sp.edit().putString("sent_day", LocalDate.now().toString()).putInt("sent_count", sentToday() + n).apply()
    }

    /** Accepted calls still waiting for their recording (answered, with talk time), newest RECORDING_WINDOW_MS only. */
    fun recordingCalls(): List<LoggedCall> {
        val json = JSONObject(sp.getString("recording_calls", "{}") ?: "{}")
        return json.keys().asSequence().map { id ->
            val o = json.getJSONObject(id)
            LoggedCall(id, o.getString("n"), o.getLong("s"), o.getInt("d"))
        }.toList()
    }

    fun addRecordingCalls(calls: List<LoggedCall>) {
        if (calls.isEmpty()) return
        saveRecordingCalls(recordingCalls() + calls)
    }

    fun markRecorded(deviceCallId: String) = saveRecordingCalls(recordingCalls().filter { it.deviceCallId != deviceCallId })

    private fun saveRecordingCalls(calls: List<LoggedCall>) {
        val floor = System.currentTimeMillis() - RECORDING_WINDOW_MS
        val json = JSONObject()
        calls.filter { it.startedMs >= floor }.forEach {
            json.put(it.deviceCallId, JSONObject().put("n", it.number).put("s", it.startedMs).put("d", it.durationSec))
        }
        sp.edit().putString("recording_calls", json.toString()).apply()
    }

    /** Recording files already uploaded or given up on ("<document uri>|<last modified>"). */
    fun handledFiles(): MutableSet<String> = sp.getStringSet("handled_files", emptySet())!!.toMutableSet()

    fun saveHandled(files: Set<String>) {
        // shortcut: keeps an arbitrary 2000 when over; fine because files older than RECORDING_WINDOW_MS are never re-read.
        sp.edit().putStringSet("handled_files", if (files.size > 2000) files.take(2000).toSet() else files.toSet()).apply()
    }

    fun clearDevice() = sp.edit().remove("device_token").remove("device_pk").apply()

    companion object {
        const val FIRST_SYNC_DAYS = 7L
        const val DAY_MS = 24 * 60 * 60 * 1000L
        const val RECORDING_WINDOW_MS = 7 * DAY_MS

        @Volatile private var cached: SharedPreferences? = null

        private fun open(c: Context): SharedPreferences = cached ?: synchronized(this) {
            cached ?: EncryptedSharedPreferences.create(
                "haip_calls",
                MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC),
                c,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            ).also { cached = it }
        }
    }
}
