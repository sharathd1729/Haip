package com.genhaip.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.CallLog
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject

private data class CallRow(val id: Long, val number: String, val type: Int, val dateMs: Long, val durationSec: Int, val name: String?)

/** Sends call-log entries newer than the cursor, 200 at a time. The cursor moves only once HAIP has answered for a batch. */
class CallSync(private val ctx: Context, private val prefs: Prefs, private val token: String) {
    fun run(): Outcome {
        if (ctx.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) return Outcome.OK
        // Yaad: names for calls already sent. Runs again once contacts are allowed (the call log's own name is often empty).
        if (BuildConfig.PERSONAL && prefs.namesLevel < namesLevelNow() && catchUpNames() == Outcome.REVOKED) return Outcome.REVOKED
        while (true) {
            val rows = read(prefs.lastCallId, prefs.syncFloorMs)
            if (rows.isEmpty()) return Outcome.OK
            val personal = prefs.personalKeys
            // Personal numbers, blocked calls and withheld numbers are dropped HERE: they never reach HAIP.
            val send = rows.mapNotNull { row ->
                val dir = Logic.direction(row.type, row.durationSec) ?: return@mapNotNull null
                if (!Logic.usable(row.number) || Logic.isPersonal(row.number, personal)) null else row to dir
            }
            if (send.isNotEmpty()) {
                val arr = JSONArray()
                send.forEach { (row, dir) ->
                    arr.put(
                        JSONObject()
                            .put("device_call_id", row.id.toString())
                            .put("number", row.number.take(40))
                            .put("direction", dir.first)
                            .put("started_at", Logic.iso(row.dateMs))
                            .put("duration_sec", row.durationSec)
                            .put("answered", dir.second)
                            // Yaad only: the name saved in the phone's contacts. The business Calls app never sends it.
                            .apply { if (BuildConfig.PERSONAL) nameFor(row.number, row.name)?.let { put("contact_name", it.take(120)) } }
                    )
                }
                val r = Api.postCalls(token, JSONObject().put("calls", arr))
                when {
                    r.code == 200 -> remember(r, send)
                    r.code == 401 -> return Outcome.REVOKED
                    // A batch the server refuses as invalid would be refused forever: note it and move past it.
                    r.code == 422 -> prefs.lastError = ctx.getString(R.string.calls_refused, r.detail())
                    else -> {
                        prefs.lastError = ctx.getString(R.string.server_busy, r.code)
                        return Outcome.RETRY
                    }
                }
            }
            prefs.lastCallId = rows.maxOf { it.id }
            prefs.lastSyncAt = System.currentTimeMillis()
            if (rows.size < BATCH) {
                prefs.lastError = null
                return Outcome.OK
            }
        }
    }

    private fun remember(r: Resp, send: List<Pair<CallRow, Pair<String, Boolean>>>) {
        val byId = send.associateBy { it.first.id.toString() }
        val results = r.json().optJSONArray("results") ?: JSONArray()
        val waiting = ArrayList<LoggedCall>()
        var queued = 0
        for (i in 0 until results.length()) {
            val o = results.optJSONObject(i) ?: continue
            val status = o.optString("status")
            if (status == "queued") queued++
            val (row, dir) = byId[o.optString("device_call_id")] ?: continue
            // Only calls HAIP kept, answered with talk time, can have a recording worth sending.
            if ((status == "queued" || status == "duplicate") && dir.second && row.durationSec > 0) {
                waiting.add(LoggedCall(row.id.toString(), row.number, row.dateMs, row.durationSec))
            }
        }
        prefs.addRecordingCalls(waiting)
        prefs.addSent(queued)
    }

    private fun read(afterId: Long, floorMs: Long): List<CallRow> {
        val out = ArrayList<CallRow>()
        val projection = arrayOf(
            CallLog.Calls._ID, CallLog.Calls.NUMBER, CallLog.Calls.TYPE, CallLog.Calls.DATE, CallLog.Calls.DURATION,
            CallLog.Calls.CACHED_NAME,
        )
        ctx.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            projection,
            "${CallLog.Calls._ID} > ? AND ${CallLog.Calls.DATE} >= ?",
            arrayOf(afterId.toString(), floorMs.toString()),
            "${CallLog.Calls._ID} ASC",
        )?.use { c ->
            while (out.size < BATCH && c.moveToNext()) {
                out.add(CallRow(c.getLong(0), c.getString(1) ?: "", c.getInt(2), c.getLong(3), c.getLong(4).coerceIn(0, 86_400).toInt(), c.getString(5)))
            }
        }
        return out
    }

    /** Yaad, once: the saved names of numbers in the call log since the first sync, so calls sent before names were sent
     *  show names too. Not done (busy server) = tried again on the next sync; the normal call sync goes on either way. */
    private fun catchUpNames(): Outcome {
        val rows = ArrayList<Pair<String, String?>>()
        ctx.contentResolver.query(
            CallLog.Calls.CONTENT_URI, arrayOf(CallLog.Calls.NUMBER, CallLog.Calls.CACHED_NAME),
            "${CallLog.Calls.DATE} >= ?", arrayOf(prefs.syncFloorMs.toString()), "${CallLog.Calls._ID} ASC",
        )?.use { c -> while (c.moveToNext()) { val n = c.getString(0) ?: ""; rows.add(n to nameFor(n, c.getString(1))) } }
        for (chunk in Logic.contactNames(rows, prefs.personalKeys).chunked(NAMES_BATCH)) {
            val arr = JSONArray()
            chunk.forEach { (number, name) -> arr.put(JSONObject().put("number", number.take(40)).put("name", name)) }
            val r = Api.postNames(token, JSONObject().put("names", arr))
            if (r.code == 401) return Outcome.REVOKED
            if (r.code != 200) return Outcome.RETRY
        }
        prefs.namesLevel = namesLevelNow()
        return Outcome.OK
    }

    private val looked = HashMap<String, String?>()

    private fun contactsAllowed() = ctx.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED

    /** 1 = names from the call log only, 2 = also from contacts. */
    private fun namesLevelNow() = if (contactsAllowed()) 2 else 1

    /** The person's saved name: the call log's cached name, else (contacts allowed) a contacts lookup by number. */
    private fun nameFor(number: String, cached: String?): String? {
        cached?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        if (number.isBlank() || !contactsAllowed()) return null
        return looked.getOrPut(number) {
            try {
                val uri = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number))
                ctx.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)
                    ?.use { c -> if (c.moveToFirst()) c.getString(0)?.trim()?.takeIf { it.isNotEmpty() } else null }
            } catch (e: Exception) {
                null // a contacts provider that refuses: the call still goes, just without a name
            }
        }
    }

    companion object {
        const val BATCH = 200
        const val NAMES_BATCH = 500
    }
}
