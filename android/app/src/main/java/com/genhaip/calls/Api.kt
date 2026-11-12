package com.genhaip.calls

import android.content.ContentResolver
import android.net.Uri
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Resp(val code: Int, val body: String) {
    fun json(): JSONObject = try { JSONObject(body) } catch (e: Exception) { JSONObject() }

    /** The server's plain-sentence error, else the status. */
    fun detail(): String = json().opt("detail")?.let { if (it is String) it else it.toString() }?.takeIf { it.isNotBlank() } ?: "HTTP $code"
}

/** The device API (docs/CALLS_APP_API.md). Blocking calls: run them off the main thread. Network failure = IOException. */
object Api {
    val base: String = BuildConfig.HAIP_BASE_URL.trimEnd('/')
    private val JSON_TYPE = "application/json; charset=utf-8".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .build()

    @Throws(IOException::class)
    private fun send(req: Request): Resp = http.newCall(req).execute().use { Resp(it.code, it.body?.string() ?: "") }

    private fun v1(path: String) = "$base/api/v1$path"

    /** NextAuth session of the WebView's login: contains accessToken (the backend JWT) when signed in. */
    fun session(cookies: String): Resp =
        send(Request.Builder().url("$base/api/auth/session").header("Cookie", cookies).get().build())

    fun register(accessToken: String, body: JSONObject): Resp = send(
        Request.Builder().url(v1("/devices/register")).header("Authorization", "Bearer $accessToken")
            .post(body.toString().toRequestBody(JSON_TYPE)).build()
    )

    fun putSettings(token: String, body: JSONObject): Resp = send(
        Request.Builder().url(v1("/devices/settings")).header("Authorization", "Bearer $token")
            .put(body.toString().toRequestBody(JSON_TYPE)).build()
    )

    fun postCalls(token: String, body: JSONObject): Resp = send(
        Request.Builder().url(v1("/device-calls")).header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody(JSON_TYPE)).build()
    )

    /** Streams the file; its known length gives the request a Content-Length (the server requires one). */
    fun uploadRecording(token: String, deviceCallId: String, resolver: ContentResolver, uri: Uri, ext: String, length: Long): Resp {
        val file = object : RequestBody() {
            override fun contentType(): MediaType = "application/octet-stream".toMediaType()
            override fun contentLength(): Long = length
            override fun writeTo(sink: BufferedSink) {
                val input = resolver.openInputStream(uri) ?: throw IOException("Cannot open the recording")
                input.use { sink.writeAll(it.source()) }
            }
        }
        // The server ignores the file name (type comes from the bytes); a plain ASCII name keeps the part header valid.
        val form = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file", "recording.$ext", file).build()
        return send(
            Request.Builder().url(v1("/device-calls/${Uri.encode(deviceCallId)}/recording"))
                .header("Authorization", "Bearer $token").post(form).build()
        )
    }
}
