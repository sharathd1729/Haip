package com.genhaip.calls

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

// Step 4 placeholder so the CI build has something to sign; step 5 replaces it with the WebView shell.
class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply {
            text = getString(R.string.app_name) + " " + BuildConfig.VERSION_NAME
            textSize = 20f
            setPadding(48, 96, 48, 48)
        })
    }
}
