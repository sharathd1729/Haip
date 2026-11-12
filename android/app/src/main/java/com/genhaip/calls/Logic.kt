package com.genhaip.calls

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.max

/** A call HAIP accepted (queued / duplicate) that may still get its recording. */
data class LoggedCall(val deviceCallId: String, val number: String, val startedMs: Long, val durationSec: Int) {
    val endMs: Long get() = startedMs + durationSec * 1000L
}

/** What a recording's file name says about its call. */
sealed class NameMatch {
    data class Found(val call: LoggedCall) : NameMatch()
    object Refuse : NameMatch()   // a personal or unknown number is in the name: never upload, never guess
    object NoNumber : NameMatch() // no phone number in the name: the caller may try matching by time
}

/** Pure rules (no Android classes) so they run as plain JVM unit tests. */
object Logic {
    const val NUMBER_MATCH_MS = 30 * 60 * 1000L
    const val TIME_MATCH_MS = 2 * 60 * 1000L
    private val ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssXXX")
    private val AUDIO = setOf("m4a", "mp3", "amr", "aac", "wav", "ogg", "3gp", "awb", "opus")
    private val DIGIT_RUN = Regex("\\d+")

    /** CallLog.Calls.TYPE -> (direction, answered); null = never sent (blocked or an unknown type). */
    fun direction(type: Int, durationSec: Int): Pair<String, Boolean>? = when (type) {
        1 -> "in" to true                 // INCOMING
        2 -> "out" to (durationSec > 0)   // OUTGOING: 0 seconds = nobody picked up
        3, 4, 5 -> "in" to false          // MISSED, VOICEMAIL, REJECTED
        7 -> "in" to true                 // ANSWERED_EXTERNALLY
        else -> null                      // 6 BLOCKED, anything new
    }

    /** Last 10 digits, so +91 98123 45678, 09812345678 and 9812345678 compare as one number. */
    fun key(number: String): String = number.filter(Char::isDigit).takeLast(10)

    /** Too short to be a real number: withheld, private, "-1", short codes. */
    fun usable(number: String): Boolean = key(number).length >= 7

    fun isPersonal(number: String, personalKeys: Set<String>): Boolean = key(number).let { it.length >= 7 && it in personalKeys }

    /** ISO 8601 with the zone offset, seconds always present (the API refuses a time without a zone). */
    fun iso(epochMs: Long, zone: ZoneId = ZoneId.systemDefault()): String = Instant.ofEpochMilli(epochMs).atZone(zone).format(ISO)

    fun isAudioName(name: String): Boolean = name.substringAfterLast('.', "").lowercase() in AUDIO

    /** Digit runs that look like a phone number (10-13 digits). A 14-digit run is a yyyyMMddHHmmss timestamp, 6-8 a date or time. */
    fun phoneRuns(name: String): List<String> = DIGIT_RUN.findAll(name).map { it.value }.filter { it.length in 10..13 }.toList()

    fun matchByName(fileName: String, fileModifiedMs: Long, calls: List<LoggedCall>, personalKeys: Set<String>): NameMatch {
        val digits = fileName.filter(Char::isDigit)
        if (personalKeys.any { it.length >= 10 && digits.contains(it) }) return NameMatch.Refuse
        val byNumber = calls.filter { key(it.number).length >= 10 && digits.contains(key(it.number)) }
        if (byNumber.isNotEmpty()) {
            val best = byNumber.minByOrNull { abs(it.endMs - fileModifiedMs) }!!
            return if (abs(best.endMs - fileModifiedMs) <= NUMBER_MATCH_MS) NameMatch.Found(best) else NameMatch.Refuse
        }
        // A number HAIP did not accept (unknown number skipped, personal, another phone's): never fall back to time.
        return if (phoneRuns(fileName).isNotEmpty()) NameMatch.Refuse else NameMatch.NoNumber
    }

    /**
     * Match by time only when it cannot be someone else's call: exactly ONE call in the whole call log (personal and
     * skipped ones included, [logEndsMs]) ended within [TIME_MATCH_MS] of the file, that call is one HAIP accepted, and the
     * audio is about as long as the call. Unknown audio length = no match.
     */
    fun matchByTime(fileModifiedMs: Long, fileDurationSec: Int?, calls: List<LoggedCall>, logEndsMs: List<Long>): LoggedCall? {
        if (fileDurationSec == null) return null
        if (logEndsMs.count { abs(it - fileModifiedMs) <= TIME_MATCH_MS } != 1) return null
        val call = calls.singleOrNull { abs(it.endMs - fileModifiedMs) <= TIME_MATCH_MS } ?: return null
        val tolerance = max(10, call.durationSec * 15 / 100)
        return if (abs(fileDurationSec - call.durationSec) <= tolerance) call else null
    }
}
