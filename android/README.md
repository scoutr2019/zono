# Zono TV (Android TV)

First version of Zono for Android TV, Google TV, Nvidia Shield, Fire TV and Android TV boxes.
Kotlin + Jetpack Compose, playback with Media3 (ExoPlayer). Same look and the same four languages as Zono for Windows.

What it does:

- Connect an Xtream Codes subscription or an M3U link (stored only on the device).
- Discover: continue watching, favourite channels, 4K channels, new and top-rated movies, new series.
- Live TV by group, 4K channels first; ▲▼ or CH+/CH− zaps in the player; hold OK on a channel to make it a favourite.
- Movies and series (seasons and episodes, next episode plays automatically), resume where you stopped.
- Search across channels, movies and series.
- Nederlands, Français, English, Deutsch (or the device language).

## Build

Needs JDK 17+ and the Android SDK (platform 35).

    ./gradlew testDebugUnitTest      # unit tests + screenshots of the screens in app/build/screens
    ./gradlew assembleDebug          # app/build/outputs/apk/debug/app-debug.apk

Release builds are signed with the Zono TV key, which is **not** in this repository:

    ZONO_TV_KEYSTORE=/path/zono-tv.jks ZONO_TV_KEYSTORE_PASSWORD=... ./gradlew assembleRelease

Every update must be signed with the same key, or Android refuses to install it over the old version.

## Install on a TV without the store

1. On the TV: Settings → Device preferences → About → click "Build" 7 times (developer options).
2. Install the free app **Downloader** (by AFTVnews) from the Play Store / Amazon Appstore and allow it to install apps.
3. In Downloader, type the link to the APK and install.

Or with a computer on the same network: `adb connect <tv-ip>` and `adb install Zono-TV.apk`.
