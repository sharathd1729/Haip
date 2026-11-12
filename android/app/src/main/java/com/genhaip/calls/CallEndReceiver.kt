package com.genhaip.calls

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager

/** Phone back to idle = a call just ended (or was missed): sync shortly. Needs READ_PHONE_STATE. */
class CallEndReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return
        if (intent.getStringExtra(TelephonyManager.EXTRA_STATE) != TelephonyManager.EXTRA_STATE_IDLE) return
        val prefs = Prefs(context)
        if (prefs.deviceToken != null && !prefs.paused) SyncWorker.syncNow(context)
    }
}
