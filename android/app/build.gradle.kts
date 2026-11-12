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
        buildConfigField("String", "HAIP_BASE_URL", "\"${System.getenv("HAIP_BASE_URL") ?: "https://www.genhaip.com"}\"")
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

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.9.1")         // background sync, survives reboots
    implementation("androidx.security:security-crypto:1.0.0")      // Keystore-backed storage for the device token
    implementation("com.squareup.okhttp3:okhttp:4.12.0")           // streaming multipart upload with Content-Length
    testImplementation("junit:junit:4.13.2")
}
