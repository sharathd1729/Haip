package com.genhaip.calls

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.IOException
import java.util.concurrent.TimeUnit

enum class Outcome { OK, RETRY, REVOKED }

/** One sync: new call-log entries first, then their recordings. Runs every 15 minutes and shortly after each call. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = lock.withLock {
        val prefs = Prefs(applicationContext)
        val token = prefs.deviceToken
        if (prefs.paused || token == null) return@withLock Result.success()
        val outcome = try {
            val calls = CallSync(applicationContext, prefs, token).run()
            if (calls == Outcome.OK) RecordingSync(applicationContext, prefs, token).run() else calls
        } catch (e: IOException) {
            prefs.lastError = applicationContext.getString(R.string.no_connection)
            Outcome.RETRY
        } catch (e: SecurityException) {
            // A permission (call log, recordings folder) was taken back: nothing to retry until the person grants it again.
            prefs.lastError = e.message
            Outcome.OK
        }
        // Yaad: after a good sync, ask what to show as notifications. Never fails the sync.
        if (outcome == Outcome.OK && BuildConfig.PERSONAL) {
            try {
                Notifier.check(applicationContext, prefs, token)
            } catch (e: Exception) {
                // offline or a bad answer: the next sync asks again
            }
        }
        when (outcome) {
            Outcome.OK -> Result.success()
            Outcome.RETRY -> Result.retry()
            Outcome.REVOKED -> {
                prefs.clearDevice()
                prefs.lastError = applicationContext.getString(R.string.revoked)
                Result.success()
            }
        }
    }

    companion object {
        // The periodic and the after-call work may overlap: one sync at a time (the server is idempotent either way).
        private val lock = Mutex()

        private fun network() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).setConstraints(network()).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("calls-sync", ExistingPeriodicWorkPolicy.KEEP, req)
        }

        /** After a call ends: a few seconds for the call log and the recorder to finish writing. */
        fun syncNow(context: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>()
                .setInitialDelay(10, TimeUnit.SECONDS)
                .setConstraints(network())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("calls-sync-now", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }
    }
}
