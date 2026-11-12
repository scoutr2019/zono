plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Android TV shows the same app as Zono for LG TV (../../webos); only the video uses Android's own player.
val webAssets = layout.buildDirectory.dir("web-assets")
val syncWeb by tasks.registering(Sync::class) {
    from("../../webos") { include("index.html", "style.css", "js/**", "img/**") }
    into(webAssets.map { it.dir("web") })
}

android {
    namespace = "be.zono.tv"
    compileSdk = 36
    defaultConfig {
        applicationId = "be.zono.tv"
        minSdk = 24
        targetSdk = 36
        versionCode = 15
        versionName = "2.3.8"
    }
    sourceSets["main"].assets.srcDir(webAssets)
    signingConfigs {
        create("release") {
            // The key that signs every Zono TV version. Keep zono-tv.jks safe: updates need the same key.
            val keystore = System.getenv("ZONO_TV_KEYSTORE")
            if (keystore != null) {
                storeFile = file(keystore)
                storePassword = System.getenv("ZONO_TV_KEYSTORE_PASSWORD")
                keyAlias = "zono-tv"
                keyPassword = System.getenv("ZONO_TV_KEYSTORE_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (System.getenv("ZONO_TV_KEYSTORE") != null) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { buildConfig = true }
    testOptions { unitTests.isReturnDefaultValues = true }
}

tasks.named("preBuild") { dependsOn(syncWeb) }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
    implementation("com.google.code.gson:gson:2.11.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
