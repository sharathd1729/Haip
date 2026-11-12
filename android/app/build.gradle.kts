plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing comes from the CI environment (GitHub secrets, see .github/workflows/calls-app-apk.yml). Nothing secret
// lives in the repo; without these variables only the debug build is signed (with the runner's debug key).
val releaseKeystore: String? = System.getenv("ANDROID_KEYSTORE_PATH")

android {
    namespace = "com.genhaip.calls"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.genhaip.calls"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("VERSION_NAME") ?: "0.1.0-dev"
        buildConfigField("String", "HAIP_BASE_URL", "\"${System.getenv("HAIP_BASE_URL") ?: "https://genhaip.com"}\"")
    }

    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (releaseKeystore != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
