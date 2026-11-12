// Built only in CI (.github/workflows/calls-app-apk.yml); no Android Studio or SDK needed on a laptop.
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
