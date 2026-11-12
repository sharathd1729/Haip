package com.genhaip.calls

import android.content.Context
import android.os.Build
import android.webkit.CookieManager
import org.json.JSONObject
import java.io.IOException

/** Links this phone to the staff member signed in inside the WebView (docs/CALLS_APP_API.md, "Getting the user token"). */
object Registration {
    /**
     * Blocking: call off the main thread. Returns a message for the person, or null when there is nothing to say
     * (not signed in yet). Only the device token is kept; the session cookies and the user token are not stored.
     */
    fun register(context: Context): String? {
        val prefs = Prefs(context)
        val cookies = CookieManager.getInstance().getCookie(Api.base) ?: return null
        return try {
            val session = Api.session(cookies)
            val json = session.json()
            if (session.code != 200 || json.isNull("accessToken")) return null
            val body = JSONObject()
                .put("device_id", prefs.deviceId)
                .put("model", "${Build.MANUFACTURER} ${Build.MODEL}".take(100))
                .put("android_version", Build.VERSION.RELEASE.take(20))
                .put("app_version", BuildConfig.VERSION_NAME.take(20))
            val r = Api.register(json.getString("accessToken"), body)
            if (r.code != 201) return r.detail()
            val out = r.json()
            prefs.deviceToken = out.getString("token")
            prefs.devicePk = out.optString("id")
            prefs.lastError = null
            if (prefs.syncFloorMs == 0L) prefs.syncFloorMs = System.currentTimeMillis() - Prefs.FIRST_SYNC_DAYS * Prefs.DAY_MS
            SyncWorker.schedule(context)
            SyncWorker.syncNow(context)
            context.getString(R.string.linked)
        } catch (e: IOException) {
            context.getString(R.string.no_connection)
        }
    }
}
