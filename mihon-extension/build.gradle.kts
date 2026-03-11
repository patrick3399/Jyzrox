plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.serialization")
}

android {
    namespace = "eu.kanade.tachiyomi.extension.all.jyzrox"
    compileSdk = 34

    defaultConfig {
        applicationId = "eu.kanade.tachiyomi.extension.all.jyzrox"
        minSdk = 21
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }
}

dependencies {
    // Tachiyomi / Mihon extension API — provided at runtime by the host app
    compileOnly("com.github.tachiyomiorg:extensions-lib:1.5")
    compileOnly("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.2")
    compileOnly("com.squareup.okhttp3:okhttp:5.0.0-alpha.11")
}
