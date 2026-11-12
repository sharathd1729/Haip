package com.genhaip.calls

import android.app.Application

class HaipApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // WorkManager keeps the periodic sync across reboots; this re-schedules it after an app update (KEEP = no duplicate).
        if (Prefs(this).deviceToken != null) SyncWorker.schedule(this)
    }
}
