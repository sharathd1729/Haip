package com.genhaip.calls

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.CallLog
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document

private data class Doc(val uri: Uri, val docId: String, val name: String, val modified: Long, val size: Long, val isDir: Boolean)

/**
 * Uploads each new file in the folder the person picked (Storage Access Framework, read-only) that matches a call HAIP
 * accepted: by the number in the file name, else by time (Logic). Files that match nothing are never sent.
 */
class RecordingSync(private val ctx: Context, private val prefs: Prefs, private val token: String) {
    fun run(): Outcome {
        val tree = Uri.parse(prefs.recordingsTree ?: return Outcome.OK)
        val calls = prefs.recordingCalls().toMutableList()
        if (calls.isEmpty()) return Outcome.OK
        val now = System.currentTimeMillis()
        val personal = prefs.personalKeys
        val handled = prefs.handledFiles()
        try {
            for (f in files(tree)) {
                if (calls.isEmpty()) break
                if (f.modified < now - Prefs.RECORDING_WINDOW_MS || now - f.modified < SETTLE_MS) continue
                if (f.size <= 0 || f.size > MAX_BYTES || !Logic.isAudioName(f.name)) continue
                val key = "${f.uri}|${f.modified}"
                if (key in handled) continue
                val call = match(f, calls, personal)
                if (call == null) {
                    if (f.modified < now - Prefs.DAY_MS) handled.add(key) // its call is not coming: stop re-checking it
                    continue
                }
                val r = Api.uploadRecording(token, call.deviceCallId, ctx.contentResolver, f.uri, f.name.substringAfterLast('.').lowercase(), f.size)
                when (r.code) {
                    200, 201, 202 -> {
                        handled.add(key)
                        calls.remove(call)
                        prefs.markRecorded(call.deviceCallId)
                    }
                    401 -> return Outcome.REVOKED
                    429, 503 -> return Outcome.RETRY
                    in 500..599 -> return Outcome.RETRY
                    else -> {
                        // 404 / 411 / 413 / 415 / 422: the same file would be refused again.
                        handled.add(key)
                        prefs.lastError = ctx.getString(R.string.recording_refused, r.detail())
                    }
                }
            }
        } finally {
            prefs.saveHandled(handled)
        }
        return Outcome.OK
    }

    private fun match(f: Doc, calls: List<LoggedCall>, personal: Set<String>): LoggedCall? =
        when (val byName = Logic.matchByName(f.name, f.modified, calls, personal)) {
            is NameMatch.Found -> byName.call
            NameMatch.Refuse -> null
            NameMatch.NoNumber -> Logic.matchByTime(f.modified, audioSeconds(f.uri), calls, callEndsAround(f.modified))
        }

    /** End times of EVERY call in the log that started in the 4 hours before the file (personal and skipped included). */
    private fun callEndsAround(fileMs: Long): List<Long> {
        val out = ArrayList<Long>()
        ctx.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            arrayOf(CallLog.Calls.DATE, CallLog.Calls.DURATION),
            "${CallLog.Calls.DATE} >= ? AND ${CallLog.Calls.DATE} <= ?",
            arrayOf((fileMs - 4 * 3_600_000L).toString(), fileMs.toString()),
            null,
        )?.use { c -> while (c.moveToNext()) out.add(c.getLong(0) + c.getLong(1) * 1000L) }
        return out
    }

    private fun audioSeconds(uri: Uri): Int? {
        val m = MediaMetadataRetriever()
        return try {
            m.setDataSource(ctx, uri)
            m.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()?.let { (it / 1000).toInt() }
        } catch (e: RuntimeException) {
            null
        } finally {
            m.release()
        }
    }

    /** The picked folder and one level of sub-folders (Samsung keeps calls in Recordings/Call). One query per folder. */
    private fun files(tree: Uri): List<Doc> {
        val root = children(tree, DocumentsContract.getTreeDocumentId(tree))
        return root.filter { !it.isDir } + root.filter { it.isDir }.flatMap { d -> children(tree, d.docId).filter { !it.isDir } }
    }

    private fun children(tree: Uri, parentId: String): List<Doc> {
        val out = ArrayList<Doc>()
        val projection = arrayOf(
            Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE,
            Document.COLUMN_LAST_MODIFIED, Document.COLUMN_SIZE,
        )
        ctx.contentResolver.query(DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId), projection, null, null, null)
            ?.use { c ->
                while (c.moveToNext()) {
                    val id = c.getString(0) ?: continue
                    out.add(
                        Doc(
                            DocumentsContract.buildDocumentUriUsingTree(tree, id), id, c.getString(1) ?: "",
                            c.getLong(3), c.getLong(4), c.getString(2) == Document.MIME_TYPE_DIR,
                        )
                    )
                }
            }
        return out
    }

    companion object {
        const val MAX_BYTES = 50L * 1024 * 1024
        const val SETTLE_MS = 20_000L // a file changed in the last 20 s may still be being written
    }
}
