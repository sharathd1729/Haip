package com.genhaip.calls

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.DocumentsContract
import android.provider.Settings
import android.text.InputType
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException

/** Setup in plain words, one step each: call log, recordings folder, battery, unknown numbers, personal numbers, pause. */
class SetupActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    private lateinit var box: LinearLayout

    private val askPhone = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (callLogAllowed(this)) SyncWorker.syncNow(this)
        render()
    }

    private val pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            prefs.recordingsTree = uri.toString()
            SyncWorker.syncNow(this)
        }
        render()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        title = getString(R.string.setup_title)
        box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(16), dp(20), dp(32))
        }
        setContentView(ScrollView(this).apply { addView(box) })
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun render() {
        box.removeAllViews()
        status()

        heading(R.string.step_call_log)
        if (callLogAllowed(this)) {
            text(getString(R.string.done_allowed))
        } else {
            text(getString(R.string.step_call_log_body))
            button(R.string.allow_call_log) {
                askPhone.launch(arrayOf(Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_PHONE_STATE))
            }
            text(getString(R.string.restricted_hint))
        }

        heading(R.string.step_folder)
        text(prefs.recordingsTree?.let { getString(R.string.folder_chosen, folderName(it)) } ?: getString(R.string.step_folder_body))
        button(if (prefs.recordingsTree == null) R.string.pick_folder else R.string.change_folder) { pickFolder.launch(null) }
        text(getString(R.string.folder_hint))

        heading(R.string.step_battery)
        if (getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) == true) {
            text(getString(R.string.done_battery))
        } else {
            text(getString(R.string.step_battery_body))
            button(R.string.open_battery) { open(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
        }
        text(getString(R.string.wifi_calling_hint))

        if (!BuildConfig.PERSONAL) {
            // A personal workspace (Yaad) keeps every call, so the unknown-number rule does not apply there.
            heading(R.string.step_unknown)
            unknownNumbers()
        }

        heading(R.string.step_personal)
        personalNumbers()

        heading(R.string.step_pause)
        box.addView(Switch(this).apply {
            text = getString(R.string.pause_switch)
            isChecked = prefs.paused
            setOnCheckedChangeListener { _, on ->
                prefs.paused = on
                if (!on) SyncWorker.syncNow(this@SetupActivity)
            }
        })

        heading(R.string.what_is_sent_title)
        text(getString(R.string.what_is_sent))

        button(R.string.sync_now) {
            SyncWorker.syncNow(this)
            Toast.makeText(this, R.string.sync_started, Toast.LENGTH_SHORT).show()
        }
        button(R.string.unlink) {
            prefs.clearDevice()
            Toast.makeText(this, R.string.unlinked, Toast.LENGTH_LONG).show()
            render()
        }
    }

    private fun status() {
        val linked = prefs.deviceToken != null
        val last = prefs.lastSyncAt
        val lines = mutableListOf(
            getString(if (linked) R.string.status_linked else R.string.status_not_linked),
            if (last > 0) getString(R.string.status_last_sync, DateUtils.getRelativeTimeSpanString(last)) else getString(R.string.status_never_synced),
            getString(R.string.status_sent_today, prefs.sentToday()),
        )
        if (prefs.paused) lines.add(getString(R.string.status_paused))
        prefs.lastError?.let { lines.add(getString(R.string.status_problem, it)) }
        text(lines.joinToString("\n")).setTypeface(null, Typeface.BOLD)
    }

    private fun unknownNumbers() {
        val options = listOf(
            "working_hours" to R.string.unknown_working_hours,
            "always" to R.string.unknown_always,
            "never" to R.string.unknown_never,
        )
        val group = RadioGroup(this)
        options.forEachIndexed { i, (_, label) ->
            group.addView(RadioButton(this).apply { id = View.generateViewId(); text = getString(label); tag = i })
        }
        val saved = options.indexOfFirst { it.first == prefs.unknownMode }.coerceAtLeast(0)
        (group.getChildAt(saved) as RadioButton).isChecked = true
        box.addView(group)
        val start = input(R.string.hours_start, prefs.hoursStart)
        val end = input(R.string.hours_end, prefs.hoursEnd)
        button(R.string.save_settings) {
            val checked = group.findViewById<RadioButton>(group.checkedRadioButtonId)
            val mode = options[(checked?.tag as? Int) ?: 0].first
            val body = JSONObject().put("unknown_numbers", mode)
            val s = start.text.toString().trim()
            val e = end.text.toString().trim()
            if (s.isEmpty() && e.isEmpty()) {
                body.put("working_hours", JSONObject.NULL)
            } else if (HHMM.matches(s) && HHMM.matches(e)) {
                body.put("working_hours", JSONObject().put("start", s).put("end", e))
            } else {
                Toast.makeText(this, R.string.hours_invalid, Toast.LENGTH_LONG).show()
                return@button
            }
            saveSettings(body) {
                prefs.unknownMode = mode
                prefs.hoursStart = s
                prefs.hoursEnd = e
            }
        }
    }

    private fun saveSettings(body: JSONObject, onSaved: () -> Unit) {
        val token = prefs.deviceToken ?: run {
            Toast.makeText(this, R.string.status_not_linked, Toast.LENGTH_LONG).show()
            return
        }
        lifecycleScope.launch {
            val r = withContext(Dispatchers.IO) {
                try { Api.putSettings(token, body) } catch (e: IOException) { null }
            }
            val msg = when {
                r == null -> getString(R.string.no_connection)
                r.code == 200 -> getString(R.string.settings_saved).also { onSaved() }
                else -> r.detail()
            }
            Toast.makeText(this@SetupActivity, msg, Toast.LENGTH_LONG).show()
        }
    }

    private fun personalNumbers() {
        text(getString(R.string.step_personal_body))
        val keys = prefs.personalKeys.sorted()
        keys.forEach { k ->
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            row.addView(TextView(this).apply {
                text = k
                textSize = 16f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(Button(this).apply {
                text = getString(R.string.remove)
                setOnClickListener {
                    prefs.personalKeys = prefs.personalKeys - k
                    render()
                }
            })
            box.addView(row)
        }
        val field = input(R.string.personal_hint, "")
        field.inputType = InputType.TYPE_CLASS_PHONE
        button(R.string.add_personal) {
            val number = field.text.toString()
            if (!Logic.usable(number)) {
                Toast.makeText(this, R.string.personal_invalid, Toast.LENGTH_LONG).show()
                return@button
            }
            prefs.personalKeys = prefs.personalKeys + Logic.key(number)
            render()
        }
    }

    // ── small view helpers ──────────────────────────────────────────────────

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun heading(res: Int) {
        box.addView(TextView(this).apply {
            text = getString(res)
            textSize = 18f
            setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(20), 0, dp(4))
        })
    }

    private fun text(value: String): TextView = TextView(this).apply {
        text = value
        textSize = 15f
        setPadding(0, dp(4), 0, dp(4))
        box.addView(this)
    }

    private fun button(res: Int, onClick: () -> Unit) {
        box.addView(Button(this).apply {
            text = getString(res)
            minHeight = dp(48)
            setOnClickListener { onClick() }
        })
    }

    private fun input(hint: Int, value: String): EditText = EditText(this).apply {
        this.hint = getString(hint)
        setText(value)
        textSize = 16f
        isSingleLine = true
        box.addView(this)
    }

    private fun open(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: Exception) {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }

    private fun folderName(tree: String): String =
        try { DocumentsContract.getTreeDocumentId(Uri.parse(tree)).substringAfter(':') } catch (e: Exception) { tree }

    companion object {
        private val HHMM = Regex("^([01]\\d|2[0-3]):[0-5]\\d$")

        fun callLogAllowed(c: Context): Boolean =
            c.checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED &&
                c.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED
    }
}
