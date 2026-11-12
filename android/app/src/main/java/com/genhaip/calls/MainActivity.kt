package com.genhaip.calls

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The existing HAIP web app (its own login and screens). Once signed in, the phone is linked in the background. */
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private var linking = false
    private var refused = false
    private val site: String = (Uri.parse(Api.base).host ?: "").removePrefix("www.")

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        CookieManager.getInstance().setAcceptCookie(true)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.userAgentString = web.settings.userAgentString + " HAIPCalls/" + BuildConfig.VERSION_NAME
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // genhaip.com and www.genhaip.com are both HAIP (the bare domain redirects to www).
                if (request.url.host?.removePrefix("www.") == site) return false
                // WhatsApp, tel:, maps and other sites open in their own apps.
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                } catch (e: ActivityNotFoundException) {
                    Toast.makeText(this@MainActivity, R.string.cannot_open_link, Toast.LENGTH_SHORT).show()
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) = onUrl(url)

            // The web app moves between pages without reloading (Next.js): history changes still arrive here.
            override fun doUpdateVisitedHistory(view: WebView, url: String, isReload: Boolean) = onUrl(url)
        }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })
        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) web.loadUrl("${Api.base}/dashboard")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    private fun onUrl(url: String) {
        if (Uri.parse(url).path?.startsWith("/dashboard") == true) linkPhone()
    }

    private fun linkPhone() {
        val prefs = Prefs(this)
        if (prefs.deviceToken != null || linking || refused) return
        linking = true
        lifecycleScope.launch {
            val message = withContext(Dispatchers.IO) { Registration.register(applicationContext) }
            linking = false
            // HAIP said no (phone revoked or another person's): say it once, not on every page. Reopening the app retries.
            if (message != null && prefs.deviceToken == null && message != getString(R.string.no_connection)) refused = true
            if (message != null) Toast.makeText(this@MainActivity, message, Toast.LENGTH_LONG).show()
            if (prefs.deviceToken != null && !SetupActivity.callLogAllowed(this@MainActivity)) {
                startActivity(Intent(this@MainActivity, SetupActivity::class.java))
            }
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(Menu.NONE, MENU_SETUP, Menu.NONE, R.string.menu_setup)
        menu.add(Menu.NONE, MENU_RELOAD, Menu.NONE, R.string.menu_reload)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        MENU_SETUP -> {
            startActivity(Intent(this, SetupActivity::class.java))
            true
        }
        MENU_RELOAD -> {
            web.reload()
            true
        }
        else -> super.onOptionsItemSelected(item)
    }

    companion object {
        private const val MENU_SETUP = 1
        private const val MENU_RELOAD = 2
    }
}
