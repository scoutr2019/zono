package be.zono.tv

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView

/** Full-screen player. Live TV: ▲▼ (or CH+/CH−) zaps through the group. Movies and episodes resume where you were. */
@OptIn(UnstableApi::class)
class PlayerActivity : ComponentActivity() {
    private lateinit var player: ExoPlayer
    private lateinit var view: PlayerView
    private lateinit var banner: LinearLayout
    private lateinit var bannerTitle: TextView
    private lateinit var bannerInfo: TextView
    private val handler = Handler(Looper.getMainLooper())
    private val hideBanner = Runnable { banner.animate().alpha(0f).setDuration(300).start() }
    private var queue: List<Item> = emptyList()
    private var index = 0
    private var retried = false

    private val live get() = queue.getOrNull(index)?.kind == "live"

    override fun attachBaseContext(base: Context) = super.attachBaseContext(Lang.wrap(base))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        queue = Library.queue
        if (queue.isEmpty()) { finish(); return }
        index = (savedInstanceState?.getInt("index") ?: intent.getIntExtra("index", 0)).coerceIn(0, queue.size - 1)

        val http = DefaultHttpDataSource.Factory()
            .setUserAgent(Xtream.AGENT)
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(20_000)
        // decoders built into the TV box first; the extension renderers mode lets software fall back where possible
        val renderers = DefaultRenderersFactory(this).setEnableDecoderFallback(true)
        player = ExoPlayer.Builder(this, renderers)
            .setMediaSourceFactory(DefaultMediaSourceFactory(this).setDataSourceFactory(http))
            .build()
        player.addListener(object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) = failed(error)
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) retried = false
                if (state == Player.STATE_ENDED && !live) finishedOne()
            }
        })

        view = PlayerView(this).apply {
            player = this@PlayerActivity.player
            setShowBuffering(PlayerView.SHOW_BUFFERING_ALWAYS)
            setShowNextButton(false)
            setShowPreviousButton(false)
            controllerShowTimeoutMs = 4000
            keepScreenOn = true
            setBackgroundColor(Color.BLACK)
        }
        banner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(14), dp(22), dp(14))
            background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(0xE0111116.toInt()) }
            alpha = 0f
        }
        bannerTitle = TextView(this).apply { setTextColor(Color.WHITE); setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f) }
        bannerInfo = TextView(this).apply { setTextColor(0xFF9B9BA8.toInt()); setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f) }
        banner.addView(bannerTitle)
        banner.addView(bannerInfo)
        val root = FrameLayout(this)
        root.addView(view, FrameLayout.LayoutParams(-1, -1))
        root.addView(banner, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.START).apply { setMargins(dp(40), dp(32), 0, 0) })
        setContentView(root)
        start(resume = intent.getBooleanExtra("resume", true))
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun start(resume: Boolean) {
        val item = queue[index]
        val media = MediaItem.Builder().setUri(item.url).setMediaId(item.id)
            .setMediaMetadata(MediaMetadata.Builder().setTitle(item.title).build())
        if (item.url.contains(".m3u8", true)) media.setMimeType(androidx.media3.common.MimeTypes.APPLICATION_M3U8)
        player.setMediaItem(media.build())
        var info = if (live) "${index + 1} / ${queue.size}" + (if (queue.size > 1) "   ·   " + getString(R.string.zap_hint) else "") else ""
        if (!live && resume) {
            val saved = Prefs.progress(this).firstOrNull { it.item.id == item.id }
            if (saved != null && saved.position > 0) {
                player.seekTo(saved.position)
                info = getString(R.string.resume)
            }
        }
        if (live) {
            Prefs.setLastChannel(this, item.id)
            view.useController = true
            view.setShowFastForwardButton(false)
            view.setShowRewindButton(false)
        }
        player.prepare()
        player.playWhenReady = true
        show(item.title + if (live && item.uhd) "  ·  4K" else "", info)
    }

    private fun show(title: String, info: String) {
        bannerTitle.text = title
        bannerInfo.text = info
        bannerInfo.visibility = if (info.isEmpty()) View.GONE else View.VISIBLE
        handler.removeCallbacks(hideBanner)
        banner.animate().cancel()
        banner.alpha = 1f
        handler.postDelayed(hideBanner, 3500)
    }

    private fun zap(step: Int) {
        if (queue.size < 2) return
        index = (index + step + queue.size) % queue.size
        retried = false
        player.stop()
        start(resume = false)
    }

    private fun failed(error: PlaybackException) {
        // live streams fall behind or hiccup now and then: try once more before showing a message
        if (error.errorCode == PlaybackException.ERROR_CODE_BEHIND_LIVE_WINDOW) {
            player.seekToDefaultPosition(); player.prepare(); return
        }
        val item = queue[index]
        if (live && retried && item.url.endsWith(".m3u8")) {
            // some providers only send live TV as a plain .ts stream
            queue = queue.toMutableList().also { it[index] = item.copy(url = item.url.removeSuffix(".m3u8") + ".ts") }
            retried = false
            player.stop()
            start(resume = false)
            return
        }
        if (!retried) {
            retried = true
            handler.postDelayed({ player.prepare(); player.playWhenReady = true }, 1500)
            return
        }
        show(queue[index].title, getString(R.string.playback_error))
    }

    private fun finishedOne() {
        val item = queue[index]
        Prefs.saveProgress(this, item, player.duration, player.duration)
        if (item.kind == "episode" && index + 1 < queue.size) {
            index += 1
            start(resume = false)
            show(queue[index].title, getString(R.string.next_episode))
        } else finish()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (live && event.action == KeyEvent.ACTION_DOWN) {
            val controls = view.isControllerFullyVisible
            when (event.keyCode) {
                KeyEvent.KEYCODE_CHANNEL_UP -> { zap(-1); return true }
                KeyEvent.KEYCODE_CHANNEL_DOWN -> { zap(1); return true }
                KeyEvent.KEYCODE_DPAD_UP -> if (!controls) { zap(-1); return true }
                KeyEvent.KEYCODE_DPAD_DOWN -> if (!controls) { zap(1); return true }
                KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> if (!controls) {
                    val item = queue[index]
                    show(item.title + if (item.uhd) "  ·  4K" else "", "${index + 1} / ${queue.size}   ·   " + getString(R.string.zap_hint))
                    view.showController()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    private fun saveProgress() {
        val item = queue.getOrNull(index) ?: return
        if (item.kind == "live" || player.duration == C.TIME_UNSET) return
        Prefs.saveProgress(this, item, player.currentPosition, player.duration)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putInt("index", index)
    }

    override fun onStart() {
        super.onStart()
        if (::player.isInitialized && player.playbackState == Player.STATE_IDLE) start(resume = true)
    }

    override fun onStop() {
        super.onStop()
        if (!::player.isInitialized) return
        saveProgress()
        player.stop()
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
        if (::player.isInitialized) player.release()
    }
}
