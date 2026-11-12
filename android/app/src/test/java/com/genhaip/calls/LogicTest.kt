package com.genhaip.calls

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class LogicTest {
    private val t0 = 1_762_934_400_000L // 2025-11-12T08:00:00Z
    private val guest = LoggedCall("101", "+91 98123 45678", t0, 120)          // ends t0 + 2 min
    private val other = LoggedCall("102", "08012345678", t0 + 3_600_000, 60)  // an hour later
    private val calls = listOf(guest, other)

    @Test fun callTypes() {
        assertEquals("in" to true, Logic.direction(1, 30))
        assertEquals("out" to false, Logic.direction(2, 0))
        assertEquals("out" to true, Logic.direction(2, 5))
        assertEquals("in" to false, Logic.direction(3, 0))
        assertEquals("in" to false, Logic.direction(5, 0))
        assertNull(Logic.direction(6, 0)) // blocked: never sent
    }

    @Test fun numbersCompareByLastTenDigits() {
        assertEquals("9812345678", Logic.key("+91 98123-45678"))
        assertEquals(Logic.key("09812345678"), Logic.key("+919812345678"))
        assertTrue(Logic.isPersonal("+91 98123 45678", setOf("9812345678")))
        assertFalse(Logic.isPersonal("9800000000", setOf("9812345678")))
        assertFalse(Logic.usable("-1"))
        assertFalse(Logic.usable(""))
    }

    @Test fun isoAlwaysHasSecondsAndOffset() {
        assertEquals("2025-11-12T13:30:00+05:30", Logic.iso(t0, ZoneId.of("Asia/Kolkata")))
        assertEquals("2025-11-12T08:00:00Z", Logic.iso(t0, ZoneId.of("UTC")))
    }

    @Test fun numberInNameFindsTheCallClosestToTheFileTime() {
        val r = Logic.matchByName("Call recording 9812345678_251112_133200.m4a", guest.endMs + 5_000, calls, emptySet())
        assertEquals(NameMatch.Found(guest), r)
    }

    @Test fun personalNumberInNameIsRefused() {
        val r = Logic.matchByName("Call_+919812345678_20251112.m4a", guest.endMs, calls, setOf("9812345678"))
        assertEquals(NameMatch.Refuse, r)
    }

    @Test fun unknownNumberInNameIsRefusedNotGuessedByTime() {
        val r = Logic.matchByName("Call recording 9700000000_251112_133200.m4a", guest.endMs, calls, emptySet())
        assertEquals(NameMatch.Refuse, r)
    }

    @Test fun datesAndTimesAreNotPhoneNumbers() {
        assertEquals(NameMatch.NoNumber, Logic.matchByName("Call recording Asha_251112_133200.m4a", guest.endMs, calls, emptySet()))
        assertEquals(NameMatch.NoNumber, Logic.matchByName("rec_20251112133200.amr", guest.endMs, calls, emptySet()))
    }

    @Test fun matchByTimeNeedsOneCallInTheWholeLogAndASimilarLength() {
        val ends = listOf(guest.endMs, other.endMs)
        assertEquals(guest, Logic.matchByTime(guest.endMs + 30_000, 118, calls, ends))
        assertNull(Logic.matchByTime(guest.endMs + 30_000, null, calls, ends))         // unknown audio length
        assertNull(Logic.matchByTime(guest.endMs + 30_000, 40, calls, ends))           // far too short
        val personalCallRightAfter = guest.endMs + 60_000
        assertNull(Logic.matchByTime(guest.endMs + 30_000, 118, calls, ends + personalCallRightAfter)) // two calls ended nearby
        assertNull(Logic.matchByTime(guest.endMs + 10 * 60_000, 118, calls, ends))     // nothing near
    }

    @Test fun audioNames() {
        assertTrue(Logic.isAudioName("a.M4A"))
        assertTrue(Logic.isAudioName("b.amr"))
        assertFalse(Logic.isAudioName("notes.txt"))
        assertFalse(Logic.isAudioName("noext"))
    }
}
