package com.genhaip.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CallLog
import org.json.JSONArray
import org.json.JSONObject

private data class CallRow(val id: Long, val number: String, val type: Int, val dateMs: Long, val durationSec: Int)

/** Sends call-log entries newer than the cursor, 200 at a time. The cursor moves only once HAIP has answered for a batch. */
class CallSync(private val ctx: Context, private val prefs: Prefs, private val token: String) {
    fun run(): Outcome {
        if (ctx.checkSelfPermission(Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) return Outcome.OK
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
        )
        ctx.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            projection,
            "${CallLog.Calls._ID} > ? AND ${CallLog.Calls.DATE} >= ?",
            arrayOf(afterId.toString(), floorMs.toString()),
            "${CallLog.Calls._ID} ASC",
        )?.use { c ->
            while (out.size < BATCH && c.moveToNext()) {
                out.add(CallRow(c.getLong(0), c.getString(1) ?: "", c.getInt(2), c.getLong(3), c.getLong(4).coerceIn(0, 86_400).toInt()))
            }
        }
        return out
    }

    companion object {
        const val BATCH = 200
    }
}
