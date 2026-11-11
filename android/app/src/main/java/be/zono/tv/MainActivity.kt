package be.zono.tv

import android.annotation.SuppressLint
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.TextureView
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Zono for Android TV: the same app as Zono for LG TV (the web app in assets/web, built from ../webos),
 * with video from Android's own player (ExoPlayer: HLS, MPEG-TS, MKV, AC3, 4K).
 *
 * - The page talks to [Bridge] (window.ZonoAndroid): load / play / pause / seek / stop, and where the picture goes.
 * - The player reports back with window.ZonoVideoEvent(type, position, duration, paused, errorCode).
 * - Requests to the IPTV provider go through /proxy?u=… here, so the page has no browser limits (like on LG).
 */
@OptIn(UnstableApi::class)
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private lateinit var player: ExoPlayer
    private lateinit var videoBox: AspectRatioFrameLayout
    private val main = Handler(Looper.getMainLooper())
    private var mode = 0 // 0 hidden, 1 small picture (above the page), 2 full screen (behind the page)
    private val ticker = object : Runnable {
        override fun run() {
            if (player.isPlaying) send("timeupdate")
            main.postDelayed(this, 500)
        }
    }
    private val assets by lazy {
        WebViewAssetLoader.Builder().addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }

        val http = DefaultHttpDataSource.Factory()
            .setUserAgent(AGENT)
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(20_000)
        player = ExoPlayer.Builder(this, DefaultRenderersFactory(this).setEnableDecoderFallback(true))
            .setMediaSourceFactory(DefaultMediaSourceFactory(this).setDataSourceFactory(http))
            .build()

        // the picture: a TextureView, so it can sit above the page (small picture) or behind it (full screen)
        videoBox = AspectRatioFrameLayout(this).apply { resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT; visibility = View.GONE }
        val texture = TextureView(this)
        videoBox.addView(texture, FrameLayout.LayoutParams(-1, -1, Gravity.CENTER))
        player.setVideoTextureView(texture)
        player.addListener(object : Player.Listener {
            override fun onVideoSizeChanged(size: VideoSize) {
                if (size.height > 0) videoBox.setAspectRatio(size.width * size.pixelWidthHeightRatio / size.height)
            }
            override fun onPlaybackStateChanged(state: Int) {
                when (state) {
                    Player.STATE_BUFFERING -> send("waiting")
                    Player.STATE_READY -> { if (!announced) { announced = true; send("loadedmetadata") }; if (player.playWhenReady) send("playing") }
                    Player.STATE_ENDED -> send("ended")
                }
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) { if (isPlaying) send("playing") }
            override fun onPlayerError(error: PlaybackException) {
                val code = if (error.errorCode == PlaybackException.ERROR_CODE_BEHIND_LIVE_WINDOW) 0 else 4
                if (code == 0) { player.seekToDefaultPosition(); player.prepare(); return }
                send("error", code)
            }
        })

        web = WebView(this).apply {
            setBackgroundColor(Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW // channel logos and posters are often http
            settings.allowFileAccess = false
            // the app is laid out for a 1920 x 1080 screen (like on LG): show that whole page on any TV,
            // whatever the screen density or font size setting (otherwise everything is blown up)
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            settings.textZoom = 100
            settings.setSupportZoom(false)
            settings.builtInZoomControls = false
            setInitialScale((resources.displayMetrics.widthPixels * 100) / 1920)
            isFocusable = true
            isFocusableInTouchMode = true
            addJavascriptInterface(Bridge(), "ZonoAndroid")
            webViewClient = object : WebViewClientCompat() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    val url = request.url
                    if (url.host == HOST && url.path == "/proxy") return proxy(url.getQueryParameter("u") ?: "")
                    return assets.shouldInterceptRequest(url)
                }
            }
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        root.addView(videoBox, FrameLayout.LayoutParams(0, 0))
        root.addView(web, FrameLayout.LayoutParams(-1, -1))
        setContentView(root)
        web.loadUrl("https://$HOST/assets/web/index.html")
        web.requestFocus()
        main.post(ticker)
    }

    private var announced = false

    /** The provider, reached by the app (no browser limits), with the same agent as Zono for Windows. */
    private fun proxy(target: String): WebResourceResponse {
        val headers = mapOf("Access-Control-Allow-Origin" to "*", "Cache-Control" to "no-store")
        return try {
            var url = target
            var connection: HttpURLConnection
            var hops = 0
            while (true) {
                connection = URL(url).openConnection() as HttpURLConnection
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 15_000
                connection.readTimeout = 120_000
                connection.setRequestProperty("User-Agent", AGENT)
                val code = connection.responseCode
                if (code in 300..399 && hops++ < 6) {
                    val next = connection.getHeaderField("Location") ?: break
                    url = URL(URL(url), next).toString()
                    connection.disconnect()
                    continue
                }
                break
            }
            val code = connection.responseCode
            val body = if (code >= 400) connection.errorStream ?: ByteArrayInputStream(ByteArray(0)) else connection.inputStream
            val type = connection.contentType?.substringBefore(';')?.trim()?.ifEmpty { null } ?: "application/octet-stream"
            WebResourceResponse(type, "utf-8", code, connection.responseMessage?.ifBlank { null } ?: "OK", headers, body)
        } catch (problem: Exception) {
            WebResourceResponse("text/plain", "utf-8", 502, "Bad Gateway", headers, ByteArrayInputStream((problem.message ?: "error").toByteArray()))
        }
    }

    /** window.ZonoVideoEvent(type, position s, duration s, paused, code) */
    private fun send(type: String, code: Int = 0) {
        val duration = if (player.duration == C.TIME_UNSET || player.isCurrentMediaItemLive) -1.0 else player.duration / 1000.0
        val position = player.currentPosition / 1000.0
        val paused = !player.playWhenReady
        web.evaluateJavascript("window.ZonoVideoEvent && ZonoVideoEvent('$type', $position, $duration, $paused, $code)", null)
    }

    /** What the page calls. Runs on a background thread: everything goes to the main thread. */
    inner class Bridge {
        @JavascriptInterface fun load(url: String) = main.post {
            announced = false
            val item = MediaItem.Builder().setUri(url)
            if (url.substringBefore('?').endsWith(".m3u8", true)) item.setMimeType(MimeTypes.APPLICATION_M3U8)
            player.setMediaItem(item.build())
            player.prepare()
        }
        @JavascriptInterface fun play() = main.post { player.playWhenReady = true }
        @JavascriptInterface fun pause() = main.post { player.playWhenReady = false }
        @JavascriptInterface fun seek(ms: Long) = main.post { player.seekTo(ms) }
        @JavascriptInterface fun stop() = main.post { player.stop(); player.clearMediaItems() }
        @JavascriptInterface fun exit() = main.post { finish() }
        /** Where the picture goes: 0 hidden, 1 small picture at x, y, w, h (page pixels of 1920 wide), 2 full screen. */
        @JavascriptInterface fun rect(newMode: Int, x: Double, y: Double, w: Double, h: Double) = main.post {
            mode = newMode
            val scale = web.width / 1920.0
            val params = videoBox.layoutParams as FrameLayout.LayoutParams
            when (newMode) {
                0 -> videoBox.visibility = View.GONE
                1 -> {
                    params.width = (w * scale).toInt(); params.height = (h * scale).toInt()
                    params.leftMargin = (x * scale).toInt(); params.topMargin = (y * scale).toInt()
                    params.gravity = Gravity.TOP or Gravity.START
                    videoBox.layoutParams = params
                    videoBox.visibility = View.VISIBLE
                    videoBox.bringToFront() // above the page
                }
                else -> {
                    params.width = -1; params.height = -1; params.leftMargin = 0; params.topMargin = 0
                    videoBox.layoutParams = params
                    videoBox.visibility = View.VISIBLE
                    web.bringToFront() // the page (live bar, channel list) on top of the picture
                    web.requestFocus()
                }
            }
        }
    }

    /** Keys the page does not get by itself from an Android TV remote. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val code = when (event.keyCode) {
            KeyEvent.KEYCODE_BACK -> 461
            KeyEvent.KEYCODE_CHANNEL_UP -> 33
            KeyEvent.KEYCODE_CHANNEL_DOWN -> 34
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> 10252
            KeyEvent.KEYCODE_MEDIA_PLAY -> 415
            KeyEvent.KEYCODE_MEDIA_PAUSE -> 19
            KeyEvent.KEYCODE_MEDIA_STOP -> 413
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> 417
            KeyEvent.KEYCODE_MEDIA_REWIND -> 412
            else -> 0
        }
        if (code == 0) return super.dispatchKeyEvent(event)
        if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
            web.evaluateJavascript("window.Zono && Zono.key($code)", null)
        }
        return true
    }

    override fun onPause() {
        super.onPause()
        player.playWhenReady = false
        web.evaluateJavascript("window.ZonoVideoEvent && ZonoVideoEvent('pause', ${player.currentPosition / 1000.0}, -1, true, 0)", null)
        web.onPause()
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        player.release()
        web.destroy()
        super.onDestroy()
    }


    companion object {
        const val HOST = "appassets.androidplatform.net"
        const val AGENT = "VLC/3.0 LibVLC/3.0"
    }
}
